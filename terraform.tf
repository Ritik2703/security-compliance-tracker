resource "aws_lambda_function" "compliance_tracker" {
  filename      = "lambda.zip"
  function_name = "compliance-tracker"
  role          = aws_iam_role.lambda_role.arn
  handler       = "compliance_tracker.lambda_handler"
  runtime       = "python3.11"
  timeout       = 300
  
  environment {
    variables = {
      SHAREPOINT_URL = "https://company.sharepoint.com"
    }
  }
}

resource "aws_iam_role" "lambda_role" {
  name = "compliance-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name   = "compliance-lambda-policy"
  role   = aws_iam_role.lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:*", "logs:*", "secretsmanager:GetSecretValue"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_events_rule" "daily_trigger" {
  name                = "compliance-daily"
  schedule_expression = "cron(0 2 * * ? *)"
}

resource "aws_events_target" "lambda_target" {
  rule      = aws_events_rule.daily_trigger.name
  target_id = "ComplianceLambda"
  arn       = aws_lambda_function.compliance_tracker.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.compliance_tracker.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_events_rule.daily_trigger.arn
}
