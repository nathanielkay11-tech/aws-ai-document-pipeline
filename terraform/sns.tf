resource "aws_sns_topic" "internal" {
  name = var.sns_internal_topic_name

  tags = {
    Name        = var.sns_internal_topic_name
    Environment = var.environment
    Purpose     = "Internal claims team notifications"
  }
}

resource "aws_sns_topic" "claimant" {
  name = var.sns_claimant_topic_name

  tags = {
    Name        = var.sns_claimant_topic_name
    Environment = var.environment
    Purpose     = "Claimant-facing notifications"
  }
}

resource "aws_sns_topic_subscription" "internal_email" {
  topic_arn = aws_sns_topic.internal.arn
  protocol  = "email"
  endpoint  = var.sns_internal_email
}

resource "aws_sns_topic_subscription" "claimant_email" {
  topic_arn = aws_sns_topic.claimant.arn
  protocol  = "email"
  endpoint  = var.sns_claimant_email
}
