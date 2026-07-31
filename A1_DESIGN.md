# A1 — Durable Session Governance: Design Plan

Status: approved, pre-implementation. This document is the reviewable
artifact for the design decision — not reconstructable from `git log` or
test output alone, unlike the code changes that will follow it.

## Problem (verified against the running code, not assumed)

Two disconnected identity concepts exist today:

- A **stable Flask conversation key** (`_skey`, resolved in
  `_resolve_chat_session`, `abigail/abigail_hardened_enhanced.py:2156-2160`)
  backing a `SessionState` object kept alive in `SessionRegistry` across
  turns. This key is **never sent to Sentinel**.
- A **Sentinel-facing `session_id` regenerated on every single turn**:
  `sentinel_session_id = f"session_{session.turn_count}_{uuid.uuid4().hex[:12]}"`
  at `abigail_hardened_enhanced.py:927`, inside `process_message()`, called
  fresh on every `/api/chat` POST.

Because of this, the Rust governance spine's three per-session maps
(`Arbiter.session_states`, `OverWatch.sessions`, `GovernancePipeline.session_memories`
— all keyed by the literal `session_id` string) never see the same key
twice for what a human would call "one conversation." Drift, cumulative
threat, lock state, and escalation cannot accumulate across turns — every
turn looks like the first message of a brand-new session to Rust.

`/session/start` and `/session/end` are fully implemented server-side
(`governance-spine/src/server.rs:510-573`) but **never called** by the live
client — the only Python caller, `governance-spine/sentinel_server.py`, is
not part of the deployed stack (the `sentinel` container runs the Rust
binary directly; see `docker-compose.yml` / `governance-spine/Dockerfile`).

`/api/agents/dispatch` (`abigail_hardened_enhanced.py:2405`) mints its own
`dispatch_{agent_id}_{uuid}` session_id, disconnected from whatever chat
conversation may have triggered it.

## Design

### Python — one durable ID per conversation

- `SessionState.__init__` gains two fields:
  `self.sentinel_session_id = f"conv_{uuid.uuid4().hex}"` and
  `self.session_started = False`. The ID's lifetime is now tied to the
  `SessionState` object's lifetime, which `SessionRegistry` already keeps
  stable per conversation key — no new parallel store, no new concept.
- The per-turn mint at `abigail_hardened_enhanced.py:927` is replaced with
  reading `session.sentinel_session_id`.
- New helper `_sentinel_session_start(session_id, actor_id)`, modeled
  directly on the existing `_sentinel_inspect()` pattern (same timeout,
  same `log_event` error shape). Called once per conversation, gated by the
  **existing** `SENTINEL_REQUIRED` fail-closed/degrade-open logic already
  used for `/inspect` (`abigail_hardened_enhanced.py:938-961`) — not a new
  policy, the same one, applied to a new call site.
  - On success, or on an intentional `SENTINEL_REQUIRED=0` degrade-open:
    mark `session_started = True`. It is never attempted again for that
    conversation.
  - On a hard-block failure (`SENTINEL_REQUIRED=1`, Sentinel unreachable):
    **the current turn is blocked** — `process_message` returns a governed
    refusal before `_sentinel_inspect`, before any provider dispatch, and
    before `record_turn()` — and `session_started` stays `False`, so the
    *next* turn retries rather than silently proceeding ungoverned. This is
    Test 7 (see below): no provider call, no dispatch, no session_id
    churn (the ID is stable regardless of outcome), a deterministic block
    response, and an audit event written.
- `/api/agents/dispatch` stops minting `dispatch_{agent_id}_{uuid}` and
  instead resolves the caller's conversation through the same
  `_resolve_chat_session` mechanism `/api/chat` already uses, then uses
  that session's `sentinel_session_id` for all governance calls in the
  handler — literal "inherit the conversation session."
  `tests/test_agent_dispatch_governance.py:283` currently asserts
  `governance["sentinel_session_id"].startswith("dispatch_")`; this is
  replaced with an assertion that the dispatch's `sentinel_session_id`
  **equals** the session_id of a conversation established via the same
  `X-Session-ID`/body `session_id` key — proving the governance binding,
  not just removing the old check. (Test 6.)
- `/session/end` hooks into the two places a conversation already
  naturally ends today: the CLI `/exit` verb
  (`abigail_hardened_enhanced.py:2897`, next to the existing `SESSION_END`
  audit event) and `SessionRegistry`'s existing eviction path (when the
  2048-session cap is hit). Both calls are **best-effort cleanup, not a
  fail-closed gate** — a failed `/session/end` must never block creating a
  new session or exiting the CLI. (Test 8.)
- **`/api/swarm/dispatch` is explicitly out of scope**, not a silent gap —
  logged to `FINDINGS.md` (see below). It has no Sentinel session concept
  at all today (it never calls `/inspect`); giving it one would be new
  scope beyond "inherit the conversation session," which presupposes a
  session already exists to inherit.

### Rust — small, additive, C3 untouched

- New method `Arbiter::forget_session(session_id: &str)` — a plain
  removal (`self.session_states.write().remove(session_id)`), mirroring
  the already-existing plain `OverWatch::reset_session` (`overwatch.rs:312-314`).
  This is a **new** method, not a change to `operator_reset_session`'s
  token-gated logic (`arbiter.rs:460-490`, unchanged) — C3 is not touched.
- `GovernancePipeline::end_session()` (`pipeline.rs:404-419`) currently
  clears only `session_memories`. Two lines are added to also call
  `self.arbiter.forget_session(session_id)` and
  `self.overwatch.write().reset_session(session_id)` — the same plain
  removal `operator_reset()` already uses for overwatch, invoked from a
  new call site, not a modified one.
- `/session/start` / `/session/end` HTTP route handlers
  (`server.rs:510-573`) need **no changes** — `/session/start` is already
  correctly read-only/descriptive (fail-closed behavior lives entirely on
  the Python caller's side); `/session/end` already does real cleanup, it
  was just never invoked.

## The four confirmations (requested before writing code)

**1. Does a `/session/start` failure block the current turn, not just future turns?**
Yes — see "Python" above. The check happens before `_sentinel_inspect`,
before any provider call, before `record_turn()`. Test named explicitly:
`test_session_start_failure_blocks_current_turn_fail_closed` — asserts
zero provider calls, zero dispatch, the session_id is unchanged
before/after, the response is the deterministic block shape, and a
`log_event` audit entry was written.

**2. Is the `/api/swarm/*` deferral logged, not silent?**
Yes — new `FINDINGS.md` entry (below), following the existing
`GRACEFUL_SHUTDOWN_PID1_SIGNAL_SEMANTICS` heading convention.

**3. Does the updated `test_agent_dispatch_governance.py:283` assertion prove the binding?**
Yes — re-designed as
`assert dispatch_governance["sentinel_session_id"] == conversation_session_id`,
established by first hitting `/api/chat` with a known `X-Session-ID`, then
`/api/agents/dispatch` with the same header, and comparing. This is Test 6
("session identifiers remain stable") applied at the dispatch boundary,
not a deletion of the old check.

**4. Was capability-token behavior re-examined against a session_id now stable across hundreds of turns, not just re-run?**
Yes — read `governance-spine/src/capability.rs:479-483` (`session_mismatch`)
and `:447-451` (`replay_rejected`) directly. `session_mismatch` tests
string-equality between the issued and presented `session_id`; it never
varies session_id *lifetime*, so it is structurally indifferent to A1.
`replay_rejected` tests single-use enforcement keyed by `gov_tx_id`
(freshly minted every turn regardless of session_id, per
`server.rs`'s `format!("GTX-{}", uuid::Uuid::new_v4().simple())`), not by
session_id — so a durable session_id introduces no new replay surface.
Both claims hold on direct re-reading, not by coincidence of the tests
still passing. One new test is added anyway,
`same_session_multiple_turns_each_capability_independent`, proving three
sequential issue/consume cycles under one stable session_id remain
mutually independent — the old tests only ever exercised one capability
per session in isolation, which A1 changes the realism of.

## Test plan (numbered per the original Phase 2 spec)

Rust — `governance-spine/tests/durable_session_governance.rs` (new):
1. drift increases across turns (same session_id, repeated signals)
2. cumulative threat increases
3. memory floor persists across turns
4. locks survive multiple turns
5. escalation ratchets upward
8. `end_session` clears all three maps (memory + arbiter + overwatch)
   — plus a same-session-different-session independence contrast test.

Rust — `governance-spine/src/capability.rs` (append to existing `mod tests`):
9. `same_session_multiple_turns_each_capability_independent` (new)

Python — `tests/test_durable_session_governance_a1.py` (new):
6. session identifiers remain stable — across chat turns, and across
   dispatch vs. the originating conversation
7. `/session/start` failure fails closed for the **current** turn
   (explicit, named test) + success marks-started/no-retry +
   `SENTINEL_REQUIRED=0` degrade-open
8. `/session/end` invoked on CLI `/exit` and on registry eviction

Existing test updated (not removed): `tests/test_agent_dispatch_governance.py:283`.

## Verification

After implementation: targeted tests, full Python suite (target 1666+
passing, up from 1666), full Rust suite (target 59+ passing, up from 59),
container rebuild + runtime verification of both services, evidence
recorded, commit separately from this design doc.
