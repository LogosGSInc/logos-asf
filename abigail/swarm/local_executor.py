# -*- coding: utf-8 -*-
"""
local_executor.py — AG-01 governed local swarm executor.

Dispatches bounded department work under Abigail's supervision:
  - every dispatch requires a MM-01 RoutingManifest AND a scoped SignedHandoffPacket;
  - the SEC-02 cost gate is checked before any (would-be provider-backed) worker path;
  - the MM-03 approval gate stops high-risk / external-action work before execution;
  - containment/kill-switch is enforced EXTERNALLY (the worker cannot opt out);
  - workers receive only the scoped packet (bounded mission), never the full prompt,
    and may write only inside the approved workspace.

No provider calls. No network. Workers produce deterministic local draft artifacts.
"""
import dataclasses
import os
from pathlib import Path

from orchestration.routing_manifest import build_routing_manifest
from orchestration.handoff_packet import build_handoff_packet
from orchestration.schemas import SignedHandoffPacket
from orchestration.audit import now_utc

from .job_spec import ContainmentMode, FORBIDDEN_ACTIONS


class SwarmDenied(Exception):
    """Raised when a governed control refuses a swarm action."""


@dataclasses.dataclass
class DeptResult:
    department: str
    worker_id: str
    backed_by_authored_agent: bool
    manifest_id: str
    packet_id: str
    artifact: str
    artifact_path: str
    status: str                # complete | approval_required | blocked
    content: str = ""


# ── external containment / kill switch ─────────────────────────────────────────
class ContainmentController:
    """External kill-switch/containment. The executor consults it before every
    dispatch and every write; workers cannot bypass or override it."""

    def __init__(self, mode=ContainmentMode.RUNNING):
        self.mode = mode
        self.events = []

    def _record(self, action, reason, authority, scope, job_id):
        self.events.append({
            "action": action, "reason": reason, "authority": authority,
            "scope": scope, "job_id": job_id, "at": now_utc(),
            "resulting_mode": self.mode,
        })

    def kill(self, reason="operator", authority="operator", scope="all", job_id=None):
        self.mode = ContainmentMode.FULLY_KILLED
        self._record("KILL_SWITCH", reason, authority, scope, job_id)

    def pause(self, reason="operator", authority="operator", scope="all", job_id=None):
        self.mode = ContainmentMode.PAUSED
        self._record("PAUSE", reason, authority, scope, job_id)

    def disable_writes(self, reason="operator", authority="operator", scope="all", job_id=None):
        self.mode = ContainmentMode.WRITES_DISABLED
        self._record("WRITES_DISABLED", reason, authority, scope, job_id)

    def resume(self, reason="operator", authority="operator", job_id=None):
        self.mode = ContainmentMode.RUNNING
        self._record("RESUME", reason, authority, "all", job_id)

    def allows_dispatch(self):
        # PAUSED and FULLY_KILLED halt new dispatches; WRITES_DISABLED still lets a
        # worker compute a draft (the write itself is blocked separately).
        return self.mode in (ContainmentMode.RUNNING, ContainmentMode.WRITES_DISABLED)

    def allows_write(self):
        return self.mode == ContainmentMode.RUNNING


# ── default governance gates (compose with SEC-02 cost / MM-03 approval) ────────
def default_cost_gate(job, dept, manifest):
    """Deterministic local budget gate mirroring SEC-02 semantics. Returns
    (allowed, meta). A zero/empty budget fails closed."""
    enabled = os.environ.get("ABIGAIL_COST_GOVERNOR_ENABLED", "1") == "1"
    if not enabled:
        return True, {"decision": "allow_disabled"}
    try:
        max_ops = int(os.environ.get("ABIGAIL_MAX_SWARM_OPS", "1000") or 0)
    except ValueError:
        max_ops = 0
    if max_ops <= 0:
        return False, {"decision": "block_zero_budget", "max_swarm_ops": max_ops}
    return True, {"decision": "allow", "max_swarm_ops": max_ops}


def default_approval_gate(manifest, task):
    """MM-03 semantics: human approval required blocks execution (True => stop)."""
    return bool(getattr(manifest, "human_approval_required", False))


# ── the worker (bounded, packet-scoped, deterministic, no network) ──────────────
def _draft(dept, task, packet):
    hdr = (
        f"# {dept} — governed local draft\n\n"
        f"> **Status:** DRY-RUN / SANDBOXED-LOCAL governed draft. Not published, not sent, "
        f"not approved for external execution.\n"
        f"> **Manifest:** {packet.manifest_id} · **Packet:** {packet.packet_id} · "
        f"**Worker:** {packet.to_agent}\n"
        f"> **Bounded task:** {task}\n\n"
    )
    body = (
        f"## Draft deliverable\n\n"
        f"This is a bounded, supervisor-scoped draft for the **{dept}** department task "
        f"in job **{'/'.join(packet.input_refs) or 'local'}**. It contains no external "
        f"actions, no outbound contact, and no spend.\n\n"
        f"- Scope: {packet.authority_scope}\n"
        f"- Allowed outputs: {', '.join(packet.allowed_outputs) or 'local_draft'}\n"
        f"- Forbidden outputs: {', '.join(packet.forbidden_outputs) or 'external_actions'}\n\n"
        f"### Working notes\n\n"
        f"1. Objective derived strictly from the bounded task above.\n"
        f"2. Draft is reviewable by Abigail before any promotion.\n"
        f"3. Any external action would require a separate approval gate and is out of scope here.\n"
    )
    return hdr + body


def execute_worker(packet, dept, task=None):
    """Execute a bounded department worker. REQUIRES a scoped handoff packet that
    references a routing manifest. The worker sees only the packet — never the full
    user prompt or transcript — and cannot self-route or self-approve."""
    if packet is None or not isinstance(packet, SignedHandoffPacket):
        raise SwarmDenied("worker requires a scoped SignedHandoffPacket")
    if not packet.manifest_id:
        raise SwarmDenied("worker requires a RoutingManifest (manifest_id missing)")
    return _draft(dept, task or packet.mission, packet)


# ── the governed executor ───────────────────────────────────────────────────────
class LocalExecutor:
    def __init__(self, registry, containment, workspace, cost_gate=None, approval_gate=None):
        self.registry = registry
        self.containment = containment
        self.workspace = Path(workspace)
        self.cost_gate = cost_gate or default_cost_gate
        self.approval_gate = approval_gate or default_approval_gate
        self.audit = []

    def _audit(self, event, **fields):
        rec = {"event": event, "at": now_utc()}
        rec.update(fields)
        self.audit.append(rec)
        return rec

    def attempt_external_action(self, job, dept, action):
        """AG-01 never performs external actions. A request is recorded as an explicit
        blocked state and refused."""
        self._audit("EXTERNAL_ACTION_BLOCKED", job_id=job.job_id, department=dept,
                    action=action, decision="blocked",
                    reason="AG-01 forbids external actions (local-only)")
        return {"status": "blocked", "action": action, "reason": "external_action_forbidden"}

    def dispatch_department(self, job, dept, risk_level="low"):
        task = job.department_tasks[dept]
        artifact = job.artifact_for(dept)
        worker_id, authored = self.registry.resolve_department_worker(dept)

        # 1) external containment / kill switch — checked before anything else
        if not self.containment.allows_dispatch():
            self._audit("DISPATCH_BLOCKED", job_id=job.job_id, department=dept,
                        worker=worker_id, reason=f"containment:{self.containment.mode}")
            return DeptResult(dept, worker_id, authored, "", "", artifact, "", "blocked")

        # 2) activation gate — dormant/unactivated agents do not execute
        if not self.registry.can_execute(worker_id):
            self._audit("DISPATCH_BLOCKED", job_id=job.job_id, department=dept,
                        worker=worker_id, reason="agent_not_activated")
            raise SwarmDenied(f"{worker_id} is not activated for local execution")

        # 3) MM-01 routing manifest (required before any worker runs)
        manifest = build_routing_manifest(
            task_intent=f"swarm_department_task:{dept}",
            request_type="chat_inference",
            modality="text",
            source_trust_class="operator_direct",
            risk_level=risk_level,
            input_payload=task.encode("utf-8"),
        )

        # 4) SEC-02 cost gate — before any (would-be provider-backed) worker path
        cost_ok, cost_meta = self.cost_gate(job, dept, manifest)
        self._audit("COST_GATE", job_id=job.job_id, department=dept,
                    manifest_id=manifest.manifest_id, decision=cost_meta.get("decision"))
        if not cost_ok:
            self._audit("DISPATCH_BLOCKED", job_id=job.job_id, department=dept,
                        worker=worker_id, reason="cost_gate_blocked")
            return DeptResult(dept, worker_id, authored, manifest.manifest_id, "",
                              artifact, "", "blocked")

        # 5) MM-03 approval gate — high-risk / external-action stops before execution
        if self.approval_gate(manifest, task):
            self._audit("APPROVAL_REQUIRED", job_id=job.job_id, department=dept,
                        manifest_id=manifest.manifest_id, risk_level=risk_level)
            return DeptResult(dept, worker_id, authored, manifest.manifest_id, "",
                              artifact, "", "approval_required")

        # 6) scoped handoff packet (bounded mission, NO full prompt/transcript)
        packet = build_handoff_packet(
            manifest, to_agent=worker_id, mission=task,
            authority_scope=f"produce_local_draft:{artifact}",
            allowed_tools=[], allowed_outputs=[artifact],
            forbidden_outputs=sorted(FORBIDDEN_ACTIONS),
            input_refs=[f"job:{job.job_id}", f"dept:{dept}"],
        )

        # 7) bounded worker execution (deterministic, local)
        content = execute_worker(packet, dept, task)

        # 8) write only inside approved workspace, only if containment allows writes
        artifact_path = ""
        if job.mode == "active_sandboxed_local":
            if not self.containment.allows_write():
                self._audit("WRITE_BLOCKED", job_id=job.job_id, department=dept,
                            reason=f"containment:{self.containment.mode}")
                return DeptResult(dept, worker_id, authored, manifest.manifest_id,
                                  packet.packet_id, artifact, "", "blocked", content)
            target = self._safe_target(artifact)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            artifact_path = str(target)

        self._audit("DISPATCH_COMPLETE", job_id=job.job_id, department=dept,
                    worker=worker_id, backed_by_authored_agent=authored,
                    manifest_id=manifest.manifest_id, packet_id=packet.packet_id,
                    artifact=artifact, artifact_path=artifact_path)
        return DeptResult(dept, worker_id, authored, manifest.manifest_id,
                          packet.packet_id, artifact, artifact_path, "complete", content)

    def _safe_target(self, artifact):
        """Resolve an artifact path and refuse anything escaping the workspace."""
        base = self.workspace.resolve()
        target = (base / artifact).resolve()
        if base != target and base not in target.parents:
            raise SwarmDenied(f"write outside approved workspace refused: {artifact}")
        return target

    def run_job(self, job, risk_level="low"):
        """Dispatch every department in the job. Returns list[DeptResult]."""
        return [self.dispatch_department(job, dept, risk_level=risk_level)
                for dept in job.departments]
