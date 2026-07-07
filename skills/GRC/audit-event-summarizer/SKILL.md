---
name: audit-event-summarizer
description: Summarize a supplied batch of governance/audit events into a concise, audit-safe briefing — counts by type, notable denials, and trends. Advisory only; reads provided events, never fetches or mutates. Trigger on "summarize these audit events", "what happened in this audit tail", "governance summary of these logs".
department: GRC
department_id: DEPT-GRC
authority_level: advisory
risk_level: low
source: first-party
license: proprietary
allowed_actions:
  - read_provided_events
  - produce_audit_safe_summary
forbidden_actions:
  - fetch_logs_from_network_or_disk
  - mutate_or_delete_events
  - execute_code_or_shell
  - grant_authority
  - expose_secrets
inputs:
  - a batch of audit/governance event records supplied in the request
outputs:
  - an audit-safe briefing (counts by event type, notable denials, trends) as text
activation_examples:
  - "summarize these audit events"
  - "governance briefing from this audit tail"
  - "what stands out in these logs"
negative_activation_examples:
  - "fetch the audit log"
  - "delete these events"
  - "tamper with the chain"
  - "show me the secrets in the logs"
---

## Purpose
Turn a supplied batch of governance/audit events into a concise, audit-safe briefing
for GRC review. Reads only what is provided; never fetches, mutates, or deletes events.

## When to Use
- Audit/governance events are pasted and the user wants a summary or trend read.

## When Not to Use
- The user wants events **fetched, altered, or deleted** (refuse — the audit chain is authoritative).
- No events are provided.

## Inputs
- Event records in the request (e.g., type, gov_tx_id, severity, timestamp). Nothing fetched.

## Outputs
- Counts by event type; notable denials (SENTINEL_BLOCK, APPROVAL_REQUIRED, COST_GATE_BLOCK,
  GOVERNANCE_UNAVAILABLE_FAIL_CLOSED); trends; and open items for GRC — all audit-safe.

## Governance Rules
- **Advisory only.** Never fetches, mutates, or deletes audit events; the chain is immutable/authoritative.
- Summaries must be **audit-safe**: never surface raw secrets, credentials, or full sensitive
  prompt bodies even if present in the supplied events — report presence/type only.
- Abigail backend gates (Sentinel, HAAP, MM-03, SEC-02 cost, audit) remain authoritative.
- Default plan/review mode; any follow-up action goes through existing governance.

## Procedure
1. Parse supplied events; tally by type and severity.
2. Highlight governance denials and any anomalies (e.g., fail-closed events).
3. Redact/omit any sensitive values; produce a briefing + open items for GRC.

## Audit Requirements
- Record activation with gov_tx_id, skill, department; log a safe summary (event counts) only —
  never re-log raw event contents.

## Tests
- Given events containing a governance denial, the summary surfaces it by type/count.
- If an event carries a secret-looking value, the summary reports presence only, never the value.
- A "fetch/delete/tamper" request is refused.
