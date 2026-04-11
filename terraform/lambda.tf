# --- SQS Dead Letter Queue ---

resource "aws_sqs_queue" "lambda_dlq" {
  name                       = "claims-pipeline-dlq"
  message_retention_seconds  = 1209600
  visibility_timeout_seconds = 60

  tags = {
    Name        = "claims-pipeline-dlq"
    Environment = var.environment
    Project     = "ai-claims-pipeline"
  }
}

# --- Lambda Function: Claims Pipeline Processor ---

resource "aws_lambda_function" "claims_processor" {
  filename         = "../src/lambda_function.zip"
  function_name    = "claims-pipeline-processor"
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  timeout          = 300
  source_code_hash = filebase64sha256("../src/lambda_function.zip")

  dead_letter_config {
    target_arn = aws_sqs_queue.lambda_dlq.arn
  }

  environment {
    variables = {
      DYNAMODB_TABLE   = var.dynamodb_table_name
      SNS_INTERNAL_ARN = aws_sns_topic.claims_internal.arn
      SNS_CLAIMANT_ARN = aws_sns_topic.claims_claimant.arn
      BEDROCK_MODEL_ID = var.bedrock_model_id
      RISK_THRESHOLD   = var.risk_threshold
      ENVIRONMENT      = var.environment
    }
  }

  tags = {
    Name        = "claims-pipeline-processor"
    Environment = var.environment
    Project     = "ai-claims-pipeline"
  }
}

# --- Lambda Permission: Allow S3 to Invoke Lambda ---

resource "aws_lambda_permission" "s3_invoke_lambda" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.claims_processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.claims_bucket.arn

  depends_on = [aws_lambda_function.claims_processor]
}

# --- DLQ Processor Lambda Function ---

resource "aws_lambda_function" "dlq_processor" {
  filename         = "../src/dlq_processor.zip"
  function_name    = "claims-pipeline-dlq-processor"
  role             = aws_iam_role.dlq_processor_role.arn
  handler          = "dlq_processor.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  source_code_hash = filebase64sha256("../src/dlq_processor.zip")

  environment {
    variables = {
      SNS_INTERNAL_ARN = aws_sns_topic.claims_internal.arn
      SNS_CLAIMANT_ARN = aws_sns_topic.claims_claimant.arn
      S3_BUCKET_NAME   = aws_s3_bucket.claims_bucket.id
    }
  }

  tags = {
    Name        = "claims-pipeline-dlq-processor"
    Environment = var.environment
    Project     = "ai-claims-pipeline"
  }
}

# --- SQS Event Source Mapping ---

resource "aws_lambda_event_source_mapping" "dlq_trigger" {
  event_source_arn = aws_sqs_queue.lambda_dlq.arn
  function_name    = aws_lambda_function.dlq_processor.arn
  batch_size       = 1
}