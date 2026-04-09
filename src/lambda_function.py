# =============================================================
# CHANGELOG
# v1.2 - 09 April 2026
# CHANGE: Implemented dual PDF processing strategy (ADR-008)
# REASON: Textract only supports image-based PDFs. Text-based
# PDFs generated digitally can be extracted directly using
# pypdf without calling Textract, reducing cost and latency.
# LOGIC: Lambda detects PDF type on ingestion:
#   - Text-based PDF -> pypdf direct extraction (no Textract)
#   - Image-based PDF -> Textract OCR as before
# =============================================================

import json
import os
import uuid
import io
import boto3
from datetime import datetime, timezone
from package.pypdf import PdfReader

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
        validated_result['claim_id'] = claim_id
        validated_result['source_document'] = object_key
        validated_result['processed_timestamp'] = datetime.now(timezone.utc).isoformat()
        
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


def extract_text(pdf_bytes, bucket_name, object_key):
    """
    Detect PDF type and extract text accordingly.
    Text-based PDFs use pypdf directly.
    Image-based PDFs use Textract OCR.
    """
    
    # Attempt direct text extraction with pypdf
    reader = PdfReader(io.BytesIO(pdf_bytes))
    extracted_text = ''
    
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            extracted_text += page_text + ' '
    
    extracted_text = extracted_text.strip()
    
    if extracted_text and len(extracted_text) > 50:
        # Text-based PDF - pypdf extracted sufficient content
        print(f"Text-based PDF detected - extracted via pypdf, bypassing Textract")
        return extracted_text
    else:
        # Image-based or scanned PDF - route to Textract
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
    
    Constraint: Return ONLY valid JSON. No explanation or preamble. Use null for missing fields."""
    
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
    
    try:
        return json.loads(result_text)
    except json.JSONDecodeError:
        if attempt < 2:
            print(f"JSON parse failed on attempt {attempt}, retrying...")
            return invoke_bedrock(raw_text, attempt=2)
        else:
            print("JSON parse failed after 2 attempts")
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


def route_claim(result):
    """Route claim to appropriate SNS topic based on routing matrix."""
    
    recommended_action = result.get('recommended_action')
    priority = result.get('priority')
    confidence = result.get('confidence')
    claim_id = result.get('claim_id')
    
    if recommended_action == 'human_review':
        message = f"""
        CLAIMS REVIEW REQUIRED
        Claim ID: {claim_id}
        Priority: {priority}
        Confidence: {confidence}
        Action Required: {result.get('audit_note')}
        Claimant: {result.get('claimant_name')}
        Amount: {result.get('total_amount_claimed')}
        """
        sns_client.publish(
            TopicArn=SNS_INTERNAL_ARN,
            Subject=f"[{priority.upper()}] Claim Review Required - {claim_id}",
            Message=message
        )
        print(f"Internal SNS alert sent for claim {claim_id}")
        
    elif recommended_action == 'pending_documentation':
        message = f"""
        Dear {result.get('claimant_name', 'Claimant')},
        
        Your insurance claim requires additional documentation to proceed.
        
        Claim Reference: {claim_id}
        Action Required: {result.get('audit_note')}
        
        Please resubmit your claim with the required documentation 
        within 5 business days.
        """
        sns_client.publish(
            TopicArn=SNS_CLAIMANT_ARN,
            Subject=f"Action Required - Claim {claim_id}",
            Message=message
        )
        print(f"Claimant SNS notification sent for claim {claim_id}")
        
    elif recommended_action == 'auto_process':
        print(f"Claim {claim_id} auto-processed - no SNS required")
        
    elif recommended_action == 'processing_error':
        handle_processing_error(claim_id)


def handle_processing_error(reference):
    """Handle pipeline failures with dual SNS notification."""
    
    sns_client.publish(
        TopicArn=SNS_INTERNAL_ARN,
        Subject=f"PIPELINE ERROR - {reference}",
        Message=f"Claims pipeline failed to process document: {reference}. Manual intervention required."
    )
    
    sns_client.publish(
        TopicArn=SNS_CLAIMANT_ARN,
        Subject="Claim Submission Issue",
        Message=f"""
        We were unable to process your claim document.
        
        Reference: {reference}
        
        Please resubmit a clearer copy of your document.
        If the issue persists please contact our claims team directly.
        """
    )
    
    print(f"Processing error SNS alerts sent for {reference}")