# -*- coding: utf-8 -*-
"""AG-01: swarm local execution — authority bounds, gates, containment, kill switch."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
from swarm import (  # noqa: E402
    SwarmRegistry, build_demo_job, ContainmentController, ContainmentMode,
    LocalExecutor, SwarmDenied, ActivationState, execute_worker, supervisor_merge,
)
from orchestration.schemas import SignedHandoffPacket  # noqa: E402


def _job(tmp_path, mode="active_sandboxed_local"):
    return build_demo_job(workspace_root=str(tmp_path / "runtime" / "jobs"), mode=mode)


def _reg_all_active(job, mode=ActivationState.ACTIVE_SANDBOXED_LOCAL):
    r = SwarmRegistry()
    for d in job.departments:
        wid, _ = r.resolve_department_worker(d)
        r.activate(wid, mode)
    return r


# ── worker authority bounds ─────────────────────────────────────────────────
def test_worker_requires_handoff_packet():
    with pytest.raises(SwarmDenied):
        execute_worker(None, "MKT")
    with pytest.raises(SwarmDenied):
        execute_worker({"not": "a packet"}, "MKT")


def test_worker_output_is_bounded_string_not_authority(tmp_path):
    job = _job(tmp_path)
    reg = _reg_all_active(job)
    ex = LocalExecutor(reg, ContainmentController(), job.approved_workspace)
    res = ex.dispatch_department(job, "MKT")
    # worker produced a draft string; it does not carry approval/route authority fields
    assert isinstance(res.content, str) and res.content
    assert res.status == "complete"          # status is set by the executor, not the worker
    assert "governed local draft" in res.content.lower()


def test_worker_never_receives_full_prompt(tmp_path):
    # The scoped packet's mission is the bounded department task only.
    job = _job(tmp_path)
    reg = _reg_all_active(job)
    ex = LocalExecutor(reg, ContainmentController(), job.approved_workspace)
    res = ex.dispatch_department(job, "PRD")
    # content references the bounded task, not a sprawling transcript
    assert job.department_tasks["PRD"][:20] in res.content
    assert "SECRET_FULL_TRANSCRIPT" not in res.content


def test_write_outside_workspace_refused(tmp_path):
    job = _job(tmp_path)
    ex = LocalExecutor(_reg_all_active(job), ContainmentController(), job.approved_workspace)
    with pytest.raises(SwarmDenied):
        ex._safe_target("../../../etc/passwd")


def test_unactivated_worker_cannot_execute(tmp_path):
    job = _job(tmp_path)
    reg = SwarmRegistry()  # nothing activated
    ex = LocalExecutor(reg, ContainmentController(), job.approved_workspace)
    with pytest.raises(SwarmDenied):
        ex.dispatch_department(job, "MKT")


# ── approval gate ────────────────────────────────────────────────────────────
def test_high_risk_returns_approval_required_before_execution(tmp_path):
    job = _job(tmp_path)
    reg = _reg_all_active(job)
    ex = LocalExecutor(reg, ContainmentController(), job.approved_workspace)
    res = ex.dispatch_department(job, "MKT", risk_level="high")
    assert res.status == "approval_required"
    assert res.artifact_path == ""       # nothing written
    assert not (Path(job.approved_workspace) / job.artifact_for("MKT")).exists()


# ── containment / kill switch (external enforcement) ─────────────────────────
def test_kill_switch_blocks_new_dispatch(tmp_path):
    job = _job(tmp_path)
    reg = _reg_all_active(job)
    c = ContainmentController()
    c.kill(reason="operator halt", authority="operator", job_id=job.job_id)
    ex = LocalExecutor(reg, c, job.approved_workspace)
    res = ex.dispatch_department(job, "MKT")
    assert res.status == "blocked"
    assert any(e["event"] == "DISPATCH_BLOCKED" for e in ex.audit)


def test_kill_switch_blocks_writes(tmp_path):
    job = _job(tmp_path)
    reg = _reg_all_active(job)
    c = ContainmentController(mode=ContainmentMode.WRITES_DISABLED)
    ex = LocalExecutor(reg, c, job.approved_workspace)
    res = ex.dispatch_department(job, "MKT")
    assert res.status == "blocked"
    assert any(e["event"] == "WRITE_BLOCKED" for e in ex.audit)
    assert not (Path(job.approved_workspace) / job.artifact_for("MKT")).exists()


def test_kill_switch_events_recorded_with_reason_and_authority():
    c = ContainmentController()
    c.kill(reason="anomaly detected", authority="sec-operator", scope="all", job_id="DEMO-MKT-001")
    ev = c.events[-1]
    assert ev["action"] == "KILL_SWITCH"
    assert ev["reason"] == "anomaly detected"
    assert ev["authority"] == "sec-operator"
    assert ev["job_id"] == "DEMO-MKT-001"


# ── cost gate ─────────────────────────────────────────────────────────────────
def test_cost_gate_checked_before_worker_path(tmp_path):
    job = _job(tmp_path)
    reg = _reg_all_active(job)
    calls = {"n": 0}

    def spy(job_, dept, manifest):
        calls["n"] += 1
        assert manifest is not None       # gate sees the manifest before execution
        return True, {"decision": "allow"}

    ex = LocalExecutor(reg, ContainmentController(), job.approved_workspace, cost_gate=spy)
    ex.dispatch_department(job, "MKT")
    assert calls["n"] == 1


def test_zero_budget_blocks_dispatch(tmp_path):
    job = _job(tmp_path)
    reg = _reg_all_active(job)
    ex = LocalExecutor(reg, ContainmentController(), job.approved_workspace,
                       cost_gate=lambda *a: (False, {"decision": "block_zero_budget"}))
    res = ex.dispatch_department(job, "MKT")
    assert res.status == "blocked"
    assert not any(e["event"] == "DISPATCH_COMPLETE" for e in ex.audit)


def test_cost_gate_checked_before_merge(tmp_path):
    job = _job(tmp_path)
    reg = _reg_all_active(job)
    ex = LocalExecutor(reg, ContainmentController(), job.approved_workspace)
    results = ex.run_job(job)
    calls = {"merge": 0}

    def merge_gate(job_, dept, manifest):
        if dept == "MERGE":
            calls["merge"] += 1
        return True, {"decision": "allow"}

    supervisor_merge(job, results, ex, cost_gate=merge_gate)
    assert calls["merge"] == 1


# ── forbidden external actions ───────────────────────────────────────────────
@pytest.mark.parametrize("action", ["publish", "send_email", "ad_spend"])
def test_forbidden_action_blocked(tmp_path, action):
    job = _job(tmp_path)
    ex = LocalExecutor(_reg_all_active(job), ContainmentController(), job.approved_workspace)
    out = ex.attempt_external_action(job, "MKT", action)
    assert out["status"] == "blocked"
    assert any(e["event"] == "EXTERNAL_ACTION_BLOCKED" and e["action"] == action
               for e in ex.audit)
