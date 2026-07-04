# SEC-01: Seven-Layer Abigail Security Baseline

**Document ID:** SEC01_SEVEN_LAYER_SECURITY_BASELINE
**Version:** 1.0
**Date:** 2026-07-04
**Status:** ACTIVE — inspection/report only
**Classification:** Internal Governance Doctrine
**Authority:** LOGOS Governance Systems Inc.

---

## Executive Summary

This is a read-only, seven-layer security baseline of Abigail CP-00 taken immediately
after MM-02 (shadow runtime bridge). No code was changed. The runtime, repo, and sealed
baseline were inventoried; findings are mapped to the seven layers and to common
early-stage / startup breach-weakness categories.

**Headline posture:** The governance *core* is strong — default-deny training, no
raw-prompt storage in orchestration, an active kill switch, a governed command bus, and
the GovSec V2.1 CMD_STYLE_INJECTION doctrine are all in place and 1407 tests pass. The
material risk is **not** in the AI-governance layer; it is in **infrastructure and
access posture (L3/L4)**: the server binds all network interfaces, admin auth fails
open, the primary inference route is unauthenticated with no cost ceiling, and a
world-readable copy of the real Groq key sits in the repo working directory.

*Status (2026-07-04): the L3/L4/L7 access findings were remediated in SEC-02, and SH-01
secret hygiene is resolved (`~/.abigail.env` canonical at mode 600; `~/.bashrc` no longer
exports managed secrets). This report is retained as the point-in-time baseline; see
inline **Status** notes on individual findings.*

- **Critical:** 1
- **High:** 4
- **Medium:** 5
- **Low:** 3

**Top immediate action:** bind to `127.0.0.1` (or gate `0.0.0.0` behind explicit,
authenticated opt-in) and make admin auth fail *closed*, before any cloud exposure.

---

## Scope

- In scope: `~/logos-asf-tr06z` working tree, running server on `127.0.0.1:7070`
  (bound `0.0.0.0`), docker/compose config, requirements, orchestration + command-bus +
  training modules, shell/env secret posture as it affects runtime auth.
- Out of scope / untouched: `~/Abigailv1`, `~/Abigailv1_EVIDENCE_20260703`.
- Method: static inspection (`git`, `grep`, `find`, file reads), one full test run, one
  `/api/status` read. No external network calls, no attacks, no provider calls from
  tests, no secrets printed.

---

## Repo and Runtime Checkpoint

| Field | Value |
|---|---|
| Active HEAD | `6c9e6f3` feat(orchestration): add shadow runtime bridge |
| Branch | `sprint/full-doctrine-mode` (ahead of origin by 46; **not pushed**) |
| Working tree | clean |
| MM-02 status | complete (code + tests + docs + live acceptance) |
| Sealed `~/Abigailv1` | `5cdfee1`, **clean / untouched** |
| Server | healthy — backend `groq`, sandbox `docker+venv`, kill_switch inactive, version `1.2.0-sprint6-docker-sandbox`, turns 3 |
| Test suite | 1407 passed |

---

## Seven-Layer Findings

Finding fields: `id | layer | severity | component | evidence | risk | recommended_action | patch_now_or_backlog | owner`.

### L1 — Human identity & access
*(startup weakness: low cybersecurity awareness / no dedicated expertise)*

- **SEC01-L1-1 | HIGH | admin auth fail-open | `abigail_hardened_enhanced.py:874,921,981`**
  Evidence: guard pattern is `if admin_token and token != admin_token: reject` and
  `_admin_ok()` returns `(not admin_token) or (token == admin_token)`. Risk: if
  `ABIGAIL_ADMIN_TOKEN` is empty/unset, **every** privileged route (agent spawn,
  department kill/restart, audit-tail) is served unauthenticated. Action: make auth
  fail *closed* — refuse to serve privileged routes when no admin token is configured.
  **patch_now** | owner: Eng/Sec.
  *Status (2026-07-04): RESOLVED by SEC-02* — `require_admin_token()` now fails closed
  (503 when unconfigured, 401 otherwise). SH-01 is resolved: `~/.abigail.env` is the
  authoritative source (mode 600, distinct admin/demo tokens) and `~/.bashrc` no longer
  exports the managed secrets.

- **SEC01-L1-2 | MEDIUM | operator-command local gate | launch env `ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS`**
  Evidence: launch relies on this env flag, but it is not read in
  `abigail_hardened_enhanced.py` (grep returned no hits there — enforcement, if any,
  lives in `command_bus.py`). Risk: the operator-command trust boundary is not obviously
  enforced at the HTTP layer. Action: confirm where the flag is consumed and document the
  trust boundary. **backlog** | owner: Eng

### L2 — Dependency & supply chain
*(startup weakness: weak secure-dev practices / supply-chain exposure)*

- **SEC01-L2-1 | MEDIUM | unpinned dependency | `requirements.txt`, `abigail/requirements.txt`**
  Evidence: 6/7 lines pinned with `==`; `pyyaml` unpinned. Risk: non-reproducible build,
  drift, supply-chain surface. Action: pin `pyyaml==<version>`; add a lockfile/hash.
  **backlog** | owner: Eng

- **SEC01-L2-2 | MEDIUM | DEP.KEYSTONE evidence coverage | repo-wide**
  Evidence: Rust `governance-spine` has `Cargo.lock`; the Python side has no SBOM/hash
  manifest surfaced. Risk: dependency provenance for the Python runtime is unverified.
  Action: generate and seal a Python SBOM under the DEP.KEYSTONE evidence chain.
  **backlog** | owner: Sec

### L3 — Cloud infra & configuration
*(startup weakness: poor cloud/infra/config management)*

- **SEC01-L3-1 | HIGH | all-interface bind | `abigail_hardened_enhanced.py:997`**
  Evidence: `flask_app.run(host="0.0.0.0",port=port,debug=False,use_reloader=False)` while
  the startup banner (line 991) and sprint docs claim `127.0.0.1`. Risk: the API is
  reachable on every interface (on WSL: Windows host + potentially LAN via eth0), not
  localhost-only as assumed throughout MM-01/MM-02. Action: default-bind `127.0.0.1`;
  require an explicit, documented, auth-gated flag to bind `0.0.0.0`. **patch_now** |
  owner: Eng/Sec

- **SEC01-L3-2 | HIGH | world-readable real key in repo dir | `~/logos-asf-tr06z/.abigail.env` (mode 644)**
  Evidence: repo-root `.abigail.env` is `-rw-r--r--` and contains one real `gsk_` key
  line (`~/.abigail.env` is correctly `600`). It is gitignored and **not tracked** (good),
  but 644 means any local user can read the live key. Risk: local secret disclosure; key
  compromise. Action: `chmod 600`, or delete the repo-dir copy (the app reads
  `~/.abigail.env`, not this one). **patch_now** | owner: Eng/Sec

- **SEC01-L3-3 | MEDIUM | compose publishes on all host interfaces | `docker-compose.yml:40`**
  Evidence: `- "7070:7070"` (no `127.0.0.1:` prefix). Risk: container deploy exposes 7070
  on all host interfaces. Action: `- "127.0.0.1:7070:7070"` unless public exposure is
  intended and auth-gated. **backlog** | owner: Eng

- **SEC01-L3-4 | MEDIUM | container runs as root | `abigail/Dockerfile`**
  Evidence: `FROM python:3.11-slim` with no `USER` directive. Risk: root in container
  widens blast radius on escape. Action: add a non-root `USER`. **backlog** | owner: Eng

### L4 — App / API / runtime security
*(startup weakness: weak application/API controls)*

- **SEC01-L4-1 | HIGH | unauthenticated inference + no cost ceiling | `/api/chat` (`:780`)**
  Evidence: `/api/chat` requires no auth; combined with L3-1 (all-interface bind) and
  L7-1 (no Cost Governor), any network client can drive unbounded Groq inference. Risk:
  financial DoS / token exhaustion, network-reachable. Action: require a token on
  `/api/chat` when bound non-locally; add a per-session/global spend ceiling. **patch_now**
  | owner: Eng/Sec

- **SEC01-L4-2 | MEDIUM | topology-leaking unauth routes | `/api/agents`, `/api/agents/departments`, `/api/agents/<dept>/status`, `/api/agents/lifecycle`**
  Evidence: these routes have no `_admin_ok()` / token check. Risk: internal
  department/agent topology and lifecycle state disclosed to unauthenticated callers
  (amplified by L3-1). Action: gate behind admin token or bind localhost-only.
  **backlog** | owner: Eng

- **SEC01-L4-3 | MEDIUM | internal error text returned to clients | `:528, :548` (and `:360,:387,:840` governed)**
  Evidence: agent-spawn (`output: str(e)`) and sentinel-inspect (`error: str(e)`) return
  raw exception text; kill/blocked/HAAP paths return controlled governance messages.
  `debug=False` confirmed; no `traceback`/`format_exc` leakage. Risk: internal detail
  (paths, exception types) leaked on error. Action: return generic client errors, log
  detail server-side only. **backlog** | owner: Eng

- **SEC01-L4-4 | MEDIUM | `/api/agents/dispatch` auth boundary unverified | `:823`**
  Evidence: dispatch applies HAAP gating (`:839-840`) but no `_admin_ok()` was observed
  on the route; spawn (`:868`) *is* admin-gated. Risk: possible unauthenticated dispatch
  path. Action: verify and, if unauthenticated, admin-gate it. **patch_now (verify)** |
  owner: Sec

### L5 — Data privacy & memory boundaries
*(startup weakness: inadequate protection of sensitive data)*

- **SEC01-L5-1 | LOW | governed-state retains redacted user preview | `orchestration/runtime_bridge.py:59-64,131`**
  Evidence: `safe_task_summary` stores up to 120 chars of the user message with
  secret-pattern redaction and truncation (no model inference). Orchestration otherwise
  stores only SHA-256 `input_hash` (`schemas.py:90`, `routing_manifest.py:9`). Risk: if
  `SingleGovernedState` is ever persisted/exported, a bounded redacted preview of user
  content travels with it. Action: confirm state is never persisted with the preview, or
  hash-only it before persistence. **backlog** | owner: Eng
- **NOT A FINDING (strength):** training pipeline is default-deny — `dataset_builder.py`
  enforces `training_allowed is not False` as a hard invariant and never sets it true
  (`:179-188,:216,:485`). Store-1 promotion is gated.

### L6 — LLM / agentic / prompt-injection security
*(startup weakness: agentic prompt injection / tool hijack / governance bypass)*

- **SEC01-L6-1 | MEDIUM | duplicated CMD_STYLE_INJECTION pattern set (drift risk) | `runtime_bridge.py:27-36` vs `abigail_hardened_enhanced.py:244-252`**
  Evidence: the bridge carries a *local copy* of the injection regex "mirroring
  SENT-CMD-001–006" (6 of the 10 doctrine patterns), duplicating the main file's set.
  Risk: the two copies can diverge; the bridge would under-detect if the canonical set is
  extended. Action: extract the pattern set to one shared module consumed by both.
  **backlog** | owner: Eng/Sec
- **NOT A FINDING (strength):** GovSec V2.1 doctrine, command bus (`command_bus.py`),
  SENT-CMD registry, routing manifests, signed handoff packets, and `SingleGovernedState`
  are present; MM-02 executes **no** workers and escalates risk to `high` on a command-
  style signal.

### L7 — Monitoring, incident response & cost survival
*(startup weakness: no monitoring / IR / financial guardrails)*

- **SEC01-L7-1 | CRITICAL | no Cost Governor on the inference path | repo-wide (absent)**
  Evidence: no cost/budget/wallet/spend-limit module exists (`find` + grep returned
  none); the manifest `budget` (max_steps, max_tokens_estimate) is **shadow metadata
  only**, not enforced on the actual Groq call. Combined with L4-1 (unauth `/api/chat`)
  and L3-1 (all-interface bind), there is **no financial guardrail** between a network
  caller and paid inference. Risk: uncontrolled/adversarial spend, no ceiling, no
  circuit-breaker. Action: add an enforced per-session and global token/spend ceiling in
  the inference path with a trip-to-kill-switch on breach. **patch_now** | owner: Eng/Sec

- **SEC01-L7-2 | LOW | audit-log confidentiality depends on file perms + admin token | `log_event` → `~/.abigail_audit.jsonl`; `/api/audit/tail`**
  Evidence: audit tail is admin-gated (fail-open per L1-1); on-disk log perms rely on
  `_secure_touch`. Risk: audit contents readable if token unset or perms loose. Action:
  verify log file mode is 600; fail-close the tail route. **backlog** | owner: Eng
- **NOT A FINDING (strength):** kill switch present and checked in `process_message`;
  red-team coverage present (`redteam/`, BD1A/TAX2, `redteam_live_results.jsonl`);
  structured audit logging via `log_event`.

---

## Mapped Startup Weaknesses

| Startup breach category | Layer(s) | Worst finding here |
|---|---|---|
| Low cyber awareness / no dedicated expertise | L1 | fail-open admin auth (SEC01-L1-1) |
| Weak secure-dev / supply chain | L2 | unpinned dep + no Python SBOM |
| Poor cloud/infra/config | L3 | all-interface bind + world-readable key |
| Weak app/API controls | L4 | unauth inference route |
| Inadequate sensitive-data protection | L5 | (low) redacted preview in state |
| Agentic prompt injection / bypass | L6 | pattern-set drift (low-med) |
| No monitoring / IR / financial guardrails | L7 | **no Cost Governor (critical)** |

---

## Critical Findings
- **SEC01-L7-1** — No enforced Cost Governor between an unauthenticated, network-reachable
  `/api/chat` and paid Groq inference.

## High Findings
- **SEC01-L1-1** — Admin auth fails open when the token is unset. *(RESOLVED in SEC-02; SH-01 secret source canonicalized.)*
- **SEC01-L3-1** — Flask binds `0.0.0.0` despite localhost-only assumptions.
- **SEC01-L3-2** — World-readable (644) real `gsk_` key in the repo working directory.
- **SEC01-L4-1** — Unauthenticated `/api/chat` inference, network-reachable.

## Medium Findings
- SEC01-L1-2 (operator-command flag boundary), SEC01-L2-1 (pyyaml unpinned),
  SEC01-L2-2 (Python SBOM/DEP.KEYSTONE), SEC01-L3-3 (compose bind),
  SEC01-L3-4 (root container), SEC01-L4-2 (topology routes),
  SEC01-L4-3 (error text), SEC01-L4-4 (dispatch auth — verify), SEC01-L6-1 (pattern drift).

## Low Findings
- SEC01-L5-1 (governed-state preview), SEC01-L7-2 (audit confidentiality),
  and naming/label cleanups noted inline.

## False Positives / Not Applicable
- Orchestration "raw prompt" storage: **not applicable** — only SHA-256 hashes stored.
- Training data mutation without gate: **not applicable** — default-deny invariant enforced.
- `.abigail.env` committed to git: **false positive** — gitignored and not tracked.
- Debug mode leakage: **not applicable** — `debug=False`, no traceback in responses.

---

## Immediate Fix Queue (proposed SEC-02, requires approval)
1. Bind `127.0.0.1` by default; `0.0.0.0` only behind explicit auth-gated flag (L3-1).
2. Make admin auth **fail closed** when no token is configured (L1-1).
3. `chmod 600` (or remove) the repo-dir `.abigail.env` (L3-2).
4. Add an enforced Cost Governor / spend ceiling on the inference path (L7-1, L4-1).
5. Verify `/api/agents/dispatch` auth; gate `/api/chat` when non-local (L4-4, L4-1).

## Backlog
- Pin `pyyaml`; Python SBOM under DEP.KEYSTONE (L2).
- `127.0.0.1:` prefix in compose; non-root container `USER` (L3-3/4).
- Generic client errors + server-side detail (L4-3).
- Gate topology routes (L4-2); shared injection pattern module (L6-1).
- Confirm audit-log file mode + fail-close tail (L7-2).

## Do Not Fix Yet
- **SH-01 — RESOLVED (2026-07-04).** `~/.abigail.env` is the authoritative secret source
  (mode 600, with distinct `ABIGAIL_ADMIN_TOKEN` len 43 and `ABIGAIL_DEMO_TOKEN` len 32,
  plus `GROQ_API_KEY`). `~/.bashrc` no longer exports `GROQ_API_KEY`,
  `ABIGAIL_ADMIN_TOKEN`, or `ABIGAIL_DEMO_TOKEN` (verified in a clean login shell). One
  empty `XAI_API_KEY=""` template placeholder remains in `~/.bashrc` (unused by Abigail).
- No changes to `~/Abigailv1` or the evidence archive.

---

## Evidence Commands
```
git status --short --branch ; git log -8 --oneline
git ls-files | grep -E '\.env$'            # -> .abigail.env NOT tracked
find . -maxdepth 4 -type f \( -name '*.env' -o -iname '*secret*' -o -iname '*token*' \)
grep -n 'flask_app.run' abigail/abigail_hardened_enhanced.py   # -> host="0.0.0.0" :997
grep -nE '@flask_app.route' abigail/abigail_hardened_enhanced.py
grep -n 'admin_token' abigail/abigail_hardened_enhanced.py     # fail-open pattern
find abigail -iname '*cost*' -o -iname '*governor*'            # -> none
ls -l .abigail.env                                             # -> mode 644, real gsk_ key
python -m pytest -q                                            # -> 1407 passed
curl -s http://127.0.0.1:7070/api/status
```

## Test Results
- Full suite: **1407 passed** (no provider calls; server healthy throughout).

## Sealed Abigail V1 Integrity Confirmation
- `~/Abigailv1` at `5cdfee1`, `git status` clean — **not modified**.
- `~/Abigailv1_EVIDENCE_20260703` — not touched.
- No secrets printed in this inspection (values reported only as length/fingerprint/masked).
- No external network calls. No push.
