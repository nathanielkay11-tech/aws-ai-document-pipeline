"""
DLQ Processor Lambda
Triggered by SQS Dead Letter Queue when a claim document
fails to process after all Lambda retry attempts.
Fires a single dual SNS notification — one to the internal
claims team and one to the claimant.

KNOWN LIMITATIONS (Phase 2 items):
- Claimant contact details not available at this stage —
  document must be retrieved from S3 and reviewed manually.
- Full claimant data extraction deferred to Phase 2 via
  a pre-processing metadata store.
"""

import json
import os
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sns_client = boto3.client('sns')

SNS_INTERNAL_ARN = os.environ['SNS_INTERNAL_ARN']
SNS_CLAIMANT_ARN = os.environ['SNS_CLAIMANT_ARN']
S3_BUCKET_NAME = os.environ['S3_BUCKET_NAME']

def lambda_handler(event, context):
    """
    Triggered by SQS DLQ. Processes each failed record
    and fires a single dual SNS notification.
    """
    for record in event['Records']:
        try:
            # Extract the original S3 event from the DLQ message
            body = json.loads(record['body'])

            # Extract the object key from the original S3 event
            try:
                object_key = body['Records'][0]['s3']['object']['key']
            except (KeyError, IndexError):
                object_key = 'unknown'

            logger.info(f"Processing DLQ message for failed document: {object_key}")

            # Fire internal SNS alert
            sns_client.publish(
                TopicArn=SNS_INTERNAL_ARN,
                Subject=f"[PIPELINE ERROR] Processing Failed — {object_key}",
                Message=f"""
PIPELINE ERROR — MANUAL INTERVENTION REQUIRED
{'=' * 60}

A claim document failed to process after all retry attempts
and has been captured in the Dead Letter Queue.

DOCUMENT DETAILS
Document Reference:  {object_key}
Status:              Failed after all retry attempts
S3 Location:         s3://{S3_BUCKET_NAME}/{object_key}

ACTION REQUIRED
1. Retrieve the original document from S3 using the
   location above to obtain claimant contact details
2. Contact the claimant directly to request resubmission
3. Investigate CloudWatch logs for the
   claims-pipeline-processor Lambda function for full
   error details
4. Reprocess manually if document quality is confirmed
   acceptable

ESCALATION
If the issue cannot be resolved within 1 business day
please escalate to the claims operations manager.

{'=' * 60}
This is an automated notification from the Northgate
Insurance AI Claims Processing Pipeline.
Do not reply to this email.
                """
            )

            # Fire claimant SNS alert
            sns_client.publish(
                TopicArn=SNS_CLAIMANT_ARN,
                Subject=f"Claim Submission Issue — Action Required",
                Message=f"""
CLAIM SUBMISSION ISSUE
{'=' * 60}

Dear Claimant,

We were unable to process your recent claim document
submission after multiple attempts. This may be due to
document quality or format.

Reference: {object_key}

{'=' * 60}
ACTION REQUIRED
Please resubmit a clearer copy of your document.

Accepted formats: PDF (typed or scanned)
Maximum file size: 10MB

If the issue persists please contact our claims team
directly:

Email: claims@northgateinsurance.com
Tel:   1-800-555-0192

{'=' * 60}
This is an automated notification from the Northgate
Insurance Claims Processing System.
Do not reply to this email.
                """
            )

            logger.info(
                f"DLQ processor successfully sent dual SNS "
                f"notifications for {object_key}"
            )

        except Exception as e:
            logger.error(f"DLQ processor failed for record: {str(e)}")
            raise