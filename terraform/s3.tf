resource "aws_s3_bucket" "claims_uploads" {
  bucket = var.s3_bucket_name

  tags = {
    Name        = var.s3_bucket_name
    Environment = var.environment
  }
}

resource "aws_s3_bucket_public_access_block" "claims_uploads" {
  bucket = aws_s3_bucket.claims_uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "claims_uploads" {
  bucket = aws_s3_bucket.claims_uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_notification" "claims_uploads" {
  bucket = aws_s3_bucket.claims_uploads.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.claims_processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".pdf"
  }

  depends_on = [aws_lambda_permission.s3_invoke]
}
