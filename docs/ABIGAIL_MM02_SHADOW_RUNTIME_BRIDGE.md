# Abigail MM-02: Shadow Runtime Orchestration Bridge

**Document ID:** ABIGAIL_MM02_SHADOW_RUNTIME_BRIDGE  
**Version:** 1.0  
**Date:** 2026-07-04  
**Status:** ACTIVE  
**Classification:** Internal Governance Doctrine  

---

> **Sprint banner:** Do not test whether Abigail can answer. Test whether Abigail can stay governed.

---

## 1. Purpose

MM-02 wires the MM-01 governance primitives (`RoutingManifest`, `SingleGovernedState`)
into the live `/api/chat` runtime path in **shadow mode only**. For every normal chat
turn, Abigail now builds a deterministic, audit-safe orchestration context *before*
inference and attaches an audit-safe metadata subset to the response.

MM-02 changes **visibility**, not **behavior**. No worker executes, no sub-agent is
routed to, and provider dispatch is unchanged. The bridge exists so that governed
routing context becomes observable on real traffic without turning on autonomous
execution.

**MM-02 is shadow orchestration only.** It creates deterministic routing context
before normal inference; it does not act on that context yet.

---

## 2. Shadow Mode Definition

Shadow mode means the orchestration layer runs alongside the existing runtime and
records what it *would* govern, without altering what actually happens:

- A `RoutingManifest` and `SingleGovernedState` are constructed for each normal chat turn.
- `orchestration_mode` is always `"shadow"`.
- `current_stage` on the governed state is `"routing"`.
- Workers are **not** executed; `active_constraints` always includes `no_worker_execution`.
- The manifest's `human_approval_required` is computed and surfaced, but no action is gated on it yet — it is advisory metadata in MM-02.

---

## 3. Runtime Integration Order

Inside `api_chat` (`abigail/abigail_hardened_enhanced.py`), the order is fixed:

1. Parse request body.
2. Empty-message guard (unchanged behavior).
3. **Governed command bus first** — exact allowlisted operator commands are handled and returned before any orchestration or inference.
4. For non-command normal chat, build the shadow orchestration context via `build_shadow_orchestration_context(...)`.
5. Run the existing `process_message(...)` path **unchanged**.
6. Attach the audit-safe orchestration metadata to the response JSON under an additive `orchestration` key.
7. **Fail soft** — if the bridge returns `None` (any internal exception), the response is returned normally with no `orchestration` key and no stack trace exposed.

---

## 4. Why Command Bus Remains First

The governed command bus (CB-01) classifies exact operator commands
(`status`, `/status`, `api/status`, `/api/status`, `help`, `/help`) before the LLM.
MM-02 preserves this ordering: the command bus is consulted and, if it handles the
request, the function returns immediately. Exact operator commands therefore never
construct a `RoutingManifest` or governed state, and never reach the shadow bridge.
This keeps deterministic operator control paths free of orchestration overhead and
free of provider inference.

**MM-02 keeps command bus operator commands out of the inference provider.**

---

## 5. Why Normal Chat Still Uses the Existing Provider Dispatch

MM-02 does not change model or provider behavior. Normal chat continues through the
existing `process_message(...)` dispatch exactly as before. The shadow bridge runs
purely as a governance preflight: it computes routing metadata from the message and
untrusted `request_metadata`, but performs no inference and issues no provider or
network call itself.

**MM-02 does not change provider dispatch.**

---

## 6. Audit-Safe Metadata

The bridge stores no raw message text. `safe_task_summary` is produced by deterministic
local truncation (120-char bound) plus secret-pattern redaction — never by model
inference. Only the following additive fields are attached to the response:

| Field | Source |
|---|---|
| `manifest_id` | locally generated manifest id |
| `state_id` | locally generated state id |
| `modality` | validated against `VALID_MODALITIES`, defaults to `text` |
| `risk_level` | validated; escalated to `high` on command-style signal |
| `source_trust_class` | `user_supplied` |
| `human_approval_required` | derived from manifest |
| `command_style_signal` | local `CMD_STYLE_INJECTION` pattern match |
| `max_steps` | manifest budget |
| `max_tokens_estimate` | manifest budget |
| `orchestration_mode` | always `"shadow"` |

`request_metadata` is treated as **untrusted input**: `modality` and `risk_level` are
normalized against allowlists before use, and any out-of-range value falls back to a
safe default. Raw prompts, secrets, credentials, environment, internal config, hidden
routes, and full manifest/state payloads are never included.

**MM-02 keeps orchestration metadata strictly additive and non-breaking for existing
clients** — no existing response key is removed or renamed.

---

## 7. Failure Behavior

`build_shadow_orchestration_context(...)` wraps its body in a broad exception guard and
returns `None` on any failure. The `api_chat` integration treats `None` as fail-soft:
the chat response is returned normally with no `orchestration` key attached. No stack
trace, exception text, or partial state is ever exposed to the client. The bridge is
also import-guarded (`_ORCHESTRATION_BRIDGE_OK`), so an import failure degrades to
existing behavior rather than breaking the route.

---

## 8. No Worker Execution

MM-02 defines and records routing context only. No worker agent is instantiated,
handed off to, or executed. `active_constraints` always includes `no_worker_execution`
and `shadow_mode`, and `worker_outputs_refs` is always empty. Worker execution is
explicitly out of scope until a future promotion sprint.

**MM-02 does not execute workers.**

---

## 9. No Provider Calls From Tests

The test suite exercises the bridge and the integration without any provider or network
call. Source-scan guards in both `test_orchestration_runtime_bridge.py` and
`test_orchestration_routing_manifest.py` assert that orchestration modules contain none
of the forbidden provider/network tokens (`groq`, `openai`, `anthropic`, `requests`,
`httpx`, ...). The bridge's capability labels are provider-neutral (`llm_inference`) for
this reason.

---

## 10. Acceptance Criteria

- Shadow orchestration context is built for normal chat.
- Command bus remains first for exact operator commands.
- Exact operator commands do not construct a manifest or governed state.
- Normal chat still reaches the existing provider dispatch unchanged.
- No worker execution occurs.
- No provider calls occur from tests.
- No external network calls occur (localhost only).
- No raw prompts appear in orchestration response metadata.
- Orchestration metadata is additive; no existing response field changes.
- Full test suite passes.
- Sealed baseline `~/Abigailv1` remains untouched.
- Local commit only; no push.

**MM-02 does not modify sealed Abigail V1** (`~/Abigailv1` at `5cdfee1`).

---

## 11. Future MM-03 Promotion Path

MM-03 will begin acting on the governed context that MM-02 only records:

- Enforce `human_approval_required` as a real gate rather than advisory metadata.
- Introduce bounded worker execution under the MM-01 `SignedHandoffPacket` contract,
  with capability profiles enforced at dispatch.
- Promote `current_stage` beyond `routing` through the governed state machine.
- Retain shadow observability as the fallback posture for any un-promoted request class.

Promotion is gated: no execution capability is enabled until the corresponding
governance gate, tests, and operator approval are in place.

---

## Citation Note

This document references only internal LOGOS / GovSec / HAAP / Sentinel doctrine and the
in-repo MM-01 primitives. No external citations were validated during this sprint and
none are treated as authoritative doctrine.
