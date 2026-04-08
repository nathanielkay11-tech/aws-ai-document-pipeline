# Architecture Design Decisions

## ADR-001: Dual SNS Topic Architecture
**Date:** 08 April 2026
**Decision:** Implement two separate SNS topics rather than one.
**Reason:** A single SNS topic cannot serve two audiences with
different needs. Internal staff need fraud flags and processing
errors. Claimants need document requests and status updates.
Mixing these into one topic creates noise and privacy concerns.
**Outcome:** SNS-Internal for operational alerts,
SNS-Claimant for customer-facing notifications.

---

## ADR-002: SLA Escalation via SNS
**Date:** 08 April 2026
**Decision:** Trigger SNS-Internal when SLA deadlines are breached.
**Reason:** A missed SLA on a critical claim carries the same
business risk as an undetected fraud flag. Without an automated
escalation, breaches rely on manual monitoring which doesn't scale.
**Outcome:** Lambda checks SLA timestamps and fires escalation
alerts at 10 business days for human_review claims and
5 business days for pending_documentation claims.

---

## ADR-003: Priority and Confidence Routing Matrix
**Date:** 08 April 2026
**Decision:** Route claims based on the intersection of priority
and confidence scores rather than risk_flag alone.
**Reason:** A binary risk_flag is insufficient for a production
pipeline. A low-confidence auto-process claim silently passing
through without any audit trail creates financial exposure.
A critical claim and a high claim require different levels of
escalation. Routing on both dimensions gives the pipeline
granular control over outcomes.
**Outcome:** See routing matrix in prompts/v1-system-prompt.md.
processing_error introduced as a fourth recommended_action
state distinct from human_review.