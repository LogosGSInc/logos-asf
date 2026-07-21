# SEC-02: Immediate Runtime Hardening

**Document ID:** SEC02_IMMEDIATE_RUNTIME_HARDENING
**Version:** 1.0
**Date:** 2026-07-04
**Status:** ACTIVE
**Classification:** Internal Governance Doctrine
**Authority:** LOGOS Governance Systems Inc.

---

> SEC-02 patches runtime survivability before MM-03.

## Purpose

SEC-02 patches the immediate SEC-01 runtime exposure findings so Abigail's local
runtime is survivable by default: localhost bind by default, fail-closed admin auth, no
world-readable plaintext secret in the repo tree, and a deterministic local Cost Governor
gate before paid Groq inference. MM-02 shadow orchestration and the governed command bus
are preserved unchanged in behavior.

## SEC-01 Findings Addressed

| SEC-01 finding | Severity | Fix |
|---|---|---|
| SEC01-L3-1 all-interface bind | HIGH | default bind `127.0.0.1`; non-local requires explicit opt-in |
| SEC01-L1-1 admin auth fails open | HIGH | `require_admin_token()` fails closed (503 if unconfigured, 401 otherwise) |
| SEC01-L3-2 world-readable key in repo | HIGH | repo-local `.abigail.env` set to mode 600; gitignored & untracked |
| SEC01-L7-1 no Cost Governor | CRITICAL | `check_chat_cost_budget()` gate before provider dispatch |
| SEC01-L4-1 unauth uncapped `/api/chat` | HIGH | cost gate caps turns/tokens ahead of inference (auth on chat tracked in backlog) |

## Default Localhost Bind

`resolve_bind_host()` returns `127.0.0.1` by default. `run_web()` calls it, and the
startup banner prints the **actual** resolved bind host and whether it is localhost-only.
`flask_app.run(host=...)` now uses the resolved host instead of a hard-coded `0.0.0.0`.

## Explicit Non-Local Bind Policy

A non-local bind is only honored when **both** are set:
`ABIGAIL_BIND_HOST=<addr>` **and** `ABIGAIL_ALLOW_NONLOCAL_BIND=1`. Any non-local host
requested without the safety flag is refused, logged (`BIND_NONLOCAL_REFUSED`, length
only — no address value), and downgraded to `127.0.0.1`.

## Admin Auth Fail-Closed Policy

`require_admin_token(req)` returns `(ok, status, error)`:
- **No server-side `ABIGAIL_ADMIN_TOKEN`** → `(False, 503, ...)` — a server
  misconfiguration must never serve a privileged action.
- **Missing or incorrect client token** → `(False, 401, ...)`.
- **Correct token** → `(True, 200, None)`.

The error text never reveals the token, its length, or how close a guess was. All
privileged routes now use it: `/api/agents/spawn`, `/api/agents/<dept>/kill`,
`/api/agents/<dept>/restart`, `/api/audit/tail` (and `/api/audit-tail`). The prior
`if admin_token and token != admin_token` fail-open checks are removed.

> **Operational coupling (SH-01) — RESOLVED (2026-07-04):** `~/.abigail.env` is the
> authoritative secret source (mode 600, with distinct admin len-43 and demo len-32
> tokens and the Groq key). `~/.bashrc` no longer exports `GROQ_API_KEY`,
> `ABIGAIL_ADMIN_TOKEN`, or `ABIGAIL_DEMO_TOKEN` (verified in a clean login shell), so
> fail-closed auth now relies on a single authoritative token. Only an empty
> `XAI_API_KEY=""` template placeholder (unused by Abigail) remains in `~/.bashrc`.

## Secret File Policy

- Canonical runtime secrets live in `~/.abigail.env` (mode 600).
- The repo-local `~/logos-asf-tr06z/.abigail.env` was **left in place but chmod'd 600**
  (was 644). It is in `.gitignore` and **not tracked**. It was not deleted — removal
  requires a timestamped backup and operator approval (recommended as backlog, since the
  app reads `~/.abigail.env`, not the repo copy).
- No secret values were printed at any point.

## Cost Governor Pre-Inference Gate

`check_chat_cost_budget(message, mode, session)` is a deterministic, local,
fail-closed gate that runs in `/api/chat` **before** `process_message()` (the provider
dispatch path). It performs no external billing calls. Environment configuration:

| Env var | Default | Meaning |
|---|---|---|
| `ABIGAIL_COST_GOVERNOR_ENABLED` | `1` | master enable |
| `ABIGAIL_MAX_CHAT_TURNS` | `1000` | per-session turn ceiling |
| `ABIGAIL_MAX_ESTIMATED_TOKENS` | `8000` | per-request estimated-token ceiling (~4 chars/token) |

When enabled, a zero/empty budget fails closed (`block_zero_budget`); exhausted turns or
oversized requests block before any paid call. On block, the route returns
`mode:"COST_BLOCKED"` and never calls `process_message`. On allow, audit-safe cost
metadata (counts and message length only — no raw prompt) is attached additively under a
`cost` key. `TODO:` integrate durable cross-process spend accounting in a later sprint;
the current guard is per-process and deterministic.

## MM-02 Preservation

- Normal chat that passes the cost/security gates still includes the additive MM-02
  `orchestration` metadata (`orchestration_mode: "shadow"`).
- The command bus still runs **first**; exact operator commands return before the cost
  gate and before orchestration — so they perform no inference, attach no `orchestration`
  block, and attach no `cost` block.
- No raw prompt appears in `orchestration` or `cost` metadata.
- Existing command-bus and MM-02 runtime-bridge tests pass unchanged.

## Tests

New `tests/test_runtime_security_hardening.py` (20 tests): bind default/refuse/allow;
admin fail-closed at both helper and route layers (503/401/accept, no token leakage);
cost gate unit decisions (zero/allow/oversized/exhausted); cost gate blocks before
`process_message` (asserted via monkeypatch — provider never called); normal chat keeps
orchestration + cost metadata; command bus bypasses inference and orchestration;
repo-local `.abigail.env` is gitignored. No provider or network calls in any test.

- New file suite: **20 passed**
- Command bus + orchestration bridge: **79 passed**
- Full suite: **1427 passed**

## Operational Validation

Runtime validation against the live server is **pending operator approval to restart**
(the currently-running process predates this patch). On approval, restart from
`~/logos-asf-tr06z` with the prior launch command and confirm: banner shows
`127.0.0.1`; `/api/status` healthy; normal `/api/chat` returns `ok:true` + orchestration
+ `cost.decision:"allow"`; `status` returns `OPERATOR_CMD` with no orchestration/cost
block. Zero-budget behavior is proven by unit tests, not by live paid inference.

## Remaining Backlog

- SH-01 is complete (canonical source `~/.abigail.env`; `.bashrc` managed exports gone).
  Optional cleanup: remove the empty `XAI_API_KEY=""` placeholder from `~/.bashrc`.
- Optionally delete the repo-local `.abigail.env` (with backup + approval).
- Add auth to `/api/chat` when bound non-locally; gate topology routes (SEC01-L4-2).
- Compose `127.0.0.1:` prefix; non-root container `USER`; pin `pyyaml`; Python SBOM.
- Durable cross-process cost accounting; verify `/api/agents/dispatch` auth (SEC01-L4-4).

---

*This document cites only internal LOGOS/GovSec/HAAP evidence and the in-repo code. No
external citations.*
