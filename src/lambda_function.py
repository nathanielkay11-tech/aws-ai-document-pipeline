# =============================================================
# CHANGELOG
# v1.6 - 09 April 2026
# CHANGE: Improved SNS email formatting and subject lines
# REASON: Plain text output was unprofessional for a claims
# manager receiving actionable alerts. Updated to include:
# - Priority-based subject lines e.g. [CRITICAL PRIORITY]
# - Structured email body with clear sections
# - Exact SLA deadline date calculated from processed timestamp
# - Phase 2 note for automated SLA reminders via EventBridge
# =============================================================

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'package'))

import json
import uuid
import io
import boto3
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from pypdf import PdfReader

# --- AWS Clients ---
s3_client = boto3.client('s3')
textract_client = boto3.client('textract')
bedrock_client = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')

# --- Environment Variables ---
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
SNS_INTERNAL_ARN = os.environ['SNS_INTERNAL_ARN']
SNS_CLAIMANT_ARN = os.environ['SNS_CLAIMANT_ARN']
BEDROCK_MODEL_ID = os.environ['BEDROCK_MODEL_ID']
RISK_THRESHOLD = float(os.environ['RISK_THRESHOLD'])

def lambda_handler(event, context):
    """Main entry point for the claims processing pipeline."""
    
    try:
        # --- STAGE 1: Read from S3 ---
        bucket_name = event['Records'][0]['s3']['bucket']['name']
        object_key = event['Records'][0]['s3']['object']['key']
        
        print(f"Processing file: {object_key} from bucket: {bucket_name}")
        
        # Download PDF from S3 into memory
        s3_response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        pdf_bytes = s3_response['Body'].read()
        
        # --- STAGE 2: Detect PDF type and extract text ---
        raw_text = extract_text(pdf_bytes, bucket_name, object_key)
        
        print(f"Extracted {len(raw_text)} characters from document")
        
        # --- STAGE 3: AI Inference via Bedrock ---
        claim_result = invoke_bedrock(raw_text)
        
        # --- STAGE 4: Validate JSON schema ---
        validated_result = validate_schema(claim_result)
        
        # Add processing metadata
        claim_id = str(uuid.uuid4())
        processed_timestamp = datetime.now(timezone.utc)
        validated_result['claim_id'] = claim_id
        validated_result['source_document'] = object_key
        validated_result['processed_timestamp'] = processed_timestamp.isoformat()
        
        # Calculate SLA deadline based on recommended action
        sla_days = {
            'human_review': 10,
            'pending_documentation': 5,
            'auto_process': 1,
            'processing_error': 0
        }
        days = sla_days.get(validated_result.get('recommended_action'), 10)
        sla_deadline = processed_timestamp + timedelta(days=days)
        validated_result['sla_deadline'] = sla_deadline.strftime('%d %B %Y')

        # Convert floats to Decimal for DynamoDB compatibility
        validated_result = convert_floats_to_decimal(validated_result)
        
        # --- STAGE 5: Write to DynamoDB ---
        table = dynamodb.Table(DYNAMODB_TABLE)
        table.put_item(Item=validated_result)
        
        print(f"Claim {claim_id} written to DynamoDB")
        
        # --- STAGE 6: Route via SNS based on routing matrix ---
        route_claim(validated_result)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Claim processed successfully',
                'claim_id': claim_id,
                'recommended_action': validated_result.get('recommended_action')
            })
        }
        
    except Exception as e:
        print(f"Pipeline error: {str(e)}")
        handle_processing_error(object_key if 'object_key' in locals() else 'unknown')
        raise


def convert_floats_to_decimal(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(i) for i in obj]
    return obj


def extract_text(pdf_bytes, bucket_name, object_key):
    """
    Detect PDF type and extract text accordingly.
    Text-based PDFs use pypdf directly.
    Image-based PDFs use Textract OCR.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    extracted_text = ''
    
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            extracted_text += page_text + ' '
    
    extracted_text = extracted_text.strip()
    
    if extracted_text and len(extracted_text) > 50:
        print(f"Text-based PDF detected - extracted via pypdf, bypassing Textract")
        return extracted_text
    else:
        print(f"Image-based PDF detected - routing to Textract OCR")
        return extract_text_via_textract(bucket_name, object_key)


def extract_text_via_textract(bucket_name, object_key):
    """Extract text from image-based PDFs using Textract."""
    textract_response = textract_client.analyze_document(
        Document={
            'S3Object': {
                'Bucket': bucket_name,
                'Name': object_key
            }
        },
        FeatureTypes=['TABLES', 'FORMS']
    )
    
    raw_text = ' '.join([
        block['Text']
        for block in textract_response['Blocks']
        if block['BlockType'] == 'LINE' and 'Text' in block
    ])
    
    print(f"Textract extracted {len(raw_text)} characters")
    return raw_text


def invoke_bedrock(raw_text, attempt=1):
    """Call Bedrock with retry logic on JSON validation failure."""
    
    system_prompt = """Role: You are a senior insurance claims specialist with expertise in 
    fraud detection, risk assessment, and claims compliance.
    
    Context: The following is raw text extracted via OCR from an insurance claims document.
    
    Task: Extract and analyze the claim data and return ONLY valid JSON matching this schema:
    {
        "claimant_name": "string",
        "date_of_birth": "string", 
        "policy_number": "string",
        "contact_details": "string",
        "incident_date": "string",
        "claim_filed_date": "string",
        "claim_type": "string",
        "incident_description": "string",
        "total_amount_claimed": number,
        "cost_breakdown": ["string"],
        "supporting_documentation_present": boolean,
        "prior_claims_detected": boolean,
        "risk_flag": boolean,
        "confidence": "high | medium | low",
        "priority": "critical | high | medium | low",
        "recommended_action": "auto_process | human_review | pending_documentation | processing_error",
        "audit_flag": boolean,
        "audit_note": "string",
        "sla_deadline": "string"
    }
    
    Constraint: Return ONLY valid JSON. No explanation, no preamble, no markdown code fences. Use null for missing fields."""
    
    response = bedrock_client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType='application/json',
        accept='application/json',
        body=json.dumps({
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 2000,
            'system': system_prompt,
            'messages': [
                {
                    'role': 'user',
                    'content': f"Process this insurance claim document:\n\n{raw_text}"
                }
            ]
        })
    )
    
    response_body = json.loads(response['body'].read())
    result_text = response_body['content'][0]['text']
    
    # Strip markdown code fences if present
    clean_text = result_text.strip()
    if clean_text.startswith('```'):
        clean_text = clean_text.split('```')[1]
        if clean_text.startswith('json'):
            clean_text = clean_text[4:]
    clean_text = clean_text.strip()
    
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        if attempt < 2:
            print(f"JSON parse failed on attempt {attempt}, retrying...")
            return invoke_bedrock(raw_text, attempt=2)
        else:
            print(f"JSON parse failed after 2 attempts")
            print(f"Raw response: {result_text[:500]}")
            raise ValueError("Bedrock returned invalid JSON after 2 attempts")


def validate_schema(result):
    """Validate that required fields are present in Bedrock response."""
    required_fields = [
        'claimant_name', 'policy_number', 'incident_date',
        'total_amount_claimed', 'risk_flag', 'confidence',
        'priority', 'recommended_action', 'audit_note'
    ]
    
    missing_fields = [f for f in required_fields if f not in result]
    
    if missing_fields:
        print(f"Missing required fields: {missing_fields}")
        result['recommended_action'] = 'human_review'
        result['audit_note'] = f"Schema validation failed - missing fields: {missing_fields}"
        result['confidence'] = 'low'
        result['priority'] = 'high'
    
    return result


def format_amount(amount):
    """Format amount as currency string."""
    try:
        return f"${float(amount):,.2f}"
    except:
        return str(amount)


def get_subject_line(priority, claim_id):
    """Generate priority-based subject line."""
    prefix = {
        'critical': '[CRITICAL PRIORITY] Immediate Action Required',
        'high':     '[HIGH PRIORITY] Claim Review Required',
        'medium':   '[MEDIUM PRIORITY] Claim Review Required',
        'low':      '[LOW PRIORITY] Claim Review Required'
    }
    label = prefix.get(priority.lower(), '[REVIEW REQUIRED] Claim Alert')
    return f"{label} - {claim_id}"


def route_claim(result):
    """Route claim to appropriate SNS topic based on routing matrix."""
    
    recommended_action = result.get('recommended_action')
    priority = result.get('priority', 'high')
    confidence = result.get('confidence', 'medium')
    claim_id = result.get('claim_id')
    sla_deadline = result.get('sla_deadline', 'N/A')
    amount = format_amount(result.get('total_amount_claimed'))

    if recommended_action == 'human_review':
        subject = get_subject_line(priority, claim_id)
        message = f"""
CLAIMS REVIEW REQUIRED
{'=' * 60}

CLAIM DETAILS
Claim Reference:  {claim_id}
Claimant:         {result.get('claimant_name', 'N/A')}
Policy Number:    {result.get('policy_number', 'N/A')}
Claim Type:       {result.get('claim_type', 'N/A')}
Date of Incident: {result.get('incident_date', 'N/A')}
Date Filed:       {result.get('claim_filed_date', 'N/A')}
Amount Claimed:   {amount}

{'=' * 60}
ASSESSMENT
Confidence:       {confidence.upper()}
Priority:         {priority.upper()}
Recommendation:   Human Review Required

{'=' * 60}
REASON FOR REVIEW
{result.get('audit_note', 'N/A')}

{'=' * 60}
SLA INFORMATION
Review Deadline:  {sla_deadline}
Time Allowed:     10 business days from receipt

Note: An automated reminder will be sent 5 business days
before the SLA deadline if this claim remains unresolved.
(Phase 2 — EventBridge Scheduler)

{'=' * 60}
This is an automated notification from the Northgate
Insurance AI Claims Processing Pipeline.
Do not reply to this email.
        """
        sns_client.publish(
            TopicArn=SNS_INTERNAL_ARN,
            Subject=subject,
            Message=message
        )
        print(f"Internal SNS alert sent for claim {claim_id}")

    elif recommended_action == 'pending_documentation':
        message = f"""
ADDITIONAL DOCUMENTATION REQUIRED
{'=' * 60}

Dear {result.get('claimant_name', 'Claimant')},

Your insurance claim submission has been received and reviewed.
Additional documentation is required before your claim can
be processed.

CLAIM DETAILS
Claim Reference:  {claim_id}
Amount Claimed:   {amount}
Date Filed:       {result.get('claim_filed_date', 'N/A')}

{'=' * 60}
ACTION REQUIRED
{result.get('audit_note', 'N/A')}

{'=' * 60}
IMPORTANT — RESPONSE DEADLINE
Please resubmit your claim with the required documentation
within 5 business days of this notification.

Response Deadline: {sla_deadline}

Failure to respond by this date may result in your claim
being suspended pending further review.

{'=' * 60}
This is an automated notification from the Northgate
Insurance Claims Processing System.
For assistance please contact claims@northgateinsurance.com
        """
        sns_client.publish(
            TopicArn=SNS_CLAIMANT_ARN,
            Subject=f"Action Required — Claim {claim_id}",
            Message=message
        )
        print(f"Claimant SNS notification sent for claim {claim_id}")

    elif recommended_action == 'auto_process':
        print(f"Claim {claim_id} auto-processed — no SNS required")

    elif recommended_action == 'processing_error':
        handle_processing_error(claim_id)


def handle_processing_error(reference):
    """Handle pipeline failures with dual SNS notification."""
    sns_client.publish(
        TopicArn=SNS_INTERNAL_ARN,
        Subject=f"[PIPELINE ERROR] Processing Failed - {reference}",
        Message=f"""
PIPELINE ERROR — MANUAL INTERVENTION REQUIRED
{'=' * 60}

The claims pipeline failed to process the following document:

Reference: {reference}

Please investigate the CloudWatch logs for this Lambda
function and reprocess the document manually if required.

{'=' * 60}
This is an automated error notification from the Northgate
Insurance AI Claims Processing Pipeline.
        """
    )
    
    sns_client.publish(
        TopicArn=SNS_CLAIMANT_ARN,
        Subject=f"Claim Submission Issue — Action Required",
        Message=f"""
CLAIM SUBMISSION ISSUE
{'=' * 60}

Dear Claimant,

We were unable to process your recent claim document
submission. This may be due to document quality or format.

Reference: {reference}

{'=' * 60}
ACTION REQUIRED
Please resubmit a clearer copy of your document.

Accepted formats: PDF (typed or scanned)
Maximum file size: 10MB

If the issue persists please contact our claims team:
claims@northgateinsurance.com
Tel: 1-800-555-0192

{'=' * 60}
This is an automated notification from the Northgate
Insurance Claims Processing System.
        """
    )
    
    print(f"Processing error SNS alerts sent for {reference}")