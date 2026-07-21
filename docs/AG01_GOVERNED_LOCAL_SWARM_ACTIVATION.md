# AG-01: Governed Local Swarm Activation

**Document ID:** AG01_GOVERNED_LOCAL_SWARM_ACTIVATION
**Version:** 1.0
**Date:** 2026-07-05
**Status:** ACTIVE
**Authority:** LOGOS Governance Systems Inc.

---

## Purpose

Activate Abigail's authored agent registry into a **governed, local, bounded** swarm
execution path for one demo-safe job — building an Abigail marketing/advertising launch
kit. The goal is not autonomy. The goal is *verifiable, bounded, audited, local
multi-department execution under Abigail's supervision.*

## Activation Ladder

```
authored/dormant   →   authored/active_dryrun   →   authored/active_sandboxed_local
      (AG-01 operates only in the two local, bounded modes)
   ✗ production_autonomous  ✗ unbounded_autonomy  ✗ external_action  ✗ network_recon
   ✗ send_email  ✗ publish  ✗ ad_spend  ✗ cloud_deploy   (all refused by the registry)
```

## Current Scope

AG-01 activates **local governed swarm execution only**, as a harness (`abigail/swarm/`)
plus the DEMO-MKT-001 job. It is **not** wired into the live `/api/chat` path or the
cockpit UI in this sprint — so no runtime/UI surface claims live autonomous agents.

## What Authored/Active Means

- **Authored:** 77 agent definitions exist under `agents/` (root key `agent:`); 6 are
  inactive stubs. The registry loads them and reports each one's activation state.
- **Active (local):** an agent moved to `active_dryrun` or `active_sandboxed_local` may
  receive a scoped handoff packet and produce a bounded local draft. Nothing else.

## What Is Still NOT Autonomous

- AG-01 does **not** enable unbounded autonomy.
- AG-01 does **not** permit outbound actions: no ad spend, email sending, publishing,
  cloud deploy, external recon, or DB mutation.
- Agents cannot self-route, self-approve, self-expand scope, create child workers, or
  write final output — **Abigail alone** merges, arbitrates, and decides.
- Workers receive only a scoped packet (bounded mission), never the full prompt/transcript.

## Demo Job (DEMO-MKT-001)

A 12-department marketing launch kit, written only inside the approved workspace
`runtime/jobs/DEMO-MKT-001/` (git-ignored; not committed). Each department produces one
bounded draft; Abigail merges them into `final_abigail_launch_packet.md` plus an
`audit_summary.json`. Every artifact is a governed dry-run/sandboxed draft — **no
outbound action, no spend, no contact.**

## Department Task Map

| Dept | Bounded task | Artifact |
|---|---|---|
| EXE | mission, buyer, decision criteria | executive_brief.md |
| PRD | promise, pain, wedge, MVP boundary | product_positioning.md |
| MKT | campaign angles, ad themes, hooks | ad_campaign_angles.md |
| REV | sales motion, discovery, close path | sales_discovery_script.md |
| LGL | claims, disclaimers, risk review | legal_claims_review.md |
| FIN | pricing hypothesis, pilot economics | pricing_hypothesis.md |
| SEC | injection risk, security claims | security_posture_one_pager.md |
| GRC | controls → governance/audit language | governance_control_map.md |
| OPS | launch checklist, owners, sequence | operations_checklist.md |
| ENG | landing-page stub / build notes | landing_page_copy.md |
| DAT | funnel metrics, telemetry, success | metrics_plan.md |
| HR | operator roles, approval SOP, outreach | outreach_email_drafts.md |

## Authority Boundaries

Enforced in `swarm/local_executor.py` and `swarm/registry.py`:
- a worker runs only via `execute_worker(packet, …)` which **requires** a
  `SignedHandoffPacket` referencing a `manifest_id` (no manifest / no packet → refused);
- a worker returns a draft string only — it holds no approval, routing, or budget authority;
- writes are confined to the approved workspace (`_safe_target` refuses path escape);
- unactivated / dormant agents cannot execute.

## Approval Gate Interaction

Each dispatch builds an MM-01 `RoutingManifest`. If the manifest requires human approval
(high/critical risk, or a would-be external-action request), the dispatch returns
`approval_required` **before** any execution — mirroring MM-03. Requesting a forbidden
external action is recorded as an explicit `EXTERNAL_ACTION_BLOCKED` state.

## Cost Gate Interaction

A SEC-02-style cost gate is checked **before** every (would-be provider-backed) worker
path and **before** the merge/synthesis path. A zero/empty budget fails closed and blocks
dispatch. (AG-01 workers are local and deterministic, so no provider spend occurs; the
gate is nonetheless enforced and audited so the control is real.)

## Containment and Kill Switch

`ContainmentController` is enforced **externally** — the executor consults it before every
dispatch and every write; a worker cannot opt out.
- `paused` / `fully_killed` → new dispatches blocked (`DISPATCH_BLOCKED`);
- `writes_disabled` → dispatch may compute but the write is blocked (`WRITE_BLOCKED`);
- every kill/pause/disable event is recorded with action, reason, authority, scope, and
  affected job ID.

## Audit Evidence

`audit_summary.json` records: job id, mode, supervisor, decision, per-department status,
manifest IDs, handoff IDs, artifact refs, dispatch events, containment events, forbidden
-action blocks, and `external_actions_performed: false`. Every swarm claim maps to a
passing test or a generated artifact.

## Test Results

- `tests/test_swarm_registry_activation.py` — 7 (load/dormant/activate/forbidden-mode/labeling)
- `tests/test_swarm_local_execution.py` — authority bounds, gates, containment, kill switch, forbidden actions
- `tests/test_swarm_marketing_launch_job.py` — 12 departments → 14 artifacts, merge, audit, no-leak
- **AG-01 suite: 36 passed**; governance regression (MM-03/SEC-02/command-bus/UX-01): 89 passed;
  **full suite: 1496 passed** (no regressions).

## Known Limitations

- Workers are deterministic template renderers, not model-backed — by design for AG-01
  (no provider calls, fully local/testable). Model-backed bounded workers are a later step.
- The harness is not yet wired into `/api/chat` or the cockpit UI.
- Cost/approval gates here are swarm-native mirrors of SEC-02/MM-03 semantics; unifying
  them with the runtime instances is future work.

## Path to Live Swarm Demo

1. Wire the harness behind an operator-authorized, approval-gated `/api/jobs` surface.
2. Introduce model-backed bounded workers (still packet-scoped, cost-capped, no external action).
3. Promote containment/cost/approval to the shared runtime instances.
4. Only then may UI/marketing describe swarm capability — and only at the verified state.

---

*Cites only internal LOGOS / GovSec / MM-01 / MM-02 / MM-03 / SEC-02 doctrine and in-repo
code. No external citations.*
