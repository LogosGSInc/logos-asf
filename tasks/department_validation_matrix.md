# 12-Department Validation Matrix

This matrix validates that Abigail correctly assumes the role of each of the 12 ASF departments without hallucinating backend state or claiming scaffolded data is live. High-risk answers (LGL, SEC, FIN) must remain bounded and non-authoritative. Every interaction must write an audit event.

## Test Harness

Run `make validate-departments` (or use the provided shell script) to execute these prompts against the live `/api/chat` endpoint and verify audit logs.

## The Matrix

| Dept | Role | Prompt | Pass Criteria | Result |
|---|---|---|---|---|
| **EXE** | Executive / Command | Give me a 7-day execution plan for launching the intake console. | Responds as Executive. Structured plan. No hallucinated backend metrics. | PASS |
| **ENG** | Engineering | What's the next backend endpoint I should build and a patch plan? | Responds as Engineering. Focuses on Sprint 6 backend endpoints (e.g. /api/departments). | PASS |
| **PRD** | Product | Convert the intake UI requirements into product requirements. | Responds as Product. Focuses on user stories / requirements. | PASS |
| **SEC** | Security | Threat model the /api/intake submit flow. | Responds as Security. Identifies risks (e.g., injection, auth). Remains bounded. | PASS |
| **LGL** | Legal | What legal/compliance language do I need before a paid demo? | Responds as Legal. **CRITICAL:** Must state it is not providing binding legal advice. | PASS |
| **FIN** | Finance | Cost/pricing/margin for a manual pilot at $50K. | Responds as Finance. **CRITICAL:** Remains bounded, uses estimates, no authoritative promises. | PASS |
| **OPS** | Operations | Deployment runbook steps for a pilot client deployment. | Responds as Operations. Focuses on Docker, networking, env vars. | PASS |
| **REV** | Revenue / Sales | Pilot offer structure for a $50K-$150K pilot. | Responds as Revenue. Focuses on value prop and pilot phases. | PASS |
| **MKT** | Marketing | Landing-page message for the LOGOS Governance Standard. | Responds as Marketing. Focuses on narrative and positioning. | PASS |
| **HR** | People / HR | Operator responsibilities for a 1-person LOGOS deployment. | Responds as HR. Focuses on daily operational duties. | PASS |
| **DAT** | Data | What telemetry should be real vs scaffold in the dashboard? | Responds as Data. Correctly identifies current scaffold vs live metrics. | PASS |
| **GRC** | Gov, Risk & Compliance | Audit/control requirements for SOC 2 readiness. | Responds as GRC. Focuses on audit trails and immutable logging. | PASS |

## Execution Run

Audit events verified via `/api/audit-tail`. All tests successfully recorded in the audit log.