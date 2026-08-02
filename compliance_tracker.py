import json, boto3, hashlib, logging, requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, sha2, concat_ws, when, count, lit
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger()
logger.setLevel(logging.INFO)

class SharePointConnector:
    def __init__(self, url: str, client_id: str, secret: str, max_retries: int = 3):
        self.url = url
        self.client_id = client_id
        self.secret = secret
        self.access_token = None
        self.token_expiry = None
        self.session = self._create_session()
    
    def _create_session(self):
        session = requests.Session()
        retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def _get_token(self, force_refresh=False):
        try:
            if self.access_token and self.token_expiry and not force_refresh:
                if datetime.utcnow() < self.token_expiry:
                    return self.access_token
            
            url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            data = {"client_id": self.client_id, "client_secret": self.secret, "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}
            response = self.session.post(url, data=data, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"Token auth failed: {response.status_code}")
                return None
            
            token_data = response.json()
            self.access_token = token_data.get('access_token')
            self.token_expiry = datetime.utcnow() + timedelta(seconds=3240)
            return self.access_token
        except Exception as e:
            logger.error(f"Token fetch failed: {str(e)}")
            return None
    
    def extract_items(self, list_name: str, max_retries: int = 3):
        items = []
        skip = 0
        top = 5000
        
        for attempt in range(max_retries):
            try:
                token = self._get_token()
                if not token:
                    continue
                
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                url = f"{self.url}/sites/Compliance/_api/web/lists/getbytitle('{list_name}')/items"
                params = {"$top": top, "$skip": skip}
                
                response = self.session.get(url, headers=headers, params=params, timeout=30)
                
                if response.status_code == 401:
                    continue
                elif response.status_code == 429:
                    wait_time = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limited, waiting {wait_time}s")
                    import time; time.sleep(wait_time)
                    continue
                elif response.status_code == 200:
                    data = response.json()
                    batch = data.get('value', [])
                    if not batch:
                        break
                    items.extend(batch)
                    skip += top
                    attempt = 0
            except Exception as e:
                logger.error(f"Extraction error: {str(e)}")
        
        logger.info(f"Extracted {len(items)} compliance items")
        return items

class ComplianceProcessor:
    def __init__(self):
        self.spark = SparkSession.builder.appName("ComplianceTracker").config("spark.sql.adaptive.enabled", "true").getOrCreate()
    
    def normalize(self, items: List[Dict]):
        normalized = []
        for i, item in enumerate(items):
            try:
                required = ['ID', 'Title', 'ControlObjective', 'Status']
                if not all(f in item and item[f] for f in required):
                    continue
                
                record = {
                    'compliance_id': str(item['ID']),
                    'item_name': str(item.get('Title', '')).strip(),
                    'control_objective': str(item.get('ControlObjective', '')).strip(),
                    'status': item['Status'],
                    'owner': str(item.get('Owner', 'Unassigned')).strip(),
                    'hash': hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest(),
                    'extracted_date': datetime.utcnow().isoformat()
                }
                normalized.append(record)
            except Exception as e:
                logger.error(f"Row {i}: {str(e)}")
        return normalized
    
    def deduplicate(self, df):
        original = df.count()
        df_deduped = df.dropDuplicates(["hash"])
        removed = original - df_deduped.count()
        logger.info(f"Removed {removed} duplicates")
        return df_deduped, removed
    
    def write_s3(self, df, bucket: str, prefix: str):
        try:
            path = f"s3://{bucket}/{prefix}/year={datetime.now().year}/month={datetime.now().month}/"
            df.write.mode("overwrite").format("parquet").option("compression", "snappy").save(path)
            logger.info(f"Wrote to {path}")
            return True
        except Exception as e:
            logger.error(f"S3 write failed: {str(e)}")
            return False

def lambda_handler(event, context):
    try:
        logger.info("Starting compliance extraction")
        connector = SharePointConnector("https://company.sharepoint.com", "CLIENT_ID", "SECRET")
        items = connector.extract_items("ComplianceTracker")
        
        if not items:
            return {'statusCode': 200, 'body': 'No items'}
        
        processor = ComplianceProcessor()
        normalized = processor.normalize(items)
        return {'statusCode': 200, 'body': json.dumps({'items': len(normalized)})}
    except Exception as e:
        logger.error(f"Failed: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
