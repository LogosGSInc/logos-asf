# MR-04: Live Provider Router Dispatch

**Document ID:** MR04_LIVE_PROVIDER_ROUTER_DISPATCH
**Version:** 1.0
**Date:** 2026-07-05
**Status:** ACTIVE
**Authority:** LOGOS Governance Systems Inc.

---

## Purpose

Unify the dry-run model router with live provider dispatch so Abigail can route an
**approved** request to the best available provider under approval, cost, sensitivity,
subscriber-tier, and audit controls. Three distinct gates, in order:

- **Approval gate** — *IF* the request may proceed.
- **Model router** — *WHICH* provider/model is best within the approved boundary.
- **Dispatcher** — *WHETHER* the chosen provider can actually execute (live-wired? keyed?
  tier-permitted? healthy? approval-cleared? cost-approved?).

## Governed Flow Order

```
1. User request
2. Sentinel / HAAP / GovSec screening
3. Command-bus exact operator command check
4. Risk + sensitivity + task classification
5. Approval gate            (may this proceed?)        ← policy gate
6. Cost gate                (budget ceiling, tier)
7. Model router             (which provider is best?)  ← capability gate
8. Dispatcher live-check    (wired? key? tier? health? approval? cost?)  ← execution gate
9. Provider adapter executes  — OR governed fallback
10. Audit log
11. Response
```

`governed_route_and_dispatch()` enforces 5→6→7→8: **the router is never consulted until
approval is cleared and cost is approved** (proven by tests with a router spy).

## Approval Gate vs Model Router vs Dispatcher

- The **approval gate is not the router.** High-risk / sensitive / external-action /
  file-write / publish / email / spend / deploy / privileged / tool-use requests require
  approval *before* routing. Normal low-risk chat auto-allows so Abigail stays usable.
- The **router operates only inside the approved boundary** — it selects, it does not
  authorize.
- The **dispatcher is the execution gate** — it refuses to run a selected provider that
  is not live-wired, keyed, tier-permitted, healthy, approval-cleared, and cost-approved,
  returning a governed fallback instead of crashing or mis-routing.

## Provider Capability Registry

`abigail/model_router/provider_capabilities.py` — a static matrix per provider
(strengths, modalities, context window, max output, tool/structured support, latency,
coarse cost-per-1k), plus health status (available / degraded / unavailable /
circuit_open), key **presence** (never values), subscriber-tier eligibility, and per-tier
cost ceilings. `registry_snapshot()` is audit-safe (presence booleans only).

## Provider Tiers and Subscriber Mapping

| Tier | Permitted providers |
|---|---|
| free_trial | groq, current_backend, local, ollama |
| paid | groq, anthropic, openai, xai, perplexity, current_backend, local, ollama |
| pro_business | + gemini, higher cost ceilings |
| sensitive_governed | local, current_backend (approval-gated) |

## Router Selection Logic

Selection maps task/risk/sensitivity/capability to a provider (e.g. fast chat → Groq;
careful policy/legal review → Anthropic; structured code planning → OpenAI; realtime
social terrain → xAI; sensitive data → local/restricted with approval). The router
remains dry-run for classification; **execution** is owned by the dispatcher.

## Dispatcher Live-Capability Checks

Order inside `dispatch()`: (1) live-wired in `BACKEND_DISPATCH`; (2) key present;
(3) tier permits; (4) health available; (5) approval cleared; (6) cost approved. Only if
all pass does the live adapter run. **OpenAI and xAI are now live-wired** (`call_openai`,
`call_xai` added to the runtime with `BACKENDS` + `BACKEND_DISPATCH` entries) — so router
policy and live dispatch now agree for Groq, Anthropic, OpenAI, and xAI (keys present).

## Fallback Behavior

Any failed check yields a governed result — never a crash:
`{provider_selected, dispatch_status, reason, fallback_provider, audit_record}`.
Reasons: `provider_not_live_wired`, `key_missing`, `tier_not_permitted`,
`provider_<health>`, `cost_ceiling_exceeded`, `adapter_error:<Type>`. Approval-not-cleared
returns `dispatch_status: approval_required` (no dispatch, no fallback provider). Fallback
selection is deterministic (`groq → current_backend → local`, filtered by tier + key).

## Audit Trail

Every dispatch/fallback carries an `audit_record` (provider_selected, dispatch_status,
reason, fallback_provider, subscriber_tier, timestamp). No secret values are emitted.

## Test Results

- `tests/test_provider_capability_registry.py` — matrix, key presence, tier eligibility, health, audit-safe snapshot
- `tests/test_model_router_live_dispatch.py` — every fallback reason + all-gates-pass execution + adapter-error fallback + governed-shape
- `tests/test_router_approval_cost_integration.py` — router does not run before approval / before cost; runs and dispatches when gates pass; router selection honored
- **MR-04 suite: 20 passed**; existing model-router + governance regression: 85 passed;
  **full suite: 1516 passed** (no regressions). No provider calls, no network in automated tests.

## Known Limitations

- Health is static (`available`) — a live health-probe / circuit-breaker layer is future work.
- The cost gate here uses coarse relative ceilings and composes with, but does not yet
  unify into, the SEC-02 runtime cost gate.
- `governed_route_and_dispatch` is not yet wired into `/api/chat`; the runtime still uses
  the single active backend. Wiring is a follow-up once live smoke tests pass.
- Live provider smoke tests (one tiny gated call per provider) are intentionally **not**
  run in automated tests — operator-approved only.

## Path to AG-01 Swarm Activation

AG-01 (governed local swarm) is already committed as a local harness. MR-04 gives it a
real, governed multi-provider execution path: once `governed_route_and_dispatch` is wired
into the runtime and live smoke tests confirm each provider, swarm workers can dispatch to
the best provider within the same approval/cost/tier/audit envelope.

---

*Any claim about mixture-of-experts routing maps to a passing test showing governed
fallback when a provider is not live. No provider call occurs without approval, cost, key,
tier, and live-wiring all verified. Cites only internal doctrine and in-repo code.*
