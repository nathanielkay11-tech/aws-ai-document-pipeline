# ─────────────────────────────────────────────
# SQS DEAD LETTER QUEUE
# ─────────────────────────────────────────────

resource "aws_sqs_queue" "dlq" {
  name                       = "${var.lambda_function_name}-dlq"
  visibility_timeout_seconds = 60      # Matches Lambda timeout
  message_retention_seconds  = 1209600 # 14 days

  tags = {
    Name        = "${var.lambda_function_name}-dlq"
    Environment = var.environment
  }
}


# ─────────────────────────────────────────────
# CLAIMS PROCESSOR LAMBDA
# ─────────────────────────────────────────────

resource "aws_lambda_function" "claims_processor" {
  function_name = var.lambda_function_name
  role          = aws_iam_role.claims_processor_lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.12"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory
  filename      = "${path.module}/../src/lambda_function.zip"

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  environment {
    variables = {
      DYNAMODB_TABLE    = var.dynamodb_table_name
      SNS_INTERNAL_ARN  = aws_sns_topic.internal.arn
      SNS_CLAIMANT_ARN  = aws_sns_topic.claimant.arn
      BEDROCK_MODEL_ID  = var.bedrock_model_id
      RISK_THRESHOLD    = tostring(var.risk_threshold)
      AWS_REGION_NAME = "us-east-1"
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.claims_processor_lambda
  ]

  tags = {
    Environment = var.environment
  }
}

# Allow S3 to invoke the claims processor Lambda
resource "aws_lambda_permission" "s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.claims_processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.claims_uploads.arn
}


# ─────────────────────────────────────────────
# DLQ PROCESSOR LAMBDA
# ─────────────────────────────────────────────

resource "aws_lambda_function" "dlq_processor" {
  function_name = var.dlq_processor_function_name
  role          = aws_iam_role.dlq_processor_lambda.arn
  handler       = "dlq_processor.lambda_handler"
  runtime       = "python3.12"
  timeout       = var.dlq_processor_timeout
  memory_size   = var.dlq_processor_memory
  filename      = "${path.module}/../src/dlq_processor.zip"

  environment {
    variables = {
      SNS_INTERNAL_ARN = aws_sns_topic.internal.arn
      SNS_CLAIMANT_ARN = aws_sns_topic.claimant.arn
      S3_BUCKET_NAME   = var.s3_bucket_name
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.dlq_processor_lambda
  ]

  tags = {
    Environment = var.environment
  }
}

# SQS event source mapping — DLQ triggers DLQ processor Lambda
resource "aws_lambda_event_source_mapping" "dlq_trigger" {
  event_source_arn = aws_sqs_queue.dlq.arn
  function_name    = aws_lambda_function.dlq_processor.arn
  batch_size       = 1
  enabled          = true
}
