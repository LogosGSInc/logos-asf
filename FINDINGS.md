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
