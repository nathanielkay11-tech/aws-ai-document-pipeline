# --- Outputs: Summary of deployed resources ---

output "s3_bucket_name" {
  description = "The name of the S3 claims upload bucket"
  value       = aws_s3_bucket.claims_bucket.id
}

output "dynamodb_table_name" {
  description = "The name of the DynamoDB claims results table"
  value       = aws_dynamodb_table.claims_table.id
}

output "lambda_function_name" {
  description = "The name of the Lambda claims processor function"
  value       = aws_lambda_function.claims_processor.function_name
}

output "sns_internal_arn" {
  description = "The ARN of the internal claims team SNS topic"
  value       = aws_sns_topic.claims_internal.arn
}

output "sns_claimant_arn" {
  description = "The ARN of the claimant notifications SNS topic"
  value       = aws_sns_topic.claims_claimant.arn
}

output "bedrock_model_id" {
  description = "The Bedrock model ID being used"
  value       = var.bedrock_model_id
}