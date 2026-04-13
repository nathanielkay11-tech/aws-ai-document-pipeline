variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment tag"
  type        = string
  default     = "dev"
}

# S3
variable "s3_bucket_name" {
  description = "Name of the S3 bucket for PDF uploads"
  type        = string
  default     = "insurance-claims-uploads-nk"
}

# DynamoDB
variable "dynamodb_table_name" {
  description = "Name of the DynamoDB table for claim results"
  type        = string
  default     = "insurance-claims-results"
}

# Bedrock
variable "bedrock_model_id" {
  description = "Bedrock inference profile ARN for Claude Sonnet 4.5"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "risk_threshold" {
  description = "Monetary threshold (USD) above which a claim is risk-flagged"
  type        = number
  default     = 50000
}

# SNS
variable "sns_internal_topic_name" {
  description = "SNS topic name for internal claims team notifications"
  type        = string
  default     = "claims-internal-notifications"
}

variable "sns_claimant_topic_name" {
  description = "SNS topic name for claimant-facing notifications"
  type        = string
  default     = "claims-claimant-notifications"
}

variable "sns_internal_email" {
  description = "Email endpoint for internal claims team SNS subscription"
  type        = string
  default     = "claims-team@example.com"
}

variable "sns_claimant_email" {
  description = "Email endpoint for claimant SNS subscription (placeholder)"
  type        = string
  default     = "claimant@example.com"
}

# Lambda — Claims Processor
variable "lambda_function_name" {
  description = "Name of the main claims processor Lambda function"
  type        = string
  default     = "insurance-claims-processor"
}

variable "lambda_timeout" {
  description = "Timeout in seconds for the claims processor Lambda"
  type        = number
  default     = 300
}

variable "lambda_memory" {
  description = "Memory in MB for the claims processor Lambda"
  type        = number
  default     = 512
}

# Lambda — DLQ Processor
variable "dlq_processor_function_name" {
  description = "Name of the Dead Letter Queue processor Lambda function"
  type        = string
  default     = "insurance-claims-dlq-processor"
}

variable "dlq_processor_timeout" {
  description = "Timeout in seconds for the DLQ processor Lambda"
  type        = number
  default     = 30
}

variable "dlq_processor_memory" {
  description = "Memory in MB for the DLQ processor Lambda"
  type        = number
  default     = 128
}
