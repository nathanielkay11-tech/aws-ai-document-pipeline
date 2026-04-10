# Prompt Version 2

*Personal observations and reflections from first live test run — 09 April 2026.*

## Date
09 April 2026

## Purpose
v2 is required to iterate and expand to allow for all possible 
use cases in scope of the project.

## What I Observed from Test 1

### The Prompt
After troubleshooting iteratively for permissions, syntax, etc. 
the prompt performed well. I can see how adding multiple use 
cases and document types will adjust how we approach v2.

### The Pipeline
The Python code needed the most updating. This is because it is 
doing the heavy lifting of the flow by interacting and calling 
all the other logical resources and services being used.

### What I Would Test Next
Looking forward to testing the image-based PDF document type 
to see Textract and OCR at work.

## What Changed from v1
No prompt changes in this version. Iterative edits were made 
to the Lambda Python code to handle permissions, JSON parsing, 
float to Decimal conversion, and markdown stripping. The prompt 
itself performed as designed.

## Known Limitations
- Auto-process audit reporting deferred to Phase 2 — see ADR-010
- SLA reminder notifications deferred to Phase 2 — see ADR-010