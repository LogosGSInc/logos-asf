# Findings

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
