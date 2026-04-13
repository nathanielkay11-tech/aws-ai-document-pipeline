# ─────────────────────────────────────────────
# CLAIMS PROCESSOR LAMBDA — IAM Role & Policy
# ─────────────────────────────────────────────

resource "aws_iam_role" "claims_processor_lambda" {
  name = "${var.lambda_function_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
  }
}

resource "aws_iam_policy" "claims_processor_lambda" {
  name        = "${var.lambda_function_name}-policy"
  description = "Least-privilege policy for the insurance claims processor Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.lambda_function_name}:*"
      },
      {
        Sid    = "S3GetObject"
        Effect = "Allow"
        Action = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.claims_uploads.arn}/*"
      },
      {
        Sid    = "TextractAnalyze"
        Effect = "Allow"
        Action = [
          "textract:DetectDocumentText",
          "textract:AnalyzeDocument"
        ]
        Resource = "*"
      },
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:*:inference-profile/*"
        ]
      },
      {
        Sid    = "DynamoDBPutItem"
        Effect = "Allow"
        Action = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.claims_results.arn
      },
      {
        Sid    = "SNSPublish"
        Effect = "Allow"
        Action = ["sns:Publish"]
        Resource = [
          aws_sns_topic.internal.arn,
          aws_sns_topic.claimant.arn
        ]
      },
      {
        Sid    = "SQSSendMessage"
        Effect = "Allow"
        Action = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.dlq.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "claims_processor_lambda" {
  role       = aws_iam_role.claims_processor_lambda.name
  policy_arn = aws_iam_policy.claims_processor_lambda.arn
}


# ─────────────────────────────────────────────
# DLQ PROCESSOR LAMBDA — IAM Role & Policy
# ─────────────────────────────────────────────

resource "aws_iam_role" "dlq_processor_lambda" {
  name = "${var.dlq_processor_function_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
  }
}

resource "aws_iam_policy" "dlq_processor_lambda" {
  name        = "${var.dlq_processor_function_name}-policy"
  description = "Least-privilege policy for the DLQ processor Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.dlq_processor_function_name}:*"
      },
      {
        Sid    = "SNSPublish"
        Effect = "Allow"
        Action = ["sns:Publish"]
        Resource = [
          aws_sns_topic.internal.arn,
          aws_sns_topic.claimant.arn
        ]
      },
      {
        Sid    = "SQSConsume"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.dlq.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "dlq_processor_lambda" {
  role       = aws_iam_role.dlq_processor_lambda.name
  policy_arn = aws_iam_policy.dlq_processor_lambda.arn
}