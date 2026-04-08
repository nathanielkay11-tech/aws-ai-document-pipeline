# --- DynamoDB Table: Claims Results Storage ---

resource "aws_dynamodb_table" "claims_table" {
  name         = var.dynamodb_table_name
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "claim_id"

  attribute {
    name = "claim_id"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Name        = var.dynamodb_table_name
    Environment = var.environment
    Project     = "ai-claims-pipeline"
  }
}