# --- IAM Role: Lambda Execution Role ---

resource "aws_iam_role" "lambda_execution_role" {
  name = "claims-pipeline-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Environment = var.environment
    Project     = "ai-claims-pipeline"
  }
}

# --- IAM Policy: Lambda Least Privilege Permissions ---

resource "aws_iam_policy" "lambda_policy" {
  name        = "claims-pipeline-lambda-policy"
  description = "Least privilege policy for claims pipeline Lambda function"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3ReadAccess"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.claims_bucket.arn}/*"
      },
      {
        Sid    = "TextractAccess"
        Effect = "Allow"
        Action = [
          "textract:DetectDocumentText",
          "textract:AnalyzeDocument"
        ]
        Resource = "*"
      },
      {
        Sid    = "BedrockAccess"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:251478237846:inference-profile/*"
        ]
      },
      {
        Sid      = "DynamoDBWriteAccess"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.claims_table.arn
      },
      {
        Sid    = "SNSPublishAccess"
        Effect = "Allow"
        Action = ["sns:Publish"]
        Resource = [
          aws_sns_topic.claims_internal.arn,
          aws_sns_topic.claims_claimant.arn
        ]
      },
      {
        Sid      = "SQSDeadLetterQueue"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.lambda_dlq.arn
      },
      {
        Sid    = "CloudWatchLogsAccess"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# --- Attach Policy to Role ---

resource "aws_iam_role_policy_attachment" "lambda_policy_attachment" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

# --- IAM Role: DLQ Processor Lambda ---

resource "aws_iam_role" "dlq_processor_role" {
  name = "claims-pipeline-dlq-processor-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Environment = var.environment
    Project     = "ai-claims-pipeline"
  }
}

# --- IAM Policy: DLQ Processor Least Privilege ---

resource "aws_iam_policy" "dlq_processor_policy" {
  name        = "claims-pipeline-dlq-processor-policy"
  description = "Least privilege policy for DLQ processor Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SNSPublishAccess"
        Effect = "Allow"
        Action = ["sns:Publish"]
        Resource = [
          aws_sns_topic.claims_internal.arn,
          aws_sns_topic.claims_claimant.arn
        ]
      },
      {
        Sid    = "SQSReceiveAccess"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.lambda_dlq.arn
      },
      {
        Sid    = "CloudWatchLogsAccess"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# --- Attach Policy to DLQ Processor Role ---

resource "aws_iam_role_policy_attachment" "dlq_processor_policy_attachment" {
  role       = aws_iam_role.dlq_processor_role.name
  policy_arn = aws_iam_policy.dlq_processor_policy.arn
}
