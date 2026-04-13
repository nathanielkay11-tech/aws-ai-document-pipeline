output "s3_bucket_name" {
  description = "Name of the S3 claims upload bucket"
  value       = aws_s3_bucket.claims_uploads.bucket
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB claims results table"
  value       = aws_dynamodb_table.claims_results.name
}

output "lambda_function_name" {
  description = "Name of the claims processor Lambda function"
  value       = aws_lambda_function.claims_processor.function_name
}

output "sns_internal_arn" {
  description = "ARN of the internal claims team SNS topic"
  value       = aws_sns_topic.internal.arn
}

output "sns_claimant_arn" {
  description = "ARN of the claimant-facing SNS topic"
  value       = aws_sns_topic.claimant.arn
}

output "bedrock_model_id" {
  description = "Bedrock inference profile model ID in use"
  value       = var.bedrock_model_id
}

output "dlq_url" {
  description = "URL of the SQS Dead Letter Queue"
  value       = aws_sqs_queue.dlq.url
}

output "dlq_processor_function_name" {
  description = "Name of the DLQ processor Lambda function"
  value       = aws_lambda_function.dlq_processor.function_name
}
