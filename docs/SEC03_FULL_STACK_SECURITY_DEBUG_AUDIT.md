# SEC-03 — Full-Stack Abigail Security, Debug & AWS MVP Readiness Audit

**Mode:** MANUAL_APPROVAL_ONLY · audit-first, patch-second. **No code was changed. Nothing was committed. Nothing was pushed.**

---

## Executive Summary

The Abigail governance core is, in most respects, well-built: the `/api/chat`
governance ordering holds, provider error paths are sanitized, secrets are not
committed, the swarm model is genuinely dormant-by-default and well-tested, and
the full test suite is green (**1544 passed, 0 failed**).

However, the audit found **two Critical** and **four High** issues that are
**hard blockers for AWS MVP exposure**, the most serious of which is confirmed
exploitable live against the running container:

- **EP-01 (CRITICAL, confirmed live):** the static-file route allows
  unauthenticated path traversal → arbitrary file read. This lets any caller of
  `:7070` read `~/.abigail.env` (all four provider keys **and** the admin/demo
  tokens) and the audit log — which collapses the entire admin-token security
  model.
- **DOCK-01 (CRITICAL, confirmed):** the Sentinel governance control plane is
  published on `0.0.0.0:9091` with no authentication on its inspect/audit/session
  routes.

**AWS MVP recommendation: NO-GO** until the Critical and High findings are
remediated and re-tested. None of these were introduced by MR-05; they are
pre-existing stack issues surfaced by this first full-stack audit.

**Doctrine check ("Before AWS, Abigail must survive herself"):** not yet. Two
routes (static file read; Sentinel control plane) do not "know their authority,"
and one buyer-facing surface (`dashboard.html`) makes a "Live" claim that no test
backs.

---

## Audit Scope

Full stack at the worktree HEAD below: Abigail CP-00 runtime, Sentinel/OverWatch
(Rust + Python shims), command bus (CB-01), SEC-02 runtime hardening, MM-03
approval gate, UX-01 public calibration, AG-01 governed local swarm, MR-04 live
provider dispatch, MR-05 router/chatpath. Phases 0–12 per the SEC-03 brief.
Read-only inspection + safe local probes only. No live paid provider inference
was triggered; no external network scans; no AWS resources touched.

## Current Commit / Runtime State

- **Repo:** `~/logos-asf-tr06z` (audited in isolated worktree
  `.claude/worktrees/mr05-router-chatpath`).
- **HEAD:** `b4b6e5543e3e3f919c37306633689adca749b625`
  = `sprint/full-doctrine-mode` (`a45f6c3`) **+ the local MR-05 commit**
  (`b4b6e55`, not yet merged to the sprint branch, not pushed).
- **Working tree:** clean; no untracked runtime/generated artifacts.
- **Sealed baseline:** `~/Abigailv1` at `5cdfee1` — verified present and
  **untouched**. Evidence archive `~/Abigailv1_EVIDENCE_20260703` — untouched.
- **Containers:** `asf-abby` Up healthy `127.0.0.1:7070` (localhost-only ✓);
  `asf-sentinel` Up healthy `0.0.0.0:9091→8080` (**all interfaces — see DOCK-01**).
- `~/.abigail.env`: mode `600`, owner `legacy`, not a symlink, ro-mounted into
  the container, gitignored.

## Component Map

- **Entrypoint:** `abigail/abigail_hardened_enhanced.py::main()` → `run_web()` →
  `build_web_app()` → `flask_app.run()`; Docker `CMD python … --web --port=7070`.
- **Public (no auth):** `GET /`, `GET /<path:filename>` (static), `/api/status`,
  `POST /api/chat`, `/api/sentinel-health`, `/api/agents/departments`,
  `/api/agents`, `/api/agents/<dept>/status`, `/api/agents/lifecycle`.
- **Admin (`require_admin_token`, fail-closed):** `POST /api/agents/spawn`,
  `POST /api/agents/<dept>/kill`, `.../restart`, `GET /api/audit/tail`.
- **Ungated write route:** `POST /api/agents/dispatch` (HAAP only — EP-02).
- **Governance chain (`process_message`):** kill-switch → grounded → A2A relay →
  Sentinel OverWatch → HAAP → MM-03 approval → UX-01 public → DRS → tacit → MR-01
  route card (shadow) → MR-02 provider dry-run → **MR-05 `_router_dispatch`** →
  PUBLIC disclosure clamp. Cost gate (SEC-02) runs in `api_chat` before
  `process_message`.
- **Providers:** `BACKEND_DISPATCH = {groq, anthropic, perplexity, ollama,
  openai, xai}`; MR-04 dispatcher + `provider_capabilities` + `live_adapters`;
  MR-05 modes 0/1/2.
- **Swarm:** `abigail/swarm/{registry,local_executor,job_spec,merge}.py` (dormant
  by default; **not shipped in the abby image — DOCK-03**).
- **Audit:** `log_event` → `~/.abigail_audit.jsonl` (scrubbed); admin viewer
  `/api/audit/tail`.
- **Boundaries:** mode 0 single-backend (default) · mode 1 dry-run (no MR-04 live
  dispatch) · mode 2 governed live · MR-02 adapters dry-run-only. All optional
  imports fail-soft to no-ops.

---

## Findings by Section

Finding format: **ID | Severity | Component | Evidence | Risk | Fix | Safe-to-patch-now | Test-needed.**

### Secret Hygiene Findings

- **PASS (verified):** only `.abigail.env.example` tracked (placeholder values,
  0 real-key regex hits); `.gitignore` covers `.abigail.env`/`.env`/`*.jsonl`;
  `_safe_error` returns exception *type name* only; `Authorization: Bearer` headers
  never logged/returned; `log_event` scrubs via `_SECRET_RE`; `key_present()`
  exposes presence only; `_require_env_key` rejects empty/`YOUR_*`/`PLACEHOLDER`.
- **SEC-01 | Low | env loader precedence** | `abigail_hardened_enhanced.py:171`
  (`if k and k not in os.environ`) | An already-present-but-**empty** env var is
  not overridden by the real value in `.abigail.env`, so an empty shell/compose
  var can shadow a real key. | Treat empty existing env values as unset before
  applying the file value. | Yes | load-precedence unit test.
- **SEC-02 | Low | CORS reflection** | `abigail_hardened_enhanced.py` CORS block
  (`*.app.github.dev` regex + manual `Origin` reflection echoing `Authorization`
  in `Allow-Headers`) | Any `*.app.github.dev` subdomain is trusted. Bounded: not
  literal `*`, no `Allow-Credentials`. | Pin to specific Codespace hosts; drop
  wildcard outside Codespaces. | Yes | origin-allow browser check.

### Endpoint Findings

- **EP-01 | CRITICAL | static file route — unauthenticated path traversal /
  arbitrary file read** | `abigail_hardened_enhanced.py:1153-1163` —
  `p = os.path.join(STATIC_DIR, filename); open(p,"rb").read()` with no
  normalization; `<path:filename>` permits `..`. **Confirmed live:**
  `GET /../../../../etc/hostname` → HTTP 200, content returned (verified twice,
  independently). | Any unauthenticated caller of `:7070` can read any file the
  process can access — including `~/.abigail.env` (provider keys + admin/demo
  tokens) and `~/.abigail_audit.jsonl`. Fully defeats the admin-token model
  (token is exfiltratable). | Use `flask.send_from_directory`, or `os.path.realpath`
  + `os.path.commonpath` containment check; reject `..`/absolute/encoded traversal.
  | **Yes** | traversal regression test incl. `%2e%2e` encoded variants.
- **EP-02 | High | `/api/agents/dispatch` unauth paid inference + governance
  bypass** | route has no `require_admin_token`; only `haap_gate` guards it, then
  `BACKEND_DISPATCH.get(...)()` runs. **Confirmed:** unauth POST reaches app
  logic (HTTP 400 on empty body). | Unauthenticated wallet-DoS; bypasses Sentinel,
  SEC-02 cost gate, MM-03, A2A block, PUBLIC clamp with an agent-selected system
  prompt. | Require admin/demo token **and** route through the same
  cost+Sentinel+approval ordering as `api_chat`. | Yes | auth + ordering test.
- **EP-03 | Medium | unauth topology disclosure** | `/api/agents/departments`,
  `/api/agents`, `/api/agents/<dept>/status`, `/api/agents/lifecycle` return dept
  ids, agency levels, agent registry, and lifecycle state with no auth. | Internal
  org/agent topology enumerable by anyone — the PUBLIC clamp is meant to protect
  exactly this. | Require token or reduce to non-sensitive fields. | Yes |
  recommended.
- **EP-04 | Low | `/api/status` exposes backend + kill-switch state** | returns
  `backend`, `kill_switch`. | Reveals provider choice and a security-control state
  publicly (by-design via command-bus whitelist, but arguably internal). | Gate
  behind token; keep only liveness/version public. | Yes | No.
- **EP-05 | Low | `/api/sentinel-health` exposes chain counters** |
  `chain_length`, `audit_entries`. | Minor recon aid. | Reduce to `{ok, service}`
  for unauth callers. | Yes | No.

### Governance Ordering Findings

- **PASS (proven, `/api/chat`):** command bus → cost gate → hard-blocks
  (A2A/Sentinel/HAAP) → MM-03 approval → UX-01 public → DRS/dry-runs → MR-05
  dispatch → audit/clamp. Points 1–9 of the SEC-03 ordering hold on the normal
  chat path; MR-05 mode 2 re-checks cost and (via MR-04) approval+cost before any
  provider call; response metadata carries only governance codes.
- **GOV-01 | High | MM-03 approval gate fails OPEN if the orchestration bridge is
  unavailable** | `abigail_hardened_enhanced.py:88-97` — on `ImportError`,
  `_approval_gate_blocks` is stubbed `return False`; `_build_shadow_ctx` is
  `except: return None`; `_approval_meta` only set when `_ORCHESTRATION_BRIDGE_OK`.
  Compounded by `_router_dispatch` hardcoding `approval_state="cleared"`. | If the
  optional `orchestration` package fails to import or throws, the human-approval
  gate silently disappears while paid inference continues. | Fail **closed**:
  treat "no approval metadata reachable" as approval-required (or block), never as
  approved. | Needs care (behavior change) | simulate bridge ImportError/exception.
- **GOV-02 | Medium | `try_grounded_answer` runs before Sentinel/HAAP and leaks
  the audit-log path, bypassing the PUBLIC clamp** | called at `~:646`, before A2A
  /Sentinel/HAAP/approval/public-intent and before the clamp; returns
  `"…audit log path in this build is: {LOG_FILE}"` though "audit log" is in
  `PUBLIC_FORBIDDEN_TERMS`. | Discloses internal filesystem path to the public
  path the clamp protects; pre-Sentinel early-return ordering violation. | Move
  grounded-info after Sentinel/HAAP + public-intent and/or run it through the
  clamp; never emit filesystem paths publicly. | Yes | grounded-path clamp test.

### Provider / Router Findings

- **PASS (verified):** groq/anthropic/openai/xai live-wired; perplexity/ollama
  honest when key/local missing; error paths sanitized (RTR-02/03); mode-1
  dry-run cannot reach a router-selected live provider (RTR-04); missing-key →
  governed `_fallback`, unavailable → governed metadata, never crashes (RTR-06);
  MR-04/MR-05 gate ordering sound (approval→cost→router→execute, with
  defense-in-depth re-checks).
- **RTR-01 | Medium | hardcoded model IDs (no env override)** |
  `call_groq(model="meta-llama/llama-4-scout-17b-16e-instruct")`, perplexity
  `"model":"sonar"`, `call_ollama(model="llama3")` have no `ABIGAIL_*_MODEL`
  override, unlike anthropic/openai/xai. | A deprecated groq/perplexity/ollama id
  can't be rotated without a code change + redeploy. | Add `ABIGAIL_GROQ_MODEL`
  /`ABIGAIL_PERPLEXITY_MODEL`/`ABIGAIL_OLLAMA_MODEL` defaults mirroring the others.
  | Yes | per-provider env-override unit test.
- **RTR-05 | Low | `approval_state="cleared"` hardcoded in `_router_dispatch`** |
  the router trusts its single upstream caller (post-MM-03). Safe today; brittle
  if ever called from another path. | Pass the real approval outcome in, or assert
  the MM-03 predicate at entry. | Yes | non-cleared state forces fallback test.
- **RTR-07 | Low | sensitive-tier fallback blind spot** | `dispatcher.py:22`
  `_SAFE_FALLBACK_ORDER=["groq","current_backend","local"]` gated by
  `p in dispatch_table`; `current_backend`/`local` are never dispatch_table keys,
  so fallback resolves to `groq` (paid cloud) first, and `sensitive_governed` tier
  gets `None`. | A privacy-preserving local fallback is never selected for
  sensitive users. | Treat `current_backend`/`local` as always-live in
  `_pick_fallback`; force local for sensitive/private routes. | Yes |
  sensitive-tier fallback test.
- **RTR-09 | Low | admin token compared with `!=` (not constant-time)** |
  `abigail_hardened_enhanced.py:~205`. | Minor timing side-channel on admin auth.
  | Use `hmac.compare_digest`. | Yes | admin auth 401/200 test.

### Swarm / Agent Findings

- **PASS (verified & tested):** authored ≠ autonomous; dormant cannot execute;
  workers require signed manifest + scoped handoff packet; no transcript sprawl;
  cannot self-route/self-approve/create children/write outside workspace; kill
  switch external to worker; `runtime/` gitignored and untracked; docs disclaim
  autonomy.
- **SWARM-01 | Medium | activation not bound to the `authored` flag** |
  `registry.py:128-135` `activate()` auto-creates a synthetic record for any
  unknown id and enables it; `can_execute()` checks activation state only, never
  `authored`. | An operator can activate an arbitrary agent id into bounded
  execution — governance depends on discipline, not enforcement. | Gate
  `activate()`/`can_execute()` on `authored is True` (or explicit allow-list). |
  Yes | activating a non-authored id must refuse.
- **SWARM-02 | Low (disclosed) | handoff packet signing is a placeholder** |
  `handoff_packet.py` `SHA256_CHAIN_PLACEHOLDER` — hash-integrity, not
  cryptographic authenticity. | A forged packet with a recomputed hash would
  pass. | Implement Ed25519 signing before any non-local/production use. | No
  (design) | signature verification test.
- **SWARM-03 | Low (info) | manifest risk hardcoded `low`** |
  `local_executor.py:185-192` risk classification is caller-supplied, not derived
  from task content. | Low in AG-01 (workers are inert), but risk not
  content-derived. | Derive risk from task/department policy. | Yes | risk
  derivation test.

### Docker / Deployment Findings

- **PASS (verified):** no secrets in image layers (`.abigail.env` ro bind-mount,
  never baked); no committed secrets; abby host publish localhost-only; internal
  `0.0.0.0` bind intentional + guarded by `ALLOW_NONLOCAL_BIND`; healthchecks are
  real HTTP GETs; mounts clean (no Docker socket, not privileged); no duplicate
  containers; canonical env consistent; abby admin auth fail-closed 503/401.
- **DOCK-01 | CRITICAL | Sentinel governance control plane on `0.0.0.0`
  unauthenticated** | `docker-compose.yml:16-17` `"${SENTINEL_HOST_PORT:-9091}:8080"`
  (no host-IP prefix); `docker inspect asf-sentinel` → `HostIp 0.0.0.0` + IPv6;
  `governance-spine/src/server.rs` — only `/session/reset` is token-gated;
  `/inspect`, `/outbound`, `/audit`, `/session/*` are unauthenticated. Abby reaches
  Sentinel over the internal Docker network, so the host publish is only needed for
  local `make status`. | Anyone able to reach the host on 9091 (any NIC; on AWS =
  security group / public IP) can drive/read the governance pipeline with no
  credential. | Bind to `127.0.0.1:${SENTINEL_HOST_PORT:-9091}:8080` (mirror abby).
  | **Yes** (1-line compose) | confirm `make status` + abby→sentinel unaffected.
- **DOCK-02 | High | Sentinel audit disclosure + unauthenticated state mutation**
  | `server.rs` `/audit` returns last 50 entries (no auth); `/inspect`/`/outbound`
  run the pipeline on attacker payloads; `/session/end` mutates state. Reachable
  given DOCK-01. | Audit metadata leak; remote session/DRS poisoning; governance
  probing. | Add operator-token middleware to `/audit` + all mutating routes
  (reuse the `/session/reset` pattern); interim = DOCK-01 localhost bind. | Partial
  (bind now; auth = Rust code + test) | Sentinel auth test.
- **DOCK-03 | Medium | image drift — `swarm/` and `agents/` not shipped** |
  `abigail/Dockerfile` copies runtime modules but not `abigail/swarm/` or
  `agents/`; in-container `from swarm import …` → ModuleNotFoundError, and
  `load_all_agents()` returns 0 (AGENTS_DIR `/agents` absent). App still boots
  healthy (main never imports swarm). | Deployed container silently has an empty
  agent registry and no swarm activation despite code + passing tests in-repo. |
  `COPY abigail/swarm` + `COPY agents`; decide the agent-execution model (do **not**
  mount the Docker socket on AWS) before enabling. | Yes | rebuild + import/agent
  -count smoke.
- **DOCK-04 | Medium | `pydantic` imported but undeclared** | `model_router/
  envelopes.py:3`, `schemas.py:3` import pydantic; not in requirements (resolves
  only transitively via anthropic). | Bumping/removing anthropic or a pydantic
  major break silently breaks model_router. | Add pinned `pydantic>=2,<3`. | Yes |
  rebuild.
- **DOCK-05 | Low | setup.sh polls wrong Sentinel port (9090 vs 9091)** |
  `setup.sh:182,191`. | One-click setup falsely reports Sentinel down. | 9090→9091.
  | Yes | setup smoke.
- **DOCK-06 | Low | setup.sh echoes API key to terminal** | `setup.sh:55,59,63`
  use `read -p` not `read -s`; key lands in scrollback. | Local secret exposure in
  terminal history. | `read -s`. | Yes | manual.
- **DOCK-07 | Low/Info | no `.dockerignore`** | build `context: .` includes
  `.abigail.env`, `.git`, `**/target`. Current COPYs are specific (safe today). |
  Future broad `COPY` could leak. | Add `.dockerignore`. | Yes | build check.
- **SEC-03 | Low | Python Sentinel shims bind `0.0.0.0` unconditionally** |
  `governance-spine/sentinel_server.py:115`, `sprint5/sentinel_server_s5.py:110`
  (`app.run(host="0.0.0.0")`, `debug=False`). Not the deployed Rust server, but
  the same anti-pattern. | Unguarded bind if these shims are ever run directly. |
  Gate behind an env flag like the main app. | Yes | bind test.

### Static Scan Findings

- **Clean / guarded (no action):** no `eval`/`exec`/`pickle`; all YAML via
  `yaml.safe_load`; no `debug=True` (main app explicit `debug=False,
  use_reloader=False`); `subprocess` only list-arg into a hardened, DRS-gated,
  admin-fail-closed `docker run` sandbox (no `shell=True`, no `os.system`); no
  Docker-socket reference/mount; no `-----BEGIN`/AKIA/live-key literals (all
  `gsk_`/`sk-`/`xai-` hits are test fixtures or redaction regexes); no
  Authorization/key logging; network usage limited to provider + sentinel calls
  (Ollama localhost-restricted).
- **INFO | `datetime.utcnow()` deprecation (116 test warnings)** |
  `abigail_hardened_enhanced.py:~153` audit timestamp. | Deprecated; removed in a
  future Python — audit timestamps would break. | Move to
  `datetime.now(datetime.UTC)`. | Yes | existing suite.

### UI / Demo Truth Findings

- **PASS:** `static/operator.html` is exemplary (pervasive `Simulate Only`/`MOCK`
  /`PREVIEW`, disabled stubs, "no execution has occurred"); `index.html` labels
  the cockpit "Preview"; `docs/screenshots/README.md` honestly marks demo
  metrics; README claims no SOC2/HIPAA/FedRAMP and labels the patent "Provisional."
- **UI-01 | High (misleading buyer) | `static/dashboard.html`** | renders
  fabricated telemetry under a green **"Live · auto-refresh 15s"** header with no
  demo/mock label: 12 depts all `green`, 48 agents with `alignment`/`completion`/
  `tokenUsage`/`model`, job register `JOB-ASF-201..204`, "Live command view for the
  12-department doctrine stack", "Live Job Register". The project's own
  `docs/screenshots/README.md:36-37` states these are cockpit/demo values with no
  autonomous execution — the UI omits this. | A buyer sees 48 governed agents with
  live telemetry implying autonomous multi-agent execution that does not exist. |
  Add a persistent "DEMO / illustrative — not live execution" badge to the metrics,
  department grid, agent grid, and job register (mirror operator.html). | Yes |
  visual check.
- **UI-02 | Medium | provider labels mismatch router mode** | all 48 agents carry
  hardcoded `"Groq · …"` models, independent of `ABIGAIL_BACKEND` and MR-05 mode
  (0/1/2); diverges further after `a45f6c3` (anthropic/xai). | Implies each agent
  executes on a specific live model; labels don't match routing. | Drive labels
  from `/api/status` + router mode, or mark illustrative. | Yes | label-reflects
  -mode test.
- **UI-03 | Low-Med | `firmHealth` heuristic mislabeled** | `dashboard.html:~595`
  a 2-boolean up/down heuristic (96/72/38) shown as a measured "Firm Health %". |
  Presents a reachability flag as a composite posture score. | Relabel as
  reachability-derived. | Yes | No.
- **UI-04 | Low | README compliance-adjacent wording** | "governed agent
  deployments for compliance-sensitive environments." | No certification claimed
  (good), but readable as readiness. | Qualify as "governance tooling for teams
  operating in compliance-sensitive environments." | Yes | No.

### AWS MVP Readiness Findings (no deployment performed)

| # | Item | Status | Evidence / Gap |
|---|------|--------|----------------|
| AWS-01 | Runtime services | Ready | abby + sentinel healthy; all runtime modules import in-container. |
| AWS-02 | Secrets strategy | Partial | `.abigail.env` 600/ro/gitignored (local-good); no Secrets Manager/SSM/KMS. |
| AWS-03 | Network boundary | **Missing (Critical)** | Sentinel `0.0.0.0:9091` unauth (DOCK-01/02); must be private/localhost. |
| AWS-04 | TLS / domain | Missing | Plain HTTP everywhere; no ALB/ACM/reverse-proxy TLS. |
| AWS-05 | Logging path | Partial | Audit → local named volume mode 600; no CloudWatch/central drain; lost on task replace. |
| AWS-06 | Backup / rollback | Partial | Volumes + rebuildable image; no snapshot/registry-tag rollback strategy. |
| AWS-07 | Cost controls | Partial | App cost governor + BYOAPIKEY; no AWS budget/alarm/autoscale caps. |
| AWS-08 | Provider-key handling | Ready | Env-only, not baked, ro-mounted (move to Secrets Manager for AWS). |
| AWS-09 | IAM least privilege | Missing | No IAM/task-role definitions in repo. |
| AWS-10 | Container registry | Missing | Local images only; no ECR repo/push pipeline. |
| AWS-11 | Env promotion | Partial | Single `.abigail.env`; no dev/stage/prod separation. |
| AWS-12 | Health checks | Ready | Meaningful HTTP healthchecks (map to ALB/ECS). |
| AWS-13 | Incident response / kill-switch | Partial | App KillSwitch + Sentinel `/session/reset` (token); reachability depends on AWS-03; no runbook. |
| AWS-14 | Audit-log retention | Missing | No rotation/retention/WORM policy. |
| AWS-15 | Customer-data boundary | Partial | Sessions/audit in volumes; no data-classification/encryption-at-rest/residency. |
| AWS-16 | Public/private route split | Partial | abby has PUBLIC/DEMO/ADMIN modes; Sentinel has none (DOCK-02). |
| AWS-17 | Admin auth posture | Ready (abby) / Missing (sentinel) | abby fail-closed; Sentinel audit/mutating routes unauth. |
| AWS-18 | Preflight before public exposure | **Blocked** | Must clear DOCK-01/02, AWS-04, AWS-02, AWS-09/10 first. |

---

## Critical Blockers

1. **EP-01 (CRITICAL, confirmed live)** — unauthenticated path traversal /
   arbitrary file read → provider-key + admin/demo-token exfiltration; defeats the
   admin-token model globally.
2. **DOCK-01 (CRITICAL, confirmed)** — Sentinel governance control plane on
   `0.0.0.0:9091` with unauthenticated inspect/audit/session routes.

## High Findings

- **EP-02** — `/api/agents/dispatch` unauthenticated paid inference + full
  governance bypass.
- **GOV-01** — MM-03 approval gate fails **open** when the orchestration bridge is
  unavailable.
- **DOCK-02** — Sentinel audit disclosure + unauthenticated state mutation.
- **UI-01** — `dashboard.html` presents fabricated telemetry as "Live" with no
  demo label (buyer-misleading; contradicts the project's own docs).

## Medium Findings

GOV-02 (grounded-path leak / pre-Sentinel ordering), EP-03 (topology disclosure),
RTR-01 (hardcoded model IDs), SWARM-01 (activation not bound to `authored`),
DOCK-03 (image drift: swarm/agents unshipped), DOCK-04 (pydantic undeclared),
UI-02 (provider-label mismatch).

## Low Findings

SEC-01, SEC-02, SEC-03, RTR-05, RTR-07, RTR-09, EP-04, EP-05, SWARM-02, SWARM-03,
DOCK-05, DOCK-06, DOCK-07, UI-03, UI-04, and the `datetime.utcnow()` deprecation
(Info).

## Corrected / Dismissed (false positives)

- **RTR-08 (claimed "no dispatcher/`_router_dispatch` tests")** — **dismissed.**
  Coverage exists in `tests/test_model_router_live_dispatch.py` (9),
  `tests/test_router_approval_cost_integration.py` (4), and
  `tests/test_moe_router_chatpath_integration.py` (28); all green. The scanning
  agent only looked under `abigail/model_router/tests/`.
- **"`claude-sonnet-5` is an invalid Anthropic model id"** — **dismissed.**
  Sonnet 5 (`claude-sonnet-5`) is a current model. The env-overridability point
  is folded into **RTR-01**; the "invalid id" claim is outdated.

---

## Safe Fix Recommendations (low risk, apply after approval)

Config / one-liners, each with a smoke or unit test:
- **DOCK-01** — `127.0.0.1:` prefix on the Sentinel port publish.
- **DOCK-04** — pin `pydantic` in requirements.
- **DOCK-05** — setup.sh 9090→9091. **DOCK-06** — `read -s`. **DOCK-07** —
  add `.dockerignore`.
- **RTR-01** — add `ABIGAIL_GROQ_MODEL`/`ABIGAIL_PERPLEXITY_MODEL`/
  `ABIGAIL_OLLAMA_MODEL` env overrides.
- **RTR-09** — `hmac.compare_digest` for admin token.
- **UI-01 / UI-02 / UI-03 / UI-04** — demo badges + label/copy corrections.
- **EP-04 / EP-05** — trim public telemetry.
- `datetime.utcnow()` → `datetime.now(datetime.UTC)`.

## Fixes Requiring Operator Approval (behavior/logic or cross-language change)

- **EP-01** — static route containment (behavior change to file serving).
- **EP-02** — add auth + governance ordering to `/api/agents/dispatch`.
- **GOV-01** — make the approval gate fail **closed** when the bridge is absent.
- **GOV-02** — reorder `try_grounded_answer` behind Sentinel/HAAP + clamp.
- **DOCK-02** — Sentinel Rust auth middleware.
- **DOCK-03** — ship `swarm/`+`agents/` and decide the agent-execution model.
- **SWARM-01** — bind activation to `authored`. **SWARM-02** — Ed25519 signing.
- **RTR-07** — sensitive-tier local fallback.

## Deferred / Post-MVP Items

Full AWS control plane (AWS-04 TLS/ACM, AWS-09 IAM roles, AWS-10 ECR pipeline,
AWS-05 CloudWatch drain, AWS-14 audit retention/WORM, AWS-06 backup/rollback,
AWS-11 env promotion, AWS-15 data-classification), Ed25519 packet signing
(SWARM-02), content-derived risk classification (SWARM-03), and the AWS MVP
Deployment Plan (to be authored **after** blockers clear).

---

## Evidence Commands

```
git rev-parse HEAD                      # b4b6e55…
git status --short --branch            # clean
git -C ~/Abigailv1 log --oneline -1    # 5cdfee1 (sealed, untouched)
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
docker inspect asf-sentinel --format '{{json .NetworkSettings.Ports}}'   # HostIp 0.0.0.0
curl -s -o /dev/null -w '%{http_code}' --path-as-is \
  http://127.0.0.1:7070/../../../../etc/hostname                          # 200 (EP-01)
curl -s -o /dev/null -w '%{http_code}' -X POST -d '{}' \
  http://127.0.0.1:7070/api/agents/dispatch                              # 400 unauth (EP-02)
source .venv/bin/activate && python -m pytest -q                         # 1544 passed
```

## Test Results (Phase 9)

- `py_compile` core modules: **OK**.
- Security-critical suites — command_bus **36**, runtime_security_hardening **20**,
  approval_gate_promotion **7**, public_response_calibration **26**, swarm
  registry/local/marketing **14/15/7**, provider_capability_registry **7**,
  model_router_live_dispatch **9**, router_approval_cost_integration **4**,
  moe_router_chatpath_integration **28** — all **passed**.
- **Full suite: 1544 passed, 0 failed** (116 warnings = single `datetime.utcnow()`
  deprecation). No provider calls occurred in pytest.

## Exact Git Status

```
## sprint/mr05-router-chatpath
HEAD b4b6e5543e3e3f919c37306633689adca749b625
(working tree clean aside from this report + SEC-03 additions)
```

## Confirmations

- **No secrets printed** — all key/token handling used SET/UNSET or NAME-only;
  no values, prefixes, or suffixes emitted anywhere in this audit.
- **No push** — nothing was pushed to any remote.
- **No code changed / nothing committed** — audit-first; this report is the only
  new artifact, pending approval to commit.
- **Sealed baseline untouched** — `~/Abigailv1@5cdfee1` and
  `~/Abigailv1_EVIDENCE_20260703` were read for verification only, never modified.

---

## AWS MVP Go / No-Go

**NO-GO** for AWS MVP exposure until, at minimum:
1. EP-01 (path traversal) is fixed and regression-tested.
2. DOCK-01 (Sentinel `0.0.0.0`) is bound to localhost/private and DOCK-02 auth is
   added.
3. EP-02 (`/api/agents/dispatch`) is authenticated + governed.
4. GOV-01 (approval fail-open) is made fail-closed.
5. UI-01 (buyer-facing "Live" overclaim) is corrected.

**Buyer-facing claim boundary:** until the above clear and a live mode-2 test is
run under operator approval, defensible claims are limited to: "governed control
plane with dormant, bounded local swarm; model router integrated with dry-run
provable (mode 1) and live dispatch behind an operator flag (mode 2)." Claims of
production-live multi-agent autonomy, AWS readiness, or any compliance posture are
**not** currently supported.
