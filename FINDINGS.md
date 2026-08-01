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
