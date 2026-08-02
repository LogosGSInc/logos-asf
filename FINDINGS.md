# Findings

## A1_REGISTRY_EVICTION_TRIGGERS_SESSION_END

A1 wired `SessionRegistry`'s existing eviction path (`get_or_create()`,
`abigail_hardened_enhanced.py`) to call `/session/end` best-effort when a
new conversation key arrives while the registry is at its 2048-session
cap. The eviction POLICY itself is unchanged from pre-A1: pick the first
non-`"default"` key in dict-iteration order and drop it — arbitrary, not
LRU, not by staleness, not by risk level.

Before A1 this was a purely in-process memory-bounding detail with no
external effect. Now it also ends that evicted conversation's Sentinel
session — clearing its `session_memories`/`arbiter`/`overwatch` state in
the Rust governance spine. An arbitrarily-chosen conversation (which could
be an active, escalated, or Sentinel-locked one just as easily as a stale
one) can now have its governance state cleared as a side effect of some
OTHER, unrelated conversation's key being created, once the registry is
full.

This is not a new regression from A1 (the eviction policy was already
arbitrary), but it is a new governance-relevant consequence of an
unreviewed policy, in the same category as the swarm-dispatch deferral
above: flagged here rather than left implicit. A real fix would give
`SessionRegistry` an actual eviction policy (LRU at minimum; ideally one
that never evicts an escalated/locked session) — out of scope for A1,
which only wired the existing eviction hook, not redesigned it.

## A1_UNBOUNDED_TURN_HISTORY_FAST_FOLLOW (fixed)

Identified while scoping A2: Rust's three per-session maps
(`GovernancePipeline.session_memories`, `Arbiter.session_states`,
`OverWatch.sessions`) have no TTL or background expiry — only
`/session/end` (real per A1) or the operator-token-gated `/session/reset`
(C3) clear an entry. This is a real consequence of A1, not merely adjacent
to it: every pre-A1 turn got a fresh session_id, so no entry ever
accumulated past one turn. A1's entire purpose is long-lived sessions — so
unbounded per-entry growth goes from theoretical to load-bearing as a
direct result of this phase, for exactly the use case (long governed
conversations) A1 exists for.

Two of the three maps had per-turn vectors with NO cap at all —
`SessionMemory.turns: Vec<TurnRecord>` (`session_memory.rs`, pushed
unconditionally on every `ingest_signal` call) and
`OverWatch::SessionFingerprint.tool_call_sequence: Vec<String>`
(`overwatch.rs`, pushed on every tool-keyword match). `escalation_events`
in the same `SessionFingerprint` struct was NOT in this category — already
time-windowed via `retain(|t| *t > cutoff)`.

**Fixed as a fast-follow, before A2 opened**, scoped deliberately small —
this is NOT a background TTL/prune system (still out of scope; revisit
only if abandoned-session accumulation, as opposed to per-conversation
turn history, becomes an observed operational problem):
- `session_memory.rs`: new `MAX_RETAINED_TURNS = 20` constant (mirrors
  Python's `ABIGAIL_SESSION_HISTORY_WINDOW` default of 20). `turns` is
  trimmed to this cap immediately after every push, oldest dropped first.
  `turn_count` (the cumulative counter driving velocity/DRS) is NOT
  windowed — only the retained per-turn detail is.
- `overwatch.rs`: new `MAX_TOOL_CALL_SEQUENCE_LEN = 20` constant, same
  bounded-recent-window shape as the existing `escalation_events`
  windowing in the same struct, applied by count instead of by time since
  tool-call detection isn't time-decayed in this model.
- Both changes are one-directional trims immediately after the existing
  push call sites — no new mechanism, no background sweep, mirrors
  patterns already present in this codebase (Python's history window,
  Rust's own `escalation_events` retain()).

Tests: 5 new (3 in `session_memory.rs`, 2 in `overwatch.rs`) — capped
length after 2-3x overflow, oldest-dropped-first ordering, and that
downstream computations (trajectory, multi-tool-chain suspicion
detection) still function correctly once history is bounded and being
continuously trimmed. Full Rust suite: 73 passed (was 68).

Consequence accepted as part of this fix, not a separate open question:
long-conversation behavior analysis (`compute_behavior_hash`,
multi-tool-chain detection) now only sees the most recent 20 turns/tool
mentions, not full conversation history, for conversations longer than
that — the same trade-off Python's own message-history window already
makes for its own context, not a new category of imprecision.

Many-abandoned-sessions growth (crashed clients, dropped connections —
distinct from single-conversation turn-history growth, which is what this
entry fixes) remains unaddressed: still bounded only by CLI `/exit` or
Python registry eviction reaching 2048 keys. Left for a real TTL/prune
mechanism if it's ever needed — not scoped here.

## A1_SWARM_DISPATCH_SESSION_DEFERRAL

A1 (durable session governance) gives `/api/chat` and `/api/agents/dispatch`
one stable `sentinel_session_id` per conversation, inherited by dispatch
from the originating chat session via the existing `_resolve_chat_session`
key. `/api/swarm/dispatch` (multi-department swarm dispatch,
`abigail_hardened_enhanced.py:2281-2381`) is explicitly **not** included in
this change.

`/api/swarm/dispatch` does not call `_sentinel_inspect` or any other
Sentinel session-id-bearing endpoint today — it gates only through the
local Python `haap_gate` and dispatches directly via `BACKEND_DISPATCH`.
There is no existing Sentinel session concept on this path for A1 to make
durable; giving it one would be new scope (wiring swarm dispatch into the
Rust governance spine for the first time), not the fix A1 describes
("agent dispatch must inherit the conversation session" presupposes a
session-aware dispatch path already exists to inherit into).

This is a real gap, not a false one: detached/background swarm dispatch
does not yet inherit or mint a durable governance session, and its
per-department worker calls remain outside Sentinel's drift/threat/lock
accumulation entirely. Deferred under the A1 scope guard — tracked here so
it doesn't silently disappear into "A1 is done."

## GRACEFUL_SHUTDOWN_PID1_SIGNAL_SEMANTICS (was: GRACEFUL_SHUTDOWN_NOT_IMPLEMENTED)

Both `sentinel` and `abby` previously ran as PID 1 inside their container
PID namespaces. PID 1 receives special signal treatment: signals whose default
disposition would terminate an ordinary process may be ignored unless the
process installs a handler. Without an init process or explicit SIGTERM
handling, both workloads remained alive until the runtime forced SIGKILL.
This is standard containerized-process behavior, not evidence of a defect in
the governance logic.

Fix: added `init: true` to both services in `podman-verify-compose.yml`.
`podman-compose` translates this to `podman run --init`, inserting a minimal
init process as PID 1 so the app runs as PID 2+ and receives default SIGTERM
disposition (prompt termination).

Verified 2026-07-30:

| Container | Before (baseline) | After (`init: true`) |
|---|---|---|
| abby | SIGKILL forced at 10s ("StopSignal SIGTERM failed... resorting to SIGKILL") | 0.616s, clean SIGTERM, no SIGKILL warning |
| sentinel | SIGKILL forced at 10s ("StopSignal SIGTERM failed... resorting to SIGKILL") | 0.248s, clean SIGTERM, no SIGKILL warning |

SIGTERM now terminates promptly via init:true; clean audit flush before exit
not yet verified — see F2.

This proves signal delivery and prompt process termination. It does NOT
prove clean audit-buffer flushing before exit — whether an in-flight audit
write completes before the process dies is a separate, deeper concern
(audit durability under process death), scoped to F2 alongside the audit
hash-chaining and signing-key persistence fixes (A2/A3), not the Podman
migration branch.

## SESSION_ID_CLIENT_CONTROLLED

Gate 0 of the GovMem convergence effort (PR #9) fixed a real bug: the
browser never sent `X-Session-ID`, so every request fell back to
`remote_addr`, and users sharing one NAT shared one Sentinel/GovMem session
(cross-user drift bleed). The fix — `crypto.randomUUID()`, minted
client-side, sent as `X-Session-ID` — closes that gap correctly. It also
changes the threat model in a direction neither the original design doc nor
the PR noticed at the time:

| | Before (`remote_addr`) | After (`X-Session-ID`) |
|---|---|---|
| Cross-user bleed (shared NAT) | Broken | Fixed |
| Evasion by key rotation | Hard (shared infra IP) | Trivial (mint a new id per request) |

GovMem's entire premise (`governance-spine/src/govmem.rs`, `SessionMemory`)
is per-session accumulation of drift/threat across turns. The session key
now used for that accumulation is chosen entirely by the client with no
authentication behind it. An adversary running a multi-turn attack
(TAX2/BD1A-style) defeats accumulation-based detection by sending a fresh
`X-Session-ID` on every request — one HTTP header, no exploit required.

**The hoped-for mitigation does not currently work.** `StrategicMemory`
(`governance-spine/src/session_memory.rs`) is cross-session, keyed by
`actor_id` rather than `session_id` — in principle exactly the layer that
should survive a rotating session key. Tracing the actual wiring
(`governance-spine/src/pipeline.rs`):

- **Write path** — `end_session()` (`pipeline.rs:412`) calls
  `strategic_memory.ingest_session(actor_id, fingerprint)`
  (`pipeline.rs:420`) with an `actor_id` read from the HTTP `/session/end`
  body (`server.rs:576-577`, defaulting to `"anonymous"` if absent). In
  production this endpoint is only ever called from
  `_sentinel_session_end()` (`abigail_hardened_enhanced.py:1473`), which is
  itself only ever invoked with the `session_id` argument
  (`abigail_hardened_enhanced.py:752`, `:3047`) — `actor_id` is never
  passed, so the function's default fires every time:
  `actor_id: str = "abigail"`. Every real user, in every session, is
  currently ingested into `StrategicMemory` under the single literal
  key `"abigail"`.
- **Read path** — the actual advisory lookup on the hot inbound path,
  `init_session_memory()` → `advise_session_start()`
  (`pipeline.rs:499`), is called as
  `self.strategic_memory.read().advise_session_start(session_id)` —
  passing `session_id`, not `actor_id`, into a parameter the function
  itself names `actor_id` (`session_memory.rs:563`,
  `self.actors.get(actor_id)`). `session_id` is never the literal string
  `"abigail"`, so this lookup misses every single time in production.

Net effect: independent of the session-rotation question, **Tier 2
(`StrategicMemory`) provides zero live cross-session protection today.**
The read and write paths use disjoint key spaces that structurally cannot
intersect, so `advise_session_start` always falls through to the default
`SessionStartAdvice` (`Clear`, threshold ×1.0, no advisory) regardless of
an actor's history. This is not merely "evadable by rotating the header" —
it does not function even for a single non-adversarial user who never
rotates anything. Naively fixing only the key mismatch (thread the real
`session_id`'s owning actor through to both calls) would not be safe
either: since the write side is currently a hardcoded constant, every
distinct human user in the system would collapse onto one shared
`"abigail"` actor profile — indiscriminate aggregation across all users,
the opposite failure mode from evasion.

No fix applied here — this is a design question (what should `actor_id`
be bound to for an anonymous, unauthenticated caller?) belonging to
whichever gate takes up cross-session governance identity, not a
one-line wiring correction. `governance-spine/tests/durable_memory.rs`
does not catch this because its tests call `ingest_session` and read back
under the same, consistently-chosen key — the mismatch is in the
integration wiring (`pipeline.rs`), not in `StrategicMemory` itself, so
unit-level tests of `StrategicMemory` in isolation cannot see it.

Open questions this bears on, both unresolved by design (see brief §6):

- **Q-03** — no longer just "fail closed vs. server-side mint" for an
  absent header. The real question is what session/actor identity is
  *bound to* and whether that binding is authenticated. For an
  authenticated caller, bind to the account. For an anonymous one, a
  client-supplied id is a convenience identifier for UX continuity, not a
  security boundary, and should not be trusted as the sole key for
  accumulation-based governance.
- **Q-08** (new) — *"What does `actor_id` derive from at
  `pipeline.rs:420` and `:499`? If it derives from `session_id`,
  `StrategicMemory` inherits the evasion and Tier 2 provides no
  cross-session protection against an adversary who rotates the
  header."* Answered by the trace above: `:420`'s `actor_id` does *not*
  derive from `session_id` — it derives from an HTTP body field that
  production never populates, so it is always the constant `"abigail"`.
  `:499` uses `session_id` directly where `actor_id` was clearly intended
  (the parameter is literally named `actor_id`). Both paths are broken,
  independently, in different directions.

## GOVMEM_V2_SCAFFOLDING_NOT_WIRED

**Status:** Partially resolved — Gate 3 (`v1_sessions`/`should_block`); `embedding_model`/`mpa` remain open

`governance-spine/src/govmem.rs`'s `GovMem` struct originally carried
three fields — `v1_sessions`, `embedding_model`, `mpa` — that were
initialized in `new()` but never read anywhere in the module. This was
independently confirmed by both the Rust compiler's dead-code lint and a
full ground-truth survey of the codebase (`ABIGAIL_DEFINITION.md` §3.1):

- `v1_sessions` was never touched by `record_turn`'s V1 branch, which was
  itself a documented no-op (its comment said "delegate to
  session_memory.rs — not implemented here").
- `embedding_model` and `mpa` are hardcoded to `None` at construction and
  no code path ever loads them. Their backing types (`SentenceEmbedder`,
  `MemoryPolicyAgent`) are explicitly labeled
  `// PLACEHOLDER TYPES (To be implemented in Phase 2)`.
- `GovMemMode` defaults to `V1` (`pipeline.rs`, reads `GOVMEM_MODE`, not
  set anywhere in `docker-compose.yml`/`.abigail.env`), so even the V2
  code path `embedding_model`/`mpa` exist for is still not exercised in
  the real deployment today.

**Gate 3 update:** `v1_sessions` is no longer dead. Renamed
`session_memories`, it's now the same `Arc` `GovernancePipeline` holds
(shared, not duplicated — see `DEPARTMENT_LIST_DIVERGENCE`-adjacent Tier 1
convergence work below), and `should_block()` reads it directly,
unconditional on `GovMemMode` — so this part of the scaffolding is live
regardless of whether `GOVMEM_MODE=v2` is ever set. Its `#[allow(dead_code)]`
annotation is removed accordingly.

`embedding_model` and `mpa` remain exactly as described above — hardcoded
`None`, backing placeholder types, gated behind `GovMemMode::V2` which
nothing sets. This is left as a **tracked, intentionally unsuppressed**
compiler signal, not silenced — see the remaining field-level
`#[allow(dead_code)]` annotations in `govmem.rs`, each with a comment
pointing back to this entry. Closing the rest of this finding means either
wiring these two fields to something real or removing them outright, not
suppressing the warning.

## DEPARTMENT_LIST_DIVERGENCE

**Status:** Resolved — Gate 1

**Root cause:** Five independent hardcoded department enumerations
across `VALID_DEPTS`, `ASF_DEPARTMENTS`, `govmem.rs`'s `dept_ids`,
`static/dashboard.html`'s `doctrine` array, and the `agents/` filesystem,
using three incompatible ID formats (`EXE`, `EX-01`, `lgl01`) with no
single source of truth.

**Findings:**
- QA (full staff, 7 agents) was absent from `VALID_DEPTS` and `govmem.rs`.
- RI (Research Intelligence) was absent from `VALID_DEPTS` and
  `govmem.rs`; `ASF_DEPARTMENTS` did carry it, but under the wrong id
  `DEPT-RES` instead of `DEPT-RI` — not a missing entry as originally
  assumed going into this gate, but a mislabeled one.
- EXE and SC were absent from `ASF_DEPARTMENTS` (enumeration drift, not
  policy) — these are the only two active departments with no prior
  `agency_level` value anywhere to carry forward. `agency_level: 1` for
  both is now confirmed (OD-6 for EXE, OD-7 for SC), no longer an open
  question.
- REV and QA were assumed absent from `ASF_DEPARTMENTS` going into this
  gate; both were actually already present with established
  `agency_level` values (2 and 2), which this gate preserved rather than
  overwrote.
- HR was present in `VALID_DEPTS` and `govmem.rs` with no YAML, folder,
  or agents ever defined for it — removed everywhere (`abigail/swarm/job_spec.py`'s
  demo job spec, `static/dashboard.html`'s doctrine array, both hardcoded
  lists too).
- SC-01 and SEC-01 are distinct departments sharing one folder (tracked
  separately as `DEPT_FOLDER_AMBIGUITY`, see `departments/registry.json`
  → `open_remediation_items`).
- Neither `governance-spine/Dockerfile` (build context `./governance-spine`)
  nor `abigail/Dockerfile` (build context `.`, but the Python file is
  copied flat to `/app/abigail_hardened_enhanced.py`, breaking the
  local-dev-relative registry-path derivation) could reach
  `departments/registry.json` at its default path without changes — both
  were fixed as part of this gate (bind mount + `GOVMEM_REGISTRY_PATH`
  for sentinel; `COPY` + `ABIGAIL_DEPT_REGISTRY_PATH` for abby). Without
  this, the fail-closed startup assertion in `GovMem::new()` would have
  panicked in the actual deployed container on the very first Gate 1
  release.

**Resolution:** Single source of truth at `departments/registry.json`.
`VALID_DEPTS` and `ASF_DEPARTMENTS` (`abigail/abigail_hardened_enhanced.py`)
and `govmem.rs`'s department configs all load from it at runtime; no
hardcoded department list survives in any of the three. `govmem.rs` also
now parses each department's `govmem_escalation_policy` from the registry
instead of hardcoding `ThreeStrike` for all of them (today they're all
`ThreeStrike` in practice, but the old code would have silently ignored a
future per-department override).

`departments/registry.json` has no `agency_level` field, so
`ASF_DEPARTMENTS`'s per-department agency levels are still a second,
un-reconciled source (a private `_AGENCY_LEVELS` dict in
`abigail_hardened_enhanced.py`, carried over from the pre-Gate-1 literal)
— not eliminated by this gate, only kept from silently drifting further.

**Canonical counts post-reconciliation:**
- Active departments: 14
- Inactive stubs: 1 (TKR)
- Removed ghosts: 1 (HR)
- Runtime department count: 14

## DEPT_THRESHOLD_CLIENT_SELECTABLE

**Status:** Open — introduced in Gate 2, documented at introduction
**Severity:** High
**Related:** SESSION_ID_CLIENT_CONTROLLED (Gate 0)

**What it is:**
After Gate 2, the drift-blocking threshold applied to a session is a function
of the `department_id` field on the inbound request. Thresholds vary materially
by department (LGL: 0.8 — most lenient; SEC/SC/GRC: 0.5 — most strict).

**Why it is a bypass surface:**
Abigail is the only Sentinel client, authenticated by one shared
SENTINEL_SERVICE_TOKEN bearer token. Nothing distinguishes "this request
genuinely originates from LGL" from "this request claims to be LGL."
A caller with token access can supply `department_id: "LGL"` on any request
and receive the most lenient threshold regardless of actual department context,
defeating per-department escalation policy.

**Why Gate 2 proceeds anyway:**
The alternative — keeping `should_block(session_id, None)` — means the
threshold is always `unwrap_or(0.7)` for every department, forever, with no
path to per-department enforcement. That is also a bypass: a permanent one,
invisible in the audit log, with no finding attached to it.

Gate 2 makes the bypass *visible and named* rather than *structural and silent*.
A named, logged bypass with a documented remediation path is a better posture
than an undocumented structural one.

**Remediation path (not in Gate 2 scope):**
Per-department authentication at the Sentinel boundary. Options:
1. Per-department signing tokens replacing the shared SENTINEL_SERVICE_TOKEN
2. Server-side department resolution from authenticated session context,
   never from the request body
3. Threshold selection moved entirely server-side, keyed off actor profile
   rather than claimed department

Any of these requires auth infrastructure changes outside the GovMem scope.
Track as a post-Gate-4 security item.

**Prior comment at pipeline.rs:162-163:**
"Runtime identity metadata — populated from env vars, metadata only.
Do not pass these into should_block(); threshold behavior must not change."
This comment was correct at the time it was written. Gate 2 intentionally
supersedes it. The comment is removed as part of Gate 2's implementation;
its constraint no longer holds and leaving it would mislead future readers.

## GOVMEM_TIER1_CONVERGENCE

**Status:** Resolved — Gate 3

**Root cause:** Two independent, disconnected per-session threat trackers
existed in `governance-spine`. `GovernancePipeline.session_memories`
(`SessionMemory`, `session_memory.rs`) is the real accumulator —
`ingest_to_memory` populates it every turn, and it drives the arbiter's
`threshold_modifier`. `GovMem.v2_sessions`' `semantic_drift_score`/
`mpa_anomaly_score` is what `should_block()` actually read — but those
fields are permanent `0.0` placeholders (`embedding_model`/`mpa` are never
wired, see `GOVMEM_V2_SCAFFOLDING_NOT_WIRED`), and the whole check was
gated behind `GovMemMode::V2`, which nothing in any compose/env file ever
sets. Net effect: `should_block()` always returned `false` in every real
deployment, regardless of actual accumulated threat.

**Resolution:** `GovMem` now holds `session_memories` — the *same* `Arc`
`GovernancePipeline` constructs and shares at `GovernancePipeline::new()`
(hoisted before `GovMem::new_with_sessions()` is called, cloned into both,
never a second independent map). `should_block()` reads it directly and
unconditionally (no more `mode != V2` gate) — this is what
`GovMemMode::V1`'s own doc comment ("Rule-based only — existing
session_memory.rs") always claimed to be.

**Threshold comparison formula (a design decision this gate had to make,
not specified in advance):** the old check was `score > threshold` where
`score` was a semantic-drift float. Tier 1's `SessionMemory` doesn't
expose a comparable raw float — its native output is `MemoryState`
(`Clear`/`Watching`/`Elevated`/`Escalated`/`Locked`) and
`threshold_modifier()` (1.0 down to 0.0, *tightening* as severity rises).
To preserve the same comparison direction and department semantics
(`DEPT_THRESHOLD_CLIENT_SELECTABLE` — lower `drift_threshold` = stricter
department = blocks sooner), this gate defines `block_score = 1.0 -
threshold_modifier()`: `Clear`=0.0, `Watching`=0.15, `Elevated`=0.35,
`Escalated`=0.60, `Locked`=1.0. `should_block` is `block_score >
department_threshold`. This is a reasonable mapping, not a specified one —
worth operator review if the department threshold values in
`departments/registry.json` are ever revisited, since they were tuned
against the old (always-`false`) check and have no track record against
this one.

**Also fixed as part of the same instrumentation pass:**
- `pipeline.rs::outbound()` labeled its own corridor evaluation
  `"corridor_out"` — it was copy-pasted from `inbound()`'s L2 call and
  still said `"corridor_in"`, making every outbound `LayerSignal`
  indistinguishable from an inbound one in session history.
- `pipeline.rs::outbound()` now calls `self.govmem.record_turn(...)` with
  `MessageDirection::SystemToUser` — previously only `inbound()` called
  `record_turn` at all, so outbound turns never appeared in
  `GovMemSession.messages` history. `department_id`/`agent_id` are passed
  as `None` here (metadata only, `record_turn` doesn't feed `should_block`)
  since `outbound()` has no caller-supplied identity context today —
  threading that through was out of this gate's scope.

**Explicitly not done — Tier 2 stays inert (Q-08a, Option D):**
`StrategicMemory` (`session_memory.rs`) is untouched. The two `actor_id` boundaries
(`pipeline.rs::end_session` and `::init_session_memory`) already had
`TODO(Q-08)` comments describing the bug (`actor_id` is always the
constant `"abigail"` in production — see `SESSION_ID_CLIENT_CONTROLLED`).
This gate adds `TODO(Q-08a)` at both, in the code itself, stating the
decision explicitly: do not "fix" this by substituting `X-Session-ID` or
any other client-provisioned value as `actor_id` — that trades one
spoofable identity for another, and Tier 2 giving zero live advisory value
today is a safer state than Tier 2 giving *wrong* advisory value keyed off
a spoofable identity. Tier 2 stays inert until Abigail can supply a
server-authenticated durable actor identifier.

## TAX2_REQUESTS_UNDECLARED

**Status:** Open — follow-on, not fixed here
**Severity:** Low (works today; breaks on a clean environment)

`redteam/tax2/harness/fasdtest_dark_psych_v2_1.py` imports `requests`
(lines 27, 371, 375, 467) but no installable dependency manifest in the
repo declares it — it isn't in any `requirements*.txt`. The harness works
in any environment that happens to already have `requests` installed
(true of every environment this has been run in so far), but a genuinely
clean environment would fail with `ModuleNotFoundError` at import time.

**Fix (not done here):** add `requests` to whichever manifest governs the
TAX2 harness's dependencies (a `requirements.txt` alongside the harness,
or the repo-root one if TAX2 is meant to share it).

## UTC_TIMESTAMP_DEPRECATED

**Status:** Open — follow-on, not fixed here
**Severity:** Low (non-blocking deprecation warning, not a correctness bug)

`datetime.datetime.utcnow()` is deprecated as of Python 3.12 (confirmed
via `DeprecationWarning` in the pytest run). Five call sites in
`abigail/abigail_hardened_enhanced.py`: lines 200, 687, 1342, 3006, 3021 —
all audit/state-timestamp writes (`log_event`, kill-switch state,
provider-execution issuance, department kill/restart state).

**Fix (not done here):** replace each with
`datetime.datetime.now(datetime.UTC).isoformat()`. Track as one cleanup
pass across all audit-writing boundaries rather than fixing piecemeal —
only touch these lines incidentally if a future gate already has a reason
to edit the same boundary.
