# -*- coding: utf-8 -*-
"""
merge.py — AG-01 supervisor merge.

Abigail alone merges department drafts into the final launch packet and assigns a
supervisor decision state. Workers never merge or approve their own output. The final
packet is explicitly a demo-only local artifact — never approved for external execution.
"""
import dataclasses
import json
from pathlib import Path

from orchestration.audit import now_utc

from .job_spec import ContainmentMode


class SupervisorDecision:
    DRAFT_COMPLETE = "draft_complete"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED_FOR_DEMO_ONLY = "approved_for_demo_only"


@dataclasses.dataclass
class MergeResult:
    final_path: str
    audit_path: str
    decision: str
    audit_summary: dict


def supervisor_merge(job, dept_results, executor, cost_gate=None):
    """Merge department drafts under Abigail's authority. `executor` supplies the
    audit trail and containment. Cost gate is checked before the synthesis path."""
    from .local_executor import default_cost_gate
    gate = cost_gate or default_cost_gate

    # cost gate before the (would-be provider-backed) synthesis/merge path
    cost_ok, cost_meta = gate(job, "MERGE", None)
    executor._audit("COST_GATE", job_id=job.job_id, department="MERGE",
                    decision=cost_meta.get("decision"))
    if not cost_ok:
        raise RuntimeError("merge blocked by cost gate")

    completed = [r for r in dept_results if r.status == "complete"]
    pending = [r for r in dept_results if r.status == "approval_required"]
    blocked = [r for r in dept_results if r.status == "blocked"]

    if pending:
        decision = SupervisorDecision.APPROVAL_REQUIRED
    elif blocked or len(completed) < len(job.departments):
        decision = SupervisorDecision.DRAFT_COMPLETE
    else:
        # all departments produced bounded local drafts — safe for demo only
        decision = SupervisorDecision.APPROVED_FOR_DEMO_ONLY

    # ── build the final packet (Abigail-authored synthesis) ──
    lines = [
        "# Abigail Governed Launch Kit — Final Packet",
        "",
        "> **Governed local artifact.** Produced by Abigail's supervised local swarm "
        "(AG-01) in a bounded, sandboxed mode. No outbound actions, no spend, no publishing. "
        "This packet is **approved for demo only**, not for external execution.",
        "",
        f"- **Job:** {job.job_id} — {job.title}",
        f"- **Supervisor decision:** {decision}",
        f"- **Departments completed:** {len(completed)}/{len(job.departments)}",
        f"- **Generated:** {now_utc()}",
        "",
        "## Department contributions",
        "",
    ]
    for r in dept_results:
        lines.append(f"- **{r.department}** ({r.worker_id}, "
                     f"{'authored' if r.backed_by_authored_agent else 'synthetic-handle'}): "
                     f"`{r.artifact}` — {r.status} "
                     f"[manifest {r.manifest_id or 'n/a'} · packet {r.packet_id or 'n/a'}]")
    final_md = "\n".join(lines) + "\n"

    # ── audit summary ──
    audit_summary = {
        "job_id": job.job_id,
        "mode": job.mode,
        "supervisor": "abigail",
        "supervisor_decision": decision,
        "external_actions_performed": False,
        "departments": [r.department for r in dept_results],
        "manifest_ids": [r.manifest_id for r in dept_results if r.manifest_id],
        "handoff_ids": [r.packet_id for r in dept_results if r.packet_id],
        "artifacts": {r.department: r.artifact for r in dept_results},
        "artifact_paths": {r.department: r.artifact_path for r in dept_results if r.artifact_path},
        "department_status": {r.department: r.status for r in dept_results},
        "containment_events": executor.containment.events,
        "containment_mode": executor.containment.mode,
        "forbidden_action_blocks": [
            e for e in executor.audit if e.get("event") == "EXTERNAL_ACTION_BLOCKED"
        ],
        "dispatch_events": executor.audit,
        "cost_gate_meta": cost_meta,
    }

    # ── write outputs (only if containment allows writes and mode is sandboxed) ──
    final_path = audit_path = ""
    if job.mode == "active_sandboxed_local" and executor.containment.allows_write():
        base = Path(job.approved_workspace)
        base.mkdir(parents=True, exist_ok=True)
        fp = base / "final_abigail_launch_packet.md"
        ap = base / "audit_summary.json"
        fp.write_text(final_md, encoding="utf-8")
        ap.write_text(json.dumps(audit_summary, indent=2), encoding="utf-8")
        final_path, audit_path = str(fp), str(ap)

    executor._audit("SUPERVISOR_MERGE", job_id=job.job_id, decision=decision,
                    final_path=final_path)
    return MergeResult(final_path, audit_path, decision, audit_summary)
