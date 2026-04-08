# --- SNS Topic: Internal Claims Team Alerts ---

resource "aws_sns_topic" "claims_internal" {
  name = var.sns_internal_topic_name

  tags = {
    Name        = var.sns_internal_topic_name
    Environment = var.environment
    Project     = "ai-claims-pipeline"
  }
}

# --- SNS Topic: Claimant Notifications ---

resource "aws_sns_topic" "claims_claimant" {
  name = var.sns_claimant_topic_name

  tags = {
    Name        = var.sns_claimant_topic_name
    Environment = var.environment
    Project     = "ai-claims-pipeline"
  }
}

# --- SNS Subscription: Internal Email Alert ---

resource "aws_sns_topic_subscription" "internal_email" {
  topic_arn = aws_sns_topic.claims_internal.arn
  protocol  = "email"
  endpoint  = "internal-claims-team@example.com"
}

# --- SNS Subscription: Claimant Email Notification ---

resource "aws_sns_topic_subscription" "claimant_email" {
  topic_arn = aws_sns_topic.claims_claimant.arn
  protocol  = "email"
  endpoint  = "claimant-notifications@example.com"
}