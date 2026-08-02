# Security Compliance Tracker

## Architecture
- EventBridge → Lambda → SharePoint API
- Extract → Validate → Deduplicate → S3/Redshift

## Features
- OAuth2 token management
- Retry logic with exponential backoff
- Rate limiting handling
- Data validation
- Deduplication

## Deployment
```bash
terraform init
terraform apply
```

## Monitoring
- CloudWatch logs
- Execution metrics
- Error tracking
