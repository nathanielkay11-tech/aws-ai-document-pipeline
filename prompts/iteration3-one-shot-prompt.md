# Iteration 3: One-Shot Reproduction Prompt

## Purpose
This prompt was engineered after a full build and test cycle to reproduce 
the complete Terraform infrastructure and Lambda function for the AWS AI 
Document Intelligence Pipeline in a single AI-assisted pass. Every constraint 
reflects a real problem encountered and solved during development — from the 
pypdf sys.path insert to the inference profile ARN to the markdown fence 
stripping. Without the build experience, this prompt could not have been written.

## Prerequisites
Before running this prompt output, ensure the following are in place:
- AWS account with Terraform IAM user configured
- Terraform IAM user requires custom least-privilege policies for: 
  S3, DynamoDB, Lambda, SNS, Textract, IAM and Bedrock
- Amazon Bedrock model access enabled for Claude Sonnet 4.5 
  (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) in us-east-1
- AWS CLI configured with Terraform user credentials
- Terraform installed (>= 1.0)
- Python 3 and pip installed locally for Lambda packaging
- pypdf packaged into src/package/ before terraform apply
  (use the generated build_lambda.sh script)

## The Prompt

Act as a Senior AWS Solutions Architect and DevOps Engineer. 
Generate the complete Terraform configuration files and complete 
Lambda Python function for a serverless AI insurance claims 
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
- pypdf — direct text extraction for text-based PDFs, bypassing Textract
- Amazon SQS — Dead Letter Queue to capture failed Lambda events after all retry attempts are exhausted
- DLQ Processor Lambda — dedicated Lambda function triggered by SQS DLQ, fires single dual SNS notification after all retries exhausted

**Terraform Structure:**
Produce separate files for each resource — do not combine into a single main.tf:
- main.tf — AWS provider and Terraform version configuration only
- variables.tf — all configurable values including region, model ID, bucket name, table name, SNS topic names, risk threshold and environment tag
- s3.tf — private bucket, public access block, AES256 encryption, PDF event notification trigger
- dynamodb.tf — on-demand billing, claim_id as String partition key, server-side encryption
- iam.tf — Lambda execution role with exactly these permissions: s3:GetObject, textract:DetectDocumentText, textract:AnalyzeDocument, bedrock:InvokeModel for both foundation-model and inference-profile ARNs, dynamodb:PutItem, sns:Publish for both SNS topic ARNs, logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents. No AWS managed policies. No wildcards on actions.
- lambda.tf — function definition referencing ../src/lambda_function.zip, all environment variables passed from variables.tf, depends_on lambda permission to prevent loss on redeploy
- sns.tf — two topics with tags, two email subscriptions with placeholder endpoints
- outputs.tf — s3 bucket name, dynamodb table name, lambda function name, both SNS ARNs, bedrock model ID
- lambda.tf — claims processor Lambda, DLQ processor Lambda, SQS Dead Letter Queue with 60 second visibility timeout, S3 event source mapping, SQS event source mapping for DLQ processor

**Lambda Function Requirements:**
Produce a single lambda_function.py with these exact capabilities:

1. Dual PDF processing:
   - Download PDF from S3 into memory
   - Attempt pypdf text extraction first
   - If extracted text exceeds 50 characters — text-based PDF confirmed, bypass Textract
   - If extracted text below 50 characters — image-based PDF, route to Textract analyze_document with TABLES and FORMS feature types

2. Bedrock inference:
   - Model: us.anthropic.claude-sonnet-4-5-20250929-v1:0
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
   - processing_error → both SNS-Internal and SNS-Claimant simultaneously

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

**Security Constraints:**
- No hardcoded credentials anywhere
- No hardcoded ARNs — all referenced via Terraform resource attributes
- All sensitive values in variables.tf
- .gitignore must cover .tfstate, .tfstate.backup, .terraform/, *.tfvars, crash.log
- Lambda execution role must use custom least-privilege policy only

**Bedrock Prompt:**
The system prompt passed to Bedrock must instruct the model to:
- Act as a senior insurance claims specialist
- Extract: claimant_name, date_of_birth, policy_number, contact_details, incident_date, claim_filed_date, claim_type, incident_description, total_amount_claimed, cost_breakdown, supporting_documentation_present, prior_claims_detected
- Apply risk flagging logic: amount >= $50,000, prior claims detected, filing delay > 90 days, document inconsistencies, signs of alteration
- Return confidence: high/medium/low
- Return priority: critical/high/medium/low
- Return recommended_action: auto_process/human_review/pending_documentation/processing_error
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
2. IAM policy has exactly the permissions listed — no wildcards, no extras
3. Lambda handler is named lambda_function.lambda_handler
4. pypdf is imported from package/ subdirectory via sys.path insert
5. Both SNS topics are referenced correctly in routing logic
6. SLA deadlines are calculated dynamically not hardcoded
7. All environment variables match what is defined in lambda.tf
8. .gitignore is present in terraform/ folder

## Architect Review Findings (10 April 2026)

**Verdict: ✅ Prompt successful — output is production quality**

**What the AI produced correctly:**
- All 9 Terraform files correctly separated
- IAM least-privilege policy with exact permissions specified
- Dual PDF processing with pypdf/Textract routing
- SLA deadline calculation skipping weekends — more sophisticated than manual build
- Regex-based markdown fence stripping — more robust than manual build
- Float to Decimal conversion with InvalidOperation handling
- Known limitations documented in code comments
- Bonus build_lambda.sh script automating pypdf packaging

**What required architect correction:**
- Environment variable naming — DYNAMODB_TABLE_NAME vs DYNAMODB_TABLE
  — corrected in prompt constraints above
- depends_on references aws_iam_role_policy_attachment rather than
  aws_lambda_permission — valid alternative but differs from tested fix

**Conclusion:**
The one-shot prompt successfully reproduced the core infrastructure
and Lambda function. Two discrepancies identified and corrected through
architect review — consistent with treating the AI as a junior engineer
whose output requires validation. Full redeployment test planned as
final validation step.