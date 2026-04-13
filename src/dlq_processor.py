"""
Insurance Claims Pipeline — Dead Letter Queue Processor
========================================================
Triggered by SQS event source mapping on the pipeline DLQ.
Fires exactly two SNS notifications per failed document:
  1. SNS-Internal — alert to claims team with CloudWatch investigation guidance
  2. SNS-Claimant — professional resubmission request with accepted formats

This function is intentionally minimal. All complex triage logic lives in
lambda_function.py. By the time a message reaches the DLQ, all Lambda
retry attempts have been exhausted — this is the last line of defence
before a claim is lost.

Known Limitations:
  - Claimant authentication is out of scope; the claimant email is sourced
    from the SNS topic subscription, not extracted from the failed document.
  - SLA reminder notifications are deferred to Phase 2.
"""

import os
import json
import logging

import boto3

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─────────────────────────────────────────────
# Environment variables
# ─────────────────────────────────────────────
SNS_INTERNAL_ARN = os.environ["SNS_INTERNAL_ARN"]
SNS_CLAIMANT_ARN = os.environ["SNS_CLAIMANT_ARN"]
S3_BUCKET_NAME   = os.environ["S3_BUCKET_NAME"]

# ─────────────────────────────────────────────
# AWS clients
# ─────────────────────────────────────────────
sns = boto3.client("sns")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def extract_object_key(record: dict) -> str:
    """
    Extract the original S3 object key from a DLQ SQS record.

    The DLQ message body is the original Lambda event payload serialised
    as a JSON string. We navigate:
      record["body"] -> JSON string
        -> {"Records": [{"s3": {"object": {"key": "..."}}}]}

    Falls back to a safe placeholder if parsing fails so notifications
    still fire rather than the DLQ processor itself erroring out.
    """
    try:
        body = json.loads(record["body"])
        return body["Records"][0]["s3"]["object"]["key"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.warning("Could not extract S3 key from DLQ record: %s", exc)
        return "UNKNOWN_DOCUMENT"


def publish_internal_alert(object_key: str):
    """Fire an SNS-Internal alert to the claims team."""
    subject = f"[PIPELINE ERROR] Processing Failed — {object_key}"
    message = (
        f"PIPELINE FAILURE ALERT\n"
        f"{'=' * 50}\n\n"
        f"A document failed processing after all Lambda retry attempts were exhausted.\n\n"
        f"DOCUMENT LOCATION\n"
        f"{'─' * 30}\n"
        f"S3 Bucket:  {S3_BUCKET_NAME}\n"
        f"S3 Key:     {object_key}\n"
        f"S3 URI:     s3://{S3_BUCKET_NAME}/{object_key}\n\n"
        f"INVESTIGATION STEPS\n"
        f"{'─' * 30}\n"
        f"1. Open the AWS CloudWatch console.\n"
        f"2. Navigate to Log Groups > /aws/lambda/insurance-claims-processor\n"
        f"3. Filter log streams by the approximate failure time.\n"
        f"4. Search for the S3 key above to locate the relevant invocation.\n"
        f"5. Review the error traceback and determine root cause.\n\n"
        f"ESCALATION GUIDANCE\n"
        f"{'─' * 30}\n"
        f"- If the error is transient (timeout, throttle), retry by re-uploading "
        f"the document to the S3 bucket.\n"
        f"- If the error is a Bedrock parse failure, review the raw Bedrock "
        f"response in CloudWatch and consider adjusting the prompt or document.\n"
        f"- If the document is corrupt or unreadable, contact the claimant to "
        f"request a clean resubmission.\n"
        f"- Escalate persistent failures to the platform engineering team.\n\n"
        f"This notification was generated automatically by the DLQ processor.\n"
        f"No further automated retries will occur for this document."
    )
    logger.info("Publishing SNS-Internal alert for failed document: %s", object_key)
    sns.publish(
        TopicArn=SNS_INTERNAL_ARN,
        Subject=subject,
        Message=message,
    )
    logger.info("SNS-Internal alert published successfully")


def publish_claimant_alert(object_key: str):
    """Fire an SNS-Claimant resubmission request."""
    subject = "Important: Your Insurance Claim Could Not Be Processed"
    message = (
        f"Dear Claimant,\n\n"
        f"Thank you for submitting your insurance claim to us.\n\n"
        f"Unfortunately, we encountered a technical issue while processing your "
        f"document and were unable to complete the review. We apologise for any "
        f"inconvenience this may cause.\n\n"
        f"WHAT YOU NEED TO DO\n"
        f"{'─' * 30}\n"
        f"Please resubmit your claim documentation using one of the accepted formats "
        f"below. Our team will process your resubmission as a priority.\n\n"
        f"ACCEPTED FILE FORMATS\n"
        f"{'─' * 30}\n"
        f"  • PDF  — preferred format, text-based or scanned\n"
        f"  • PNG / JPEG — high-resolution scans (300 DPI or above)\n"
        f"  Maximum file size: 10 MB per document\n\n"
        f"TIPS FOR A SUCCESSFUL SUBMISSION\n"
        f"{'─' * 30}\n"
        f"  • Ensure all pages are included and clearly legible.\n"
        f"  • Do not use password-protected or encrypted files.\n"
        f"  • Fully handwritten documents may not be processed automatically;\n"
        f"    typed or printed documents are preferred.\n\n"
        f"CONTACT US\n"
        f"{'─' * 30}\n"
        f"If you continue to experience issues or have questions about your claim,\n"
        f"please contact our claims team:\n\n"
        f"  Email:  claims-team@example.com\n"
        f"  Phone:  +1 (800) 000-0000\n"
        f"  Hours:  Monday to Friday, 09:00 – 17:00\n\n"
        f"Please quote your document reference when contacting us: {object_key}\n\n"
        f"Kind regards,\n"
        f"Insurance Claims Team"
    )
    logger.info("Publishing SNS-Claimant resubmission request for document: %s", object_key)
    sns.publish(
        TopicArn=SNS_CLAIMANT_ARN,
        Subject=subject,
        Message=message,
    )
    logger.info("SNS-Claimant alert published successfully")


# ─────────────────────────────────────────────
# Lambda Handler
# ─────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Entry point triggered by SQS event source mapping on the DLQ.
    Batch size is 1 (enforced in Terraform) — each invocation processes
    exactly one failed document, guaranteeing exactly one pair of
    notifications per failure with no risk of duplicates.
    """
    logger.info("DLQ processor invoked — %d record(s)", len(event["Records"]))

    # Batch size is 1; defensive loop handles unexpected multi-record batches
    # without silently dropping records.
    for record in event["Records"]:
        logger.info("Processing DLQ record: messageId=%s", record.get("messageId"))

        object_key = extract_object_key(record)
        logger.info("Failed document identified: %s", object_key)

        # Fire both notifications. Order: internal first so the claims team
        # is alerted before the claimant is contacted.
        publish_internal_alert(object_key)
        publish_claimant_alert(object_key)

        logger.info(
            "DLQ processing complete for document %s — "
            "internal and claimant notifications sent",
            object_key,
        )

    return {"statusCode": 200, "processed": len(event["Records"])}
