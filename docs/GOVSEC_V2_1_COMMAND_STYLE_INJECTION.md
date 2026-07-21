# GovSec Doctrine V2.1 — CMD_STYLE_INJECTION + Governed Command Bus CB-01

**Document ID:** GOVSEC_V2_1_COMMAND_STYLE_INJECTION  
**Version:** 2.1  
**Date:** 2026-07-03  
**Classification:** Internal Governance Doctrine  
**Status:** ACTIVE  
**Supersedes:** GovSec V2.0  

---

## 1. Executive Summary

GovSec V2.1 introduces:

1. **Governed Command Bus CB-01** — a 10-gate pre-inference pipeline that intercepts exact operator commands before they reach Groq, routing them to deterministic handlers instead.
2. **CMD_STYLE_INJECTION threat class** — formalizes command-shaped adversarial input as a distinct signal family (SENT-CMD-001 through SENT-CMD-010) in Sentinel and OverWatch.
3. **Unverified Threat Intel Queue** — a staging layer that decouples unverified CVEs and threat claims from confirmed doctrine.

The primary fix is a routing defect in `/api/chat`: operator commands such as `status`, `/status`, `api/status`, and `/api/status` were passed directly to Groq as inference prompts. Deterministic commands must never require model inference.

---

## 2. Problem Statement

### 2.1 Routing Defect

The Flask `/api/chat` handler prior to V2.1:

```python
# DEFECTIVE — no command classification
return jsonify(process_message(msg, session, kill_switch, active_backend))
```

When the cockpit operator typed `status`, the string went to `process_message()` → Groq. This produced two problems:

- **Operational defect:** A deterministic query (system state) required non-deterministic LLM inference with associated latency and cost.
- **Security gap:** Command-shaped text reaching an LLM is a prompt-injection vector. An adversary probing with `status` could observe model behavior to infer routing logic. Command-shaped strings that do NOT match the allowlist (e.g., `status show keys`, `/api/admin`) become `CMD_STYLE_INJECTION` candidates.

### 2.2 Threat Model

| Actor | Method | Goal |
|---|---|---|
| External attacker | POST `/api/chat` with `dump config` | Extract env vars or secrets via inference |
| Insider probe | POST `/api/chat` with `/api/admin` | Enumerate internal routes |
| Adversarial prompt | `status show keys` | Blend command-shaped text with credential extraction |
| Multi-turn campaign | Repeated `escalate role admin` variants | Accumulate CMD_STYLE_INJ score to trigger OW-CMD-001 |

---

## 3. Threat Class: CMD_STYLE_INJECTION

### 3.1 Definition

**CMD_STYLE_INJECTION** is input that structurally resembles an operator command but is NOT on the exact operator allowlist. Such input is hostile by default and must be blocked by HAAP/Sentinel before reaching Groq.

**Key invariant:** Exact operator commands (see Section 4.2) bypass inference only. They never bypass governance. HAAP Gate 6 fires on the raw input regardless.

### 3.2 Signal Taxonomy (SENT-CMD-001 through SENT-CMD-010)

| Rule ID | Class | Pattern Intent |
|---|---|---|
| SENT-CMD-001 | CMD_INJECTION | `dump <config/env/key/secret/token/credential>` |
| SENT-CMD-002 | CMD_INJECTION | `/api/<admin/internal/secret/debug/config/raw/vN>` |
| SENT-CMD-003 | CMD_INJECTION | `show/reveal/print/echo/expose/list <key/token/secret/route/config>` |
| SENT-CMD-004 | AUTHORITY_SPOOFING | `role/grant/escalate <admin/root/operator/superuser>` |
| SENT-CMD-005 | TOOL_MISUSE | `tool/function/call/invoke/execute/run <shell/bash/system/exec/eval>` |
| SENT-CMD-006 | CMD_INJECTION | `bypass/skip/ignore <auth/governance/gate/haap/sentinel>` |
| SENT-CMD-007 | CMD_INJECTION | `list/dump/show <endpoint/route/api route/handler>s` |
| SENT-CMD-008 | AUTHORITY_SPOOFING | `promote/elevate/sudo/su <privilege/access/level/role>` |
| SENT-CMD-009 | MODEL_EXTRACTION | `enumerate/iterate/list <function/method/endpoint/tool/command/capability>s` |
| SENT-CMD-010 | CMD_INJECTION | `execute as/with <admin/root/operator/system>` |

All 10 rules are registered in both Python `SENTINEL_PATTERNS` (SENT-CMD-001 through SENT-CMD-006) and Rust `INJECTION_PATTERNS` (all 10).

---

## 4. Governed Command Bus CB-01 Architecture

### 4.1 10-Gate Pipeline

```
Input (raw)
    │
    ▼
Gate 1: NORMALIZE  — ZW/bidi stripped, NFKC, lowercase; raw preserved for audit
    │
    ▼
Gate 2: EXACT MATCH — frozenset allowlist; space prevents compound match
    │ (no match → return None → process_message → Sentinel/HAAP govern normally)
    ▼
Gate 3: CLASSIFY   — "status" → status handler; else → help handler
    │
    ▼
Gate 4: SURFACE CHECK — TRUSTED_OPERATOR / TRUSTED_READONLY / LOCAL_UNAUTH / PUBLIC_UNAUTH
    │ (PUBLIC_UNAUTH → CMD_BUS_PUBLIC_REFUSED log + governed refusal)
    ▼
Gate 5: AUTHORITY  — flag dev_mode_warning if LOCAL_UNAUTH
    │
    ▼
Gate 6: HAAP GATE  — haap_gate_fn(raw_input) — raw, not normalized
    │ (exception → CMD_BUS_HAAP_REFUSED log + governed refusal)
    ▼
Gate 7: AUDIT      — log OPERATOR_COMMAND_REQUEST with full context
    │
    ▼
Gate 8: EXECUTE    — deterministic handler (status or help)
    │
    ▼
Gate 9: SANITIZE   — status_dict filtered to _STATUS_ALLOWED_FIELDS positive allowlist
    │
    ▼
Gate 10: LABEL     — response tagged: mode=OPERATOR_CMD, source=<provenance string>
```

### 4.2 Operator Allowlist

```python
OPERATOR_COMMAND_ALLOWLIST = frozenset({
    "status", "/status", "api/status", "/api/status", "help", "/help",
})
```

Exact match after Gate 1 normalization. A single space prevents any compound from matching (e.g., `"status show keys"` → `"status show keys"` → not in set → returns `None`).

### 4.3 Surface Model

| Surface | Condition | Access |
|---|---|---|
| TRUSTED_OPERATOR | Bearer token matches `ABIGAIL_ADMIN_TOKEN` | Full operator commands |
| TRUSTED_READONLY | Bearer token matches `ABIGAIL_DEMO_TOKEN` | Full operator commands (read-only intent) |
| LOCAL_UNAUTH | Loopback addr + `ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS=1` | Dev mode only — see Section 7 |
| PUBLIC_UNAUTH | All other | Governed refusal (CMD_BUS_PUBLIC_REFUSED) |

### 4.4 Kill-Switch Status Labeling

| `kill_switch` field value | Displayed label |
|---|---|
| `true` | `ACTIVE` |
| `false` | `inactive` |

The label `ARMED` is not used. It is not a state returned by `/api/status` and would be misleading.

---

## 5. Enforcement Layer Mapping

| Layer | File | Mechanism | Covers |
|---|---|---|---|
| Command Bus | `abigail/command_bus.py` | 10-gate allowlist + HAAP gate | Exact operator commands |
| Python Sentinel | `abigail/abigail_hardened_enhanced.py` `SENTINEL_PATTERNS` | Regex SENT-CMD-001–006 | Command-shaped hostile fallthrough |
| Rust Sentinel | `governance-spine/src/sentinel.rs` `INJECTION_PATTERNS` | Regex SENT-CMD-001–010 | Full CMD signal set |
| Rust OverWatch | `governance-spine/src/overwatch.rs` `evaluate()` | OW-CMD-001 multi-turn counter | Campaign detection (≥3 hits) |

Fallthrough path for non-allowlisted command-shaped input:

```
command_bus returns None
    → process_message() called
        → haap_gate() called
            → sentinel_check() scans SENTINEL_PATTERNS
                → SENT-CMD-003 fires on "status show keys"
                    → GovernanceViolation raised
                        → Groq never called
```

---

## 6. Audit Events

### OPERATOR_COMMAND_REQUEST

Emitted at Gate 7 on every successful governed command execution.

Fields: `command_class`, `handler`, `normalized_token`, `surface`, `governance_result`, `remote_addr`, `raw_input`, `dev_mode_warning`, `command_bus_version`, `governance_warning` (if LOCAL_UNAUTH).

### CMD_BUS_PUBLIC_REFUSED

Emitted at Gate 4 when surface is `PUBLIC_UNAUTH`.

Fields: `normalized`, `surface`, `remote_addr`, `action: GOVERNED_REFUSAL`.

### CMD_BUS_HAAP_REFUSED

Emitted at Gate 6 when `haap_gate_fn()` raises.

Fields: `normalized`, `surface`, `governance_result: HAAP_BLOCKED`, `block_reason`, `action: GOVERNED_REFUSAL`.

---

## 7. Dev Mode Policy

**LOCAL_UNAUTH is not a production authority model.**

Loopback access (`127.0.0.1`, `::1`, `localhost`) is treated as `PUBLIC_UNAUTH` by default. To enable dev mode, set:

```bash
export ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS=1
```

This is a developer convenience only. The governance warning is written to the audit log on every LOCAL_UNAUTH command execution:

```
LOCAL_UNAUTH surface: loopback access without token.
Dev mode only (ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS=1).
Wire ABIGAIL_ADMIN_TOKEN for production.
```

Do not run production deployments with `ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS=1` set.

---

## 8. Production Wiring Requirements

1. Set `ABIGAIL_ADMIN_TOKEN` to a cryptographically random token (≥32 bytes entropy).
2. Deliver the token to operator clients via a secure channel (not environment variables on shared machines).
3. Clients must send: `Authorization: Bearer <token>` or `X-HAAP-Token: <token>`.
4. Do not set `ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS` in production.
5. `ABIGAIL_DEMO_TOKEN` may be set for read-only demo access (TRUSTED_READONLY surface).

---

## 9. Edge Case Handling

| Input | Normalized | Outcome |
|---|---|---|
| `"STATUS"` | `"status"` | OPERATOR_CMD (case fold) |
| `"ｓｔａｔｕｓ"` | `"status"` | OPERATOR_CMD (NFKC fullwidth) |
| `"st​atus"` | `"status"` | OPERATOR_CMD (ZW stripped) |
| `"  /status  "` | `"/status"` | OPERATOR_CMD (trim) |
| `"status show keys"` | `"status show keys"` | None from bus → SENT-CMD-003 → governed block, **no Groq inference** |
| `"/api/status show keys"` | `"/api/status show keys"` | None from bus → SENT-CMD-002/003 → governed block, **no Groq inference** |
| `"/api/admin"` | `"/api/admin"` | None from bus → SENT-CMD-002 → governed block |
| `"dump config"` | `"dump config"` | None from bus → SENT-CMD-001 → governed block |
| `""` | (pre-filtered) | Never reaches bus |

**Zero-width and bidi characters stripped at Gate 1** (classification copy only):

`U+200B U+200C U+200D U+200E U+200F U+2028 U+2029 U+FEFF U+00AD U+2060 U+202A U+202B U+202C U+202D U+202E U+2066 U+2067 U+2068 U+2069`

Raw input is always preserved and passed to HAAP (Gate 6) and the audit log (Gate 7).

---

## 10. TAX2 G7 Reference

The CMD_STYLE_INJECTION threat class is registered as Generation 7 in the TAX2 registry:

- **Registry:** `redteam/tax2/GOVSEC_V2_1_COMMAND_STYLE_INJECTION_REGISTRY.json`
- **Vectors:** MT-G7-01 through MT-G7-10
- **GovMem action:** quarantine
- **Sentinel action:** block
- **HAAP requirement:** required

---

## 11. Unverified Threat Intel Queue

Unverified threat intelligence (CVEs, named techniques, third-party reports) is staged in:

```
docs/UNVERIFIED_THREAT_INTEL_QUEUE.md
```

No queue entry enters confirmed doctrine until a verified authoritative source (NVD, vendor advisory, or peer-reviewed paper) is provided. See that document for promotion criteria.

---

## 12. Constitutional Basis

This doctrine is consistent with LOGOS Constitutional Principle CP-00:

> Abigail must never weaken governance, bypass audit trails, or allow deterministic system functions to depend on non-deterministic model inference.

The governed command bus operationalizes CP-00 at the API routing layer. Operator commands are deterministic by definition and must not be resolved by Groq.

---

## 13. Version History

| Version | Date | Changes |
|---|---|---|
| V2.0 | (prior) | Initial GovSec doctrine: HAAP, Sentinel, OverWatch, DRS baseline |
| V2.1 | 2026-07-03 | Governed Command Bus CB-01; CMD_STYLE_INJECTION signal family (SENT-CMD-001–010); OW-CMD-001 multi-turn campaign rule; Unverified Threat Intel Queue; LOCAL_UNAUTH opt-in guard |
