"""
Insurance Claims Processor — Lambda Function
=============================================
Orchestrates the full claims triage pipeline:
  S3 → pypdf/Textract → Bedrock → DynamoDB / SNS routing

Known Limitations:
  - Claimant authentication is out of scope; assumes a secure upload
    mechanism exists upstream of the S3 trigger.
  - Fully handwritten documents are not supported; Textract's FORMS/TABLES
    features require at least partial printed or digital text.
  - Prior claims detection relies solely on document content; no external
    database lookup is performed.
  - SLA reminder notifications and auto-process audit reporting are deferred
    to Phase 2.
"""

import sys
import os
import re
import json
import uuid
import logging
import boto3

from io import BytesIO
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

# pypdf is packaged into src/package/ and injected into the Lambda layer.
# sys.path insert ensures the vendored library takes precedence over any
# Lambda runtime version.
sys.path.insert(0, "/var/task/package")
import pypdf  # noqa: E402  (must follow sys.path insert)

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─────────────────────────────────────────────
# Environment variables
# ─────────────────────────────────────────────
DYNAMODB_TABLE   = os.environ["DYNAMODB_TABLE"]
SNS_INTERNAL_ARN = os.environ["SNS_INTERNAL_ARN"]
SNS_CLAIMANT_ARN = os.environ["SNS_CLAIMANT_ARN"]
BEDROCK_MODEL_ID = os.environ["BEDROCK_MODEL_ID"]
RISK_THRESHOLD   = float(os.environ.get("RISK_THRESHOLD", "50000"))

# ─────────────────────────────────────────────
# AWS clients
# ─────────────────────────────────────────────
s3       = boto3.client("s3")
textract = boto3.client("textract")
bedrock  = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"))
dynamodb = boto3.resource("dynamodb")
sns      = boto3.client("sns")

table = dynamodb.Table(DYNAMODB_TABLE)

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
PYPDF_MIN_CHARS = 50  # Below this → treat as image-based PDF, route to Textract

REQUIRED_FIELDS = [
    "claimant_name", "policy_number", "incident_date", "claim_filed_date",
    "claim_type", "incident_description", "total_amount_claimed",
    "recommended_action", "confidence", "priority",
    "audit_flag", "audit_note",
]

SLA_BUSINESS_DAYS = {
    "human_review":          10,
    "pending_documentation":  5,
    "auto_process":           1,
}

SUBJECT_TEMPLATES = {
    "critical": "[CRITICAL PRIORITY] Immediate Action Required - {claim_id}",
    "high":     "[HIGH PRIORITY] Claim Review Required - {claim_id}",
    "medium":   "[MEDIUM PRIORITY] Claim Review Required - {claim_id}",
    "low":      "[LOW PRIORITY] Claim Review Required - {claim_id}",
}

BEDROCK_SYSTEM_PROMPT = """You are a senior insurance claims specialist with 20 years of experience
in claims triage and fraud detection. Analyse the provided insurance claim document and extract
structured information.

Extract the following fields:
- claimant_name
- date_of_birth
- policy_number
- contact_details (object with phone, email, address sub-fields where present)
- incident_date
- claim_filed_date
- claim_type
- incident_description
- total_amount_claimed (numeric value only, no currency symbol)
- cost_breakdown (object or list of line items if present)
- supporting_documentation_present (boolean)
- prior_claims_detected (boolean, based on document content only — no external lookup)

Apply risk flagging logic:
- total_amount_claimed >= 50000
- prior_claims_detected is true
- filing delay > 90 days between incident_date and claim_filed_date
- document inconsistencies detected
- signs of alteration or tampering

Return the following assessment fields:
- confidence: "high" | "medium" | "low"
- priority: "critical" | "high" | "medium" | "low"
- recommended_action: "auto_process" | "human_review" | "pending_documentation" | "processing_error"
  * pending_documentation takes priority over human_review when the ONLY issue is missing
    documentation and NO risk flag has been triggered.
- audit_flag: boolean
- audit_note: plain English explanation of your reasoning, including any risk flags triggered

Return ONLY valid JSON — no markdown, no preamble, no code fences.
Use null for any fields not found in the document."""


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def add_business_days(start_date: datetime, days: int) -> datetime:
    """Return a date that is `days` business days after start_date,
    skipping Saturdays and Sundays."""
    current = start_date
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday–Friday
            added += 1
    return current


def calculate_sla_deadline(action: str) -> str:
    """Return a formatted SLA deadline string for the given action."""
    business_days = SLA_BUSINESS_DAYS.get(action, 5)
    deadline = add_business_days(datetime.utcnow(), business_days)
    return deadline.strftime("%Y-%m-%d")


def floats_to_decimals(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        try:
            return Decimal(str(obj))
        except InvalidOperation:
            return Decimal("0")
    if isinstance(obj, dict):
        return {k: floats_to_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimals(i) for i in obj]
    return obj


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ``` or ``` ... ```) from a string."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.DOTALL)


# ─────────────────────────────────────────────
# PDF Extraction
# ─────────────────────────────────────────────

def extract_text_pypdf(pdf_bytes: bytes) -> str:
    """Attempt direct text extraction from a PDF using pypdf."""
    logger.info("Attempting pypdf text extraction")
    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    text_parts = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def extract_text_textract(pdf_bytes: bytes) -> str:
    """Extract text from an image-based PDF using Amazon Textract."""
    logger.info("Routing to Textract for image-based PDF")
    response = textract.analyze_document(
        Document={"Bytes": pdf_bytes},
        FeatureTypes=["TABLES", "FORMS"],
    )
    blocks = response.get("Blocks", [])
    lines = [b["Text"] for b in blocks if b["BlockType"] == "LINE" and "Text" in b]
    return "\n".join(lines)


def get_document_text(pdf_bytes: bytes) -> str:
    """
    Dual-path PDF text extraction:
      1. Try pypdf — fast, free, no API call.
      2. If extracted text is below PYPDF_MIN_CHARS, treat as image-based
         and route to Textract.
    """
    text = extract_text_pypdf(pdf_bytes)
    if len(text.strip()) >= PYPDF_MIN_CHARS:
        logger.info("pypdf extraction successful (%d chars)", len(text))
        return text

    logger.info(
        "pypdf yielded only %d chars — image-based PDF detected, routing to Textract",
        len(text),
    )
    return extract_text_textract(pdf_bytes)


# ─────────────────────────────────────────────
# Bedrock Inference
# ─────────────────────────────────────────────

def invoke_bedrock(document_text: str) -> dict:
    """
    Send document text to Bedrock Claude for structured claim analysis.
    Strips markdown fences and retries once on JSON parse failure.
    Raises ValueError after 2 failed attempts.
    """
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": BEDROCK_SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": f"Analyse the following insurance claim document:\n\n{document_text}",
            }
        ],
    }

    for attempt in range(1, 3):
        logger.info("Bedrock inference attempt %d", attempt)
        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload),
        )
        raw = json.loads(response["body"].read())
        response_text = raw["content"][0]["text"]
        logger.info("Bedrock raw response received (attempt %d)", attempt)

        cleaned = strip_markdown_fences(response_text)
        try:
            result = json.loads(cleaned)
            logger.info("Bedrock JSON parsed successfully on attempt %d", attempt)
            return result
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse failed on attempt %d: %s", attempt, exc)

    raise ValueError("Bedrock returned invalid JSON after 2 attempts")


# ─────────────────────────────────────────────
# Schema Validation
# ─────────────────────────────────────────────

def validate_schema(claim_data: dict) -> dict:
    """
    Verify all required fields are present.
    Overrides recommended_action to 'human_review' if any are missing,
    so missing-field records are never silently auto-processed.
    """
    missing = [f for f in REQUIRED_FIELDS if f not in claim_data or claim_data[f] is None]
    if missing:
        logger.warning("Schema validation failed — missing fields: %s", missing)
        claim_data["recommended_action"] = "human_review"
        claim_data["audit_note"] = (
            claim_data.get("audit_note", "")
            + f" [Schema override: missing fields {missing}]"
        )
    return claim_data


# ─────────────────────────────────────────────
# SNS Routing
# ─────────────────────────────────────────────

def build_internal_subject(claim_id: str, priority: str) -> str:
    template = SUBJECT_TEMPLATES.get(priority.lower(), SUBJECT_TEMPLATES["medium"])
    return template.format(claim_id=claim_id)


def publish_internal_notification(claim_id: str, claim_data: dict, sla_deadline: str):
    priority = claim_data.get("priority", "medium").lower()
    subject = build_internal_subject(claim_id, priority)
    message = (
        f"INSURANCE CLAIM — HUMAN REVIEW REQUIRED\n"
        f"{'=' * 50}\n\n"
        f"Claim ID:          {claim_id}\n"
        f"Claimant Name:     {claim_data.get('claimant_name', 'N/A')}\n"
        f"Policy Number:     {claim_data.get('policy_number', 'N/A')}\n"
        f"Claim Type:        {claim_data.get('claim_type', 'N/A')}\n"
        f"Amount Claimed:    ${claim_data.get('total_amount_claimed', 'N/A')}\n"
        f"Priority:          {priority.upper()}\n"
        f"Confidence:        {claim_data.get('confidence', 'N/A')}\n"
        f"Audit Flag:        {claim_data.get('audit_flag', False)}\n"
        f"SLA Deadline:      {sla_deadline}\n\n"
        f"Audit Note:\n{claim_data.get('audit_note', 'None')}\n\n"
        f"Please log in to the claims portal to review this submission."
    )
    logger.info("Publishing SNS-Internal notification for claim %s", claim_id)
    sns.publish(TopicArn=SNS_INTERNAL_ARN, Subject=subject, Message=message)


def publish_claimant_notification(claim_id: str, claim_data: dict, sla_deadline: str):
    subject = f"Action Required: Additional Documentation Needed — Claim {claim_id}"
    message = (
        f"Dear {claim_data.get('claimant_name', 'Claimant')},\n\n"
        f"Thank you for submitting your insurance claim (Reference: {claim_id}).\n\n"
        f"After reviewing your submission, our claims team has determined that "
        f"additional documentation is required to process your claim.\n\n"
        f"ACTION REQUIRED\n"
        f"{'─' * 30}\n"
        f"Please provide the outstanding documentation within 5 business days "
        f"(by {sla_deadline}) to avoid delays in processing your claim.\n\n"
        f"If you have any questions, please contact our claims team who will be "
        f"happy to assist you.\n\n"
        f"Kind regards,\nInsurance Claims Team"
    )
    logger.info("Publishing SNS-Claimant notification for claim %s", claim_id)
    sns.publish(TopicArn=SNS_CLAIMANT_ARN, Subject=subject, Message=message)


# ─────────────────────────────────────────────
# DynamoDB Write
# ─────────────────────────────────────────────

def write_to_dynamodb(claim_id: str, claim_data: dict, sla_deadline: str, object_key: str):
    item = floats_to_decimals({
        "claim_id":       claim_id,
        "s3_object_key":  object_key,
        "processed_at":   datetime.utcnow().isoformat(),
        "sla_deadline":   sla_deadline,
        **claim_data,
    })
    logger.info("Writing claim %s to DynamoDB table %s", claim_id, DYNAMODB_TABLE)
    table.put_item(Item=item)
    logger.info("DynamoDB write successful for claim %s", claim_id)


# ─────────────────────────────────────────────
# Lambda Handler
# ─────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Entry point triggered by S3 ObjectCreated event on .pdf suffix.
    Pipeline stages:
      1. Download PDF from S3
      2. Extract text (pypdf → Textract fallback)
      3. Invoke Bedrock for structured analysis
      4. Validate schema
      5. Route: human_review → SNS-Internal
                pending_documentation → SNS-Claimant
                auto_process → DynamoDB only
                processing_error → log + raise (DLQ handles notifications)
    """
    logger.info("Lambda invoked — event: %s", json.dumps(event))

    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key    = record["s3"]["object"]["key"]

    logger.info("Processing document: s3://%s/%s", bucket, key)

    # 1. Download PDF
    logger.info("Downloading PDF from S3")
    s3_response = s3.get_object(Bucket=bucket, Key=key)
    pdf_bytes = s3_response["Body"].read()
    logger.info("PDF downloaded — %d bytes", len(pdf_bytes))

    # 2. Extract text
    document_text = get_document_text(pdf_bytes)
    logger.info("Text extraction complete — %d characters", len(document_text))

    # 3. Bedrock inference
    logger.info("Invoking Bedrock model: %s", BEDROCK_MODEL_ID)
    claim_data = invoke_bedrock(document_text)

    # 4. Schema validation
    claim_data = validate_schema(claim_data)

    # 5. Routing
    claim_id         = str(uuid.uuid4())
    action           = claim_data.get("recommended_action", "processing_error")
    sla_deadline     = calculate_sla_deadline(action)

    logger.info("Claim %s — action=%s, priority=%s, sla=%s",
                claim_id, action, claim_data.get("priority"), sla_deadline)

    if action == "human_review":
        write_to_dynamodb(claim_id, claim_data, sla_deadline, key)
        publish_internal_notification(claim_id, claim_data, sla_deadline)

    elif action == "pending_documentation":
        write_to_dynamodb(claim_id, claim_data, sla_deadline, key)
        publish_claimant_notification(claim_id, claim_data, sla_deadline)

    elif action == "auto_process":
        write_to_dynamodb(claim_id, claim_data, sla_deadline, key)
        logger.info("Claim %s auto-processed — no SNS notification required", claim_id)

    elif action == "processing_error":
        # Do NOT publish SNS here — the DLQ processor handles all error
        # notifications after all Lambda retry attempts are exhausted.
        logger.error(
            "processing_error returned by Bedrock for claim %s — "
            "audit_note: %s",
            claim_id, claim_data.get("audit_note"),
        )
        raise RuntimeError(
            f"Bedrock flagged processing_error for document s3://{bucket}/{key}"
        )

    else:
        logger.error("Unexpected action '%s' for claim %s", action, claim_id)
        raise ValueError(f"Unknown recommended_action: {action}")

    logger.info("Pipeline complete for claim %s", claim_id)
    return {"statusCode": 200, "claim_id": claim_id, "action": action}
