# --- S3 Bucket: Claims Upload Inbox ---

resource "aws_s3_bucket" "claims_bucket" {
  bucket = var.s3_bucket_name

  tags = {
    Name        = var.s3_bucket_name
    Environment = var.environment
    Project     = "ai-claims-pipeline"
  }
}

# --- Block all public access ---

resource "aws_s3_bucket_public_access_block" "claims_bucket_public_access" {
  bucket = aws_s3_bucket.claims_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- Enable encryption at rest ---

resource "aws_s3_bucket_server_side_encryption_configuration" "claims_bucket_encryption" {
  bucket = aws_s3_bucket.claims_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# --- S3 Event Notification: Trigger Lambda on PDF upload ---

resource "aws_s3_bucket_notification" "claims_bucket_notification" {
  bucket = aws_s3_bucket.claims_bucket.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.claims_processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".pdf"
  }

  depends_on = [aws_lambda_permission.s3_invoke_lambda]
}