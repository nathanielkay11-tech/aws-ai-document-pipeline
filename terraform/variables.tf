variable "region" {
  description = "The AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "bedrock_model_id" {
  description = "The Bedrock model ID to use"
  type        = string
  default     = "anthropic.claude-sonnet-4-20250514-v1:0"
}

variable "s3_bucket_name" {
  description = "The name of the S3 bucket to use"
  type        = string
  default     = "claims-pipeline-nk"
}

variable "dynamodb_table_name" {
  description = "The name of the DynamoDB table to use"
  type        = string
  default     = "claims-processed"
}

variable "environment" {
  description = "The environment to deploy resources"
  type        = string
  default     = "dev"
}

variable "sns_internal_topic_name" {
  description = "The name of the internal SNS topic to use"
  type        = string
  default     = "claims-internal-alerts"
}

variable "sns_claimant_topic_name" {
  description = "The name of the claimant SNS topic to use"
  type        = string
  default     = "claims-claimant-notifications"
}

variable "risk_threshold" {
  description = "The risk threshold for claims processing"
  type        = number
  default     = 50000
}