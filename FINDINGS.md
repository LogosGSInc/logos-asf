# Findings

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
