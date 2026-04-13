# Iteration 3: One-Shot Reproduction Prompt

## Purpose
This prompt was engineered after a full build and test cycle to reproduce 
the complete Terraform infrastructure and Lambda functions for the AWS AI 
Document Intelligence Pipeline in a single AI-assisted pass. Every constraint 
reflects a real problem encountered and solved during development — from the 
pypdf sys.path insert to the inference profile ARN to the markdown fence 
stripping. Without the build experience, this prompt could not have been written.

## Prerequisites
Before running this prompt output, ensure the following are in place:
- AWS account with Terraform IAM user configured
- Terraform IAM user requires custom least-privilege policies for: 
  S3, DynamoDB, Lambda, SNS, Textract, IAM, SQS and Bedrock
- Amazon Bedrock model access enabled for Claude Sonnet 4.5 
  (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) in us-east-1
- AWS CLI configured with Terraform user credentials
- Terraform installed (>= 1.0)
- Python 3 and pip installed locally for Lambda packaging
- pypdf packaged into src/package/ before terraform apply
  (use the generated build_lambda.sh script)
- S3 bucket name must be globally unique — add a personal suffix to the 
  default bucket name e.g. `insurance-claims-uploads-nk`

## The Prompt

Act as a Senior AWS Solutions Architect and DevOps Engineer. 
Generate the complete Terraform configuration files and complete 
Lambda Python functions for a serverless AI insurance claims 
processing pipeline. Provide the output as separate clearly 
labelled code blocks for each file. Follow these strict constraints:

**Services:**
The pipeline must use the following AWS services in sequence:
- Amazon S3 — private upload bucket, event notification trigger on .pdf suffix only
- AWS Lambda — Python 3.12, orchestrates all service interactions
- Amazon Textract — OCR for image-based PDFs only
- Amazon Bedrock — Claude Sonnet 4.5 via inference profile for AI analysis
- Amazon DynamoDB — on-demand billing, stores structured JSON claim results
- Amazon SNS — two separate topics: SNS-Internal for claims team, SNS-Claimant for claimant notifications
- Amazon SQS — Dead Letter Queue to capture failed Lambda events after all retry attempts are exhausted
- pypdf — direct text extraction for text-based PDFs, bypassing Textract
- DLQ Processor Lambda — dedicated Lambda function triggered by SQS DLQ, fires single dual SNS notification after all retries exhausted

**Terraform Structure:**
Produce separate files for each resource — do not combine into a single main.tf:
- main.tf — AWS provider and Terraform version configuration only
- variables.tf — all configurable values including region, model ID, bucket name, table name, SNS topic names, risk threshold, environment tag, Lambda function name, Lambda timeout defaulting to 300 seconds, Lambda memory defaulting to 512 MB, DLQ processor function name, DLQ processor timeout defaulting to 30 seconds, DLQ processor memory defaulting to 128 MB
- s3.tf — private bucket, public access block, AES256 encryption, PDF event notification trigger
- dynamodb.tf — on-demand billing, claim_id as String partition key, server-side encryption
- iam.tf — two separate IAM roles and least-privilege policies: (1) claims processor Lambda role with s3:GetObject, textract:DetectDocumentText, textract:AnalyzeDocument, bedrock:InvokeModel using wildcard region format `arn:aws:bedrock:*::foundation-model/*` and `arn:aws:bedrock:*:*:inference-profile/*` — this is required because the us. cross-region inference profile routes through multiple AWS regions, dynamodb:PutItem, sns:Publish for both SNS topic ARNs, sqs:SendMessage for DLQ ARN, logs permissions. (2) DLQ processor Lambda role with sns:Publish for both SNS topic ARNs, sqs:ReceiveMessage, sqs:DeleteMessage, sqs:GetQueueAttributes for DLQ ARN, logs permissions. No AWS managed policies. No wildcards on actions except Bedrock resource ARNs.
- lambda.tf — claims processor Lambda with filename referencing `${path.module}/../src/lambda_function.zip`, DLQ processor Lambda with filename referencing `${path.module}/../src/dlq_processor.zip`, dead_letter_config pointing to SQS DLQ, DLQ processor Lambda triggered by SQS event source mapping with batch size 1, SQS Dead Letter Queue with 60 second visibility timeout and 14 day message retention, S3 invoke permission with depends_on Lambda function, SQS event source mapping
- sns.tf — two topics with tags, two email subscriptions with placeholder endpoints
- outputs.tf — s3 bucket name, dynamodb table name, lambda function name, both SNS ARNs, bedrock model ID, DLQ URL, DLQ processor function name

**Lambda Function Requirements:**

Produce two separate Lambda functions:

**1. lambda_function.py — Claims Pipeline Processor:**

1. Dual PDF processing:
   - Download PDF from S3 into memory
   - Attempt pypdf text extraction first
   - If extracted text exceeds 50 characters — text-based PDF confirmed, bypass Textract
   - If extracted text below 50 characters — image-based PDF, route to Textract analyze_document with TABLES and FORMS feature types

2. Bedrock inference:
   - Model: us.anthropic.claude-sonnet-4-5-20250929-v1:0
   - Bedrock client must explicitly set region_name to us-east-1
   - Strip markdown code fences from response before JSON parsing
   - Retry once on JSON parse failure
   - Raise ValueError after 2 failed attempts

3. JSON schema validation:
   - Validate all required fields present before DynamoDB write
   - Override to human_review if fields missing

4. Float to Decimal conversion:
   - Recursively convert all float values to Decimal before DynamoDB write

5. Routing matrix:
   - human_review → SNS-Internal with priority-based subject line and structured email body
   - pending_documentation → SNS-Claimant with action required and 5 business day deadline
   - auto_process → DynamoDB write only, no SNS
   - processing_error → log error and raise exception only — do NOT fire SNS, DLQ processor handles all error notifications

6. SLA deadline calculation:
   - human_review: 10 business days
   - pending_documentation: 5 business days
   - auto_process: 1 day
   - Stored as formatted date string in DynamoDB

7. Subject line format:
   - [CRITICAL PRIORITY] Immediate Action Required - {claim_id}
   - [HIGH PRIORITY] Claim Review Required - {claim_id}
   - [MEDIUM PRIORITY] Claim Review Required - {claim_id}
   - [LOW PRIORITY] Claim Review Required - {claim_id}

8. CloudWatch logging at every stage for observability

9. Environment variables: DYNAMODB_TABLE, SNS_INTERNAL_ARN, SNS_CLAIMANT_ARN, BEDROCK_MODEL_ID, RISK_THRESHOLD

**2. dlq_processor.py — Dead Letter Queue Processor:**

1. Triggered by SQS event source mapping on the Dead Letter Queue
2. Extract original S3 object key from failed event body
3. Fire SNS-Internal alert with:
   - Subject: [PIPELINE ERROR] Processing Failed — {object_key}
   - S3 document location for manual retrieval
   - Instructions for CloudWatch log investigation
   - Escalation guidance
4. Fire SNS-Claimant alert with:
   - Professional resubmission request
   - Accepted formats and file size limits
   - Claims team contact details
5. Exactly one notification per failed document — no duplicates
6. Environment variables: SNS_INTERNAL_ARN, SNS_CLAIMANT_ARN, S3_BUCKET_NAME

**Security Constraints:**
- No hardcoded credentials anywhere
- No hardcoded ARNs — all referenced via Terraform resource attributes
- All sensitive values in variables.tf
- .gitignore must cover .tfstate, .tfstate.backup, .terraform/, *.tfvars, crash.log
- Both Lambda execution roles must use custom least-privilege policies only

**Bedrock Prompt:**
The system prompt passed to Bedrock must instruct the model to:
- Act as a senior insurance claims specialist
- Extract: claimant_name, date_of_birth, policy_number, contact_details, incident_date, claim_filed_date, claim_type, incident_description, total_amount_claimed, cost_breakdown, supporting_documentation_present, prior_claims_detected
- Apply risk flagging logic: amount >= $50,000, prior claims detected, filing delay > 90 days, document inconsistencies, signs of alteration
- Return confidence: high/medium/low
- Return priority: critical/high/medium/low
- Return recommended_action: auto_process/human_review/pending_documentation/processing_error
- pending_documentation takes priority over human_review when the only issue is missing documentation and no risk flag is triggered
- Return audit_flag boolean
- Return audit_note with plain English reasoning
- Return ONLY valid JSON — no markdown, no preamble, no code fences
- Use null for missing fields

**Known Limitations to acknowledge in code comments:**
- Claimant authentication out of scope — assumes secure upload mechanism exists
- Fully handwritten documents not supported
- Prior claims detection relies on document content only — no database lookup
- SLA reminder notifications and auto-process audit reporting deferred to Phase 2
- DLQ processor Lambda requires separate zip package — dlq_processor.zip built from src/dlq_processor.py

## How to Validate the Output
As the architect reviewing the junior engineer's output, verify:
1. Every Terraform file is separate — no combined main.tf
2. Two separate IAM roles — one for claims processor, one for DLQ processor
3. Claims processor IAM includes sqs:SendMessage for DLQ
4. DLQ processor IAM includes sqs:ReceiveMessage, sqs:DeleteMessage, sqs:GetQueueAttributes
5. Lambda handler is named lambda_function.lambda_handler
6. DLQ processor handler is named dlq_processor.lambda_handler
7. pypdf is imported from package/ subdirectory via sys.path insert
8. Both SNS topics are referenced correctly in routing logic
9. SLA deadlines are calculated dynamically not hardcoded
10. All environment variables match what is defined in lambda.tf
11. processing_error routing logs and raises only — no SNS in main Lambda
12. DLQ processor fires exactly two SNS notifications — one internal, one claimant
13. SQS visibility timeout is 60 seconds — matching Lambda timeout
14. .gitignore is present in terraform/ folder
15. Bedrock client explicitly sets region_name to us-east-1
16. Bedrock IAM resource uses wildcard region — not hardcoded us-east-1
17. Lambda zip paths reference `${path.module}/../src/` not `${path.module}/src/`
18. Lambda timeout defaults to 300 seconds in variables.tf
19. S3 bucket name uses a unique suffix — not a generic name

## Architect Review Findings (13 April 2026)

**Verdict: ✅ Prompt successful — full redeployment validated**

**What the AI produced correctly:**
- All 9 Terraform files correctly separated
- Two separate IAM roles — claims processor and DLQ processor
- Dual PDF processing with pypdf/Textract routing
- SLA deadline calculation skipping weekends
- Regex-based markdown fence stripping
- Float to Decimal conversion with InvalidOperation handling
- Known limitations documented in code comments
- build_lambda.sh script automating both Lambda zip builds
- DLQ processor Lambda with correct SQS event source mapping
- Batch size 1 enforced on DLQ trigger

**Corrections required before deployment:**

1. **Zip file paths** — generated files referenced `${path.module}/src/` but 
   correct path is `${path.module}/../src/` due to project folder structure
   where src/ sits one level above terraform/

2. **Lambda timeout** — generated default was 60 seconds, correct value is 
   300 seconds to match SQS visibility timeout requirement and Bedrock 
   inference latency

3. **Bedrock IAM ARN** — generated ARN used specific region `us-east-1` but 
   cross-region inference profile `us.anthropic.claude-sonnet-4-5` routes 
   through multiple AWS regions. Correct resource ARN uses wildcard region:
   `arn:aws:bedrock:*::foundation-model/*` and 
   `arn:aws:bedrock:*:*:inference-profile/*`

4. **S3 bucket name uniqueness** — default bucket name `insurance-claims-uploads` 
   was already taken globally. Must use a unique suffix e.g. 
   `insurance-claims-uploads-nk`

**Redeployment test result (13 April 2026):**
All four routing outcomes validated on reproduced pipeline:
- ✅ human_review HIGH priority — text-based PDF via pypdf
- ✅ pending_documentation — image-based PDF via Textract
- ✅ auto_process — image-based PDF via Textract, no SNS
- ✅ processing_error — dual notification via DLQ processor

**Conclusion:**
Four corrections required — all documented above and reflected in the 
prompt constraints above. The prompt successfully reproduces a working 
production-grade pipeline with architect review.