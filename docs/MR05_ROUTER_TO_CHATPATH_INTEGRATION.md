# MR-05 — Governed Model Router Wired Into the `/api/chat` Request Path

## Purpose

MR-05 connects the MR-04 governed dispatcher (`governed_route_and_dispatch`) to the
live `/api/chat` request path so that Abigail can dynamically route an **approved,
non-command, non-public, normal** chat request to the best live provider *under
governance* — instead of always calling the single `active_backend` directly.

Integration is gated behind a single three-state environment flag,
`ABIGAIL_MOE_ROUTER_MODE`, so the new behavior is opt-in and reversible. Mode `0`
is byte-for-byte the pre-MR-05 behavior; mode `1` proves routing decisions without
spending; mode `2` performs live governed router dispatch.

No governance layer is weakened. Every existing gate — Sentinel, HAAP, GovSec,
the command bus, the MM-03 approval gate, the SEC-02 cost gate, the Cost Governor,
DEP.KEYSTONE, and the training gates — runs and resolves *before* the router
dispatch layer is ever reached.

## Current State Before MR-05

- MR-04 committed at `6af6bc1`; live model-id fix at `a45f6c3`.
- Four providers live-wired in the MR-04 dispatch harness: `groq`, `anthropic`,
  `openai`, `xai` (via `BACKEND_DISPATCH`).
- `/api/chat` always dispatched through the single `active_backend`
  (`BACKEND_DISPATCH.get(active_backend[0], call_groq)`), inside `process_message`.
- The MR-01 shadow route card and MR-02 provider dry-run already ran in
  `process_message` for observability, but never changed dispatch.
- Full suite: 1516 passing.

## Router Mode 0: Single Backend

`ABIGAIL_MOE_ROUTER_MODE=0` (also the default, and the fail-closed value).

- `/api/chat` uses `active_backend` directly — identical to pre-MR-05 behavior.
- The MR-04 dispatcher is never consulted.
- Response metadata: `dispatch_status: "single_backend"`, `live_dispatch: false`,
  `selected_provider: <active_backend>`, `router_mode: "0"`.

## Router Mode 1: Dry-Run Router

`ABIGAIL_MOE_ROUTER_MODE=1`.

- `/api/chat` records the audit-safe route decision (from the already-computed
  MR-01 route card) and logs a `ROUTER_DRY_RUN` event.
- It **never** calls a provider through the MR-04 dispatcher and **never** invokes
  `governed_route_and_dispatch`.
- The existing `active_backend` still produces the actual response, so behavior is
  observably unchanged for the caller apart from the added router metadata.
- Response metadata: `dispatch_status: "dry_run"`, `live_dispatch: false`,
  `selected_provider: <router's choice>`, `router_mode: "1"`.

This mode lets buyers/operators observe *what the router would choose* with zero
live spend and zero provider-side effect.

## Router Mode 2: Live Router

`ABIGAIL_MOE_ROUTER_MODE=2`.

- Eligible normal chat is dispatched through MR-04 `governed_route_and_dispatch`
  **after** Sentinel/HAAP, command bus, public-intent, approval, and cost gates
  clear.
- On success: `dispatch_status: "executed"`, `live_dispatch: true`, the routed
  provider's text is returned.
- On any dispatcher outcome other than `executed` (unavailable provider, missing
  key, tier not permitted, degraded health, sanitized adapter error): a governed
  fallback to the active/current backend produces the response, reported as
  `dispatch_status: "fallback"`, `fallback_used: true`.
- The router layer never crashes the request: an unexpected exception from the
  dispatcher is caught, logged as `ROUTER_DISPATCH_ERROR` (type name only), and
  falls back with `reason: "router_exception_sanitized"`.

## Gate Ordering

The pre-MR-05 order is preserved exactly. MR-05 inserts nothing before any gate —
it only replaces the *final backend-dispatch step* with a mode-aware dispatch:

1. Kill switch / HAAP violation check
2. Grounded-answer shortcut
3. A2A relay hard-stop (HAAP Layer 1a)
4. Rust Sentinel OverWatch verdict (quarantined / hard_locked / restricted)
5. Python HAAP gate
6. **MM-03 approval gate** → returns `APPROVAL_REQUIRED` if flagged
7. **UX-01 public-intent** → returns `PUBLIC_ASSIST` canned answer if matched
8. DRS scoring, tacit pre-pass, MR-01 route card, MR-02 provider dry-run
9. **Backend or router dispatch** ← MR-05 mode-aware layer

The **SEC-02 cost gate** runs in `api_chat` *before* `process_message` is called
(a cost block returns `COST_BLOCKED` and never reaches the router). As a
defense-in-depth measure the router layer re-checks the deterministic local cost
budget before any mode-2 provider dispatch when no upstream cost state is supplied
(the check is idempotent and makes no billing call).

The command bus also runs in `api_chat` before `process_message`, so exact
commands never reach the router.

## Approval Gate Interaction

The MM-03 approval gate (step 6) returns a governed `APPROVAL_REQUIRED` response
before any inference, tool, outbound call, file write, or provider dispatch. A
high-risk request therefore stops **before** the router runs in every mode. MR-05
adds a second, in-dispatcher defense: mode-2 dispatch is only ever invoked with
`approval_state="cleared"`, and the MR-04 dispatcher itself refuses to execute if
approval is not cleared.

## Cost Gate Interaction

The SEC-02 Cost Governor gate runs before `process_message`; a block short-circuits
with `COST_BLOCKED` and the router is never reached. Within mode 2, the router
passes an approved cost state into `governed_route_and_dispatch`, which enforces
the cost gate *again* before selecting or dispatching to any provider. Cost is
therefore checked before provider dispatch on every path.

## Command Bus Interaction

Command-bus exact commands are detected and handled in `api_chat` **before**
`process_message` and thus before any router mode. Command bus behavior is
unchanged; commands never go through router dispatch in mode 0, 1, or 2.

## PUBLIC_ASSIST Interaction

UX-01 public canned answers (`PUBLIC_ASSIST`) are returned from `process_message`
before the DRS/router stage. They are no-inference answers and never call a
provider or the router in any mode. Their response carries no router metadata.

## Audit Metadata

The `/api/chat` response gains a `router` object with only audit-safe fields:

- `router_mode` — `"0"` | `"1"` | `"2"`
- `selected_provider` — provider name the router chose (or the active backend)
- `dispatch_status` — `single_backend` | `dry_run` | `executed` | `fallback`
- `fallback_used` — boolean
- `fallback_provider` — provider that actually served on fallback (or null)
- `reason` — governance code only (e.g. `router_mode_0`, `key_missing`,
  `router_exception_sanitized`); never a raw error message
- `live_dispatch` — `true` only when the MR-04 live dispatcher was invoked
- `request_type` — coarse route classification (e.g. `normal_chat`), when known

Audit log events added: `ROUTER_MODE_CONFIG_WARNING`, `ROUTER_DRY_RUN`,
`ROUTER_LIVE_DISPATCH`, `ROUTER_DISPATCH_ERROR`. `TURN_COMPLETE` gains
`router_mode` and `dispatch_status`.

**Never** included in metadata or logs: raw prompt text, API keys or key values,
environment variable names/values, provider headers, hidden topology, or secret
configuration. An invalid `ABIGAIL_MOE_ROUTER_MODE` value is rejected with a
warning that records only that the value was invalid and that it fell back to
`"0"` — the offending value itself is never echoed.

## Fallback Behavior

- Mode 0: no fallback concept — the active backend is the only responder.
- Mode 1: the active backend responds; the router decision is advisory only.
- Mode 2: if the routed provider cannot execute (not live-wired, key missing,
  tier not permitted, unhealthy, or an adapter error), the request falls back to
  the active/current backend and is reported with `fallback_used: true`. The MR-04
  dispatcher's own governed fallback selection is surfaced in the audit record;
  the response is produced by the active/current backend so the request never
  fails or hangs.

## Tests

`tests/test_moe_router_chatpath_integration.py` (28 tests) covers:

- Mode resolution: valid `0/1/2`, invalid values fail closed to `0`, unset → `0`.
- Mode 0 uses the single active backend; router never consulted.
- Mode 1 returns `dispatch_status: "dry_run"`, `live_dispatch: false`, and never
  calls a provider adapter or the MR-04 live dispatcher.
- **`test_moe_router_dry_run_returns_dry_run_and_never_calls_provider_adapter`** —
  the explicit dry-run safety proof (spies the MR-04 dispatcher, the execution
  gate, and every live-table adapter; asserts zero calls; confirms the existing
  active-backend behavior remains safe and governed).
- Mode 2 uses `governed_route_and_dispatch` (injected spy) and also exercises the
  **real** dispatcher through a stubbed dispatch table (no network).
- Command-bus exact commands bypass modes 1 and 2.
- UX-01 `PUBLIC_ASSIST` bypasses modes 1 and 2 with no provider call.
- High-risk request returns `APPROVAL_REQUIRED` before router execution.
- Cost block stops before router execution.
- Unavailable provider in live mode returns governed fallback metadata, no crash.
- Provider/router errors are sanitized (no secret/exception text leaks).
- Router metadata contains no raw prompt, key, env value, header, or hidden
  topology, and exposes only the audit-safe field set.
- No provider calls occur in pytest across all modes.

Regression coverage confirmed still green: UX-01 (`test_public_response_calibration`),
MM-03 (`test_approval_gate_promotion`), SEC-02 (`test_runtime_security_hardening`),
command bus (`test_command_bus`), and the MR-04 model-router suites
(`test_provider_capability_registry`, `test_model_router_live_dispatch`,
`test_router_approval_cost_integration`).

Full suite after MR-05: **1544 passing** (1516 baseline + 28 new).

## Known Limitations

- Provider health is a static default matrix in `provider_capabilities`; a live
  health-probe layer is future work. An unhealthy real provider is detected only
  at dispatch time via the sanitized adapter-error → governed-fallback path.
- Subscriber tier defaults to `paid` (overridable via `ABIGAIL_SUBSCRIBER_TIER`);
  per-request tier resolution from an authenticated principal is future work.
- `/api/agents/dispatch` is intentionally **not** wired to the router in MR-05;
  MR-05 scopes only the `/api/chat` normal-chat path.
- Mode 2 live dispatch has been validated in tests with stubbed adapters only.
  Live provider smoke tests require explicit operator approval and were not run
  here (no live provider calls occur in pytest).

## Buyer-Facing Claim Boundary

- **Mode 0** is the current, proven single-backend behavior.
- **Mode 1** proves routing *decisions* without live spend or provider effect.
- **Mode 2** enables live governed multi-provider router dispatch through MR-04.
- Approval and cost gates must clear before any live provider dispatch.
- The command bus and `PUBLIC_ASSIST` paths never use the model router.
- **Buyer-facing claims about dynamic multi-provider routing are valid only when
  mode 2 has been tested successfully against live providers** under explicit
  operator approval. Until that live validation is performed, the defensible claim
  is: "governed router integrated, dry-run provable (mode 1), live dispatch
  available behind an operator flag (mode 2)."
