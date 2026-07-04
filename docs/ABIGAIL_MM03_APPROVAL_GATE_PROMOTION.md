# Abigail MM-03: Approval-Gate Promotion

**Document ID:** ABIGAIL_MM03_APPROVAL_GATE_PROMOTION
**Version:** 1.0
**Date:** 2026-07-04
**Status:** ACTIVE
**Classification:** Internal Governance Doctrine
**Authority:** LOGOS Governance Systems Inc.

---

> **Doctrinal transition:** MM-02 made governance *visible*. SEC-02 made the runtime
> *survivable*. MM-03 promotes *advisory* approval into *enforced* approval.

## Purpose

MM-03 promotes the `human_approval_required` signal — computed but only *observed* in
MM-02 — into an **enforced** stop. When it is true (and no hard-block fired first),
Abigail returns a governed `APPROVAL_REQUIRED` response and performs **no** action: no
worker execution, no external action, no file write, no tool/outbound path, and no
provider inference or spend. This is the required layer before any real agent execution
is enabled.

## When the gate fires

`human_approval_required` is computed deterministically by the routing manifest
(`_requires_human_approval`): true when `risk_level ∈ {high, critical}`, or
`request_type ∈ HUMAN_APPROVAL_REQUEST_TYPES`, or a required tool ∈ `HUMAN_APPROVAL_TOOLS`.

On the current `/api/chat` path (`request_type="chat_inference"`, no tools), that reduces
to **`risk_level` high/critical**, which occurs when:
1. a CMD_STYLE_INJECTION signal is detected (bridge escalates risk to `high`), or
2. the client's `request_metadata` declares `risk_level: high|critical`.

Normal low/medium chat is unaffected.

## Enforcement point and ordering (hard-block wins)

Per operator decision, **Sentinel/HAAP hard-blocks win**; the approval gate covers only
requests that are *not* hard-blocked. The checkpoint therefore sits inside
`process_message`, immediately **after** the kill-switch, A2A, Rust-Sentinel, and HAAP
gates pass, and **before** DRS scoring, the tacit/model-router passes, and the provider
dispatch:

```
kill-switch → grounded(local) → A2A → Sentinel → HAAP   ← hard-blocks return here
      → [MM-03 approval gate]                            ← stop before inference/spend
      → DRS → tacit → model-router → provider dispatch (Groq)
```

Consequences:
- Adversarial / command-style input is **hard-blocked** (`BLOCKED` / `SENTINEL_BLOCK`)
  and never reaches the approval gate — it is not reclassified as "approvable".
- A high-risk-but-not-adversarial request (e.g. client-declared `risk_level:high`)
  returns `APPROVAL_REQUIRED` before any provider spend.
- Benign local grounded answers (no action, no spend) may still return, as they precede
  the hard-block gates and constitute no action.

## Governed response shape

`mode: "APPROVAL_REQUIRED"`, `ok: false`, with an audit-safe `approval` block:
`human_approval_required`, `enforced: true`, `manifest_id`, `state_id`, `risk_level`,
`command_style_signal`, and a `reason` list (e.g. `["risk_level:high"]`). The raw prompt
never appears in the response. MM-02 `orchestration` and SEC-02 `cost` metadata remain
attached additively.

## Reusable primitive

`orchestration.runtime_bridge.approval_gate_blocks(response_metadata)` is the single
source of truth for "must Abigail stop and escalate?". Every future worker/tool/outbound
dispatch path must call it before acting, so enforcement is consistent as real execution
is added in later sprints.

## What MM-03 does NOT do

- It does not add an approval-*grant* channel — there is intentionally no way yet to
  approve and resume. An approval-required request simply stops. Granting is a later
  sprint with its own operator-auth gate.
- It does not execute workers, tools, or outbound calls.
- It does not change provider dispatch for non-gated chat.
- It does not weaken Sentinel/HAAP, the command bus, the cost gate, or MM-02.
- CLI dispatch (`process_message` without `approval_meta`) is not gated — the operator
  console is trusted; enforcement is applied at the HTTP surface.

## Tests

`tests/test_approval_gate_promotion.py` (7 tests): predicate truth table; `process_message`
returns `APPROVAL_REQUIRED` before inference (provider never called) and passes through
without `approval_meta`; route returns `APPROVAL_REQUIRED` for high-risk with no provider
call and no raw-prompt leakage; **command-style input is hard-blocked, not approval-gated**;
normal low-risk chat still reaches inference with MM-02 + cost metadata.

- MM-03 suite: **7 passed**
- Full suite: **1434 passed** (no regressions)

## Acceptance Criteria

- `human_approval_required=true` (not hard-blocked) → governed `APPROVAL_REQUIRED`, no
  inference/worker/tool/outbound/file, no provider spend.
- Sentinel/HAAP hard-blocks still win for adversarial/command-style input.
- Normal chat unchanged; MM-02 orchestration and SEC-02 cost metadata preserved.
- Audit-safe reason fields only; no raw prompt.
- `~/Abigailv1` untouched; local commit only; no push.

---

*Cites only internal LOGOS / GovSec / HAAP / MM-01 / MM-02 doctrine and in-repo code.
No external citations.*
