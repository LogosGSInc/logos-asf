# -*- coding: utf-8 -*-
"""AG-01: DEMO-MKT-001 governed marketing launch-kit job (local, bounded, demo-safe)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
from swarm import (  # noqa: E402
    SwarmRegistry, build_demo_job, ContainmentController, LocalExecutor,
    ActivationState, supervisor_merge, SupervisorDecision,
)

_SECRET_MARKERS = ["gsk_", "sk-", "GROQ_API_KEY", "ABIGAIL_ADMIN_TOKEN", "Bearer "]


@pytest.fixture
def ran_job(tmp_path):
    job = build_demo_job(workspace_root=str(tmp_path / "runtime" / "jobs"))
    reg = SwarmRegistry()
    for d in job.departments:
        wid, _ = reg.resolve_department_worker(d)
        reg.activate(wid, ActivationState.ACTIVE_SANDBOXED_LOCAL)
    ex = LocalExecutor(reg, ContainmentController(), job.approved_workspace)
    results = ex.run_job(job)
    merge = supervisor_merge(job, results, ex)
    return job, results, merge, ex


def test_all_departments_contribute(ran_job):
    job, results, _, _ = ran_job
    assert len(results) == len(job.departments)
    assert {r.department for r in results} == set(job.departments)
    for r in results:
        assert r.status == "complete"
        assert Path(r.artifact_path).exists()
        assert r.manifest_id and r.packet_id       # bounded by manifest + handoff packet


def test_all_expected_artifacts_created(ran_job):
    job, _, _, _ = ran_job
    base = Path(job.approved_workspace)
    for fname in job.all_expected_files():
        assert (base / fname).exists(), f"missing artifact: {fname}"


def test_supervisor_produces_final_packet(ran_job):
    job, _, merge, _ = ran_job
    assert Path(merge.final_path).name == "final_abigail_launch_packet.md"
    assert Path(merge.final_path).exists()
    text = Path(merge.final_path).read_text()
    assert "approved for demo only" in text.lower()      # honest labeling
    assert "no outbound actions" in text.lower()


def test_final_decision_is_demo_only(ran_job):
    _, _, merge, _ = ran_job
    assert merge.decision == SupervisorDecision.APPROVED_FOR_DEMO_ONLY


def test_audit_summary_is_complete(ran_job):
    job, _, merge, _ = ran_job
    a = json.loads(Path(merge.audit_path).read_text())
    assert a["job_id"] == "DEMO-MKT-001"
    assert a["supervisor"] == "abigail"
    assert a["supervisor_decision"] == SupervisorDecision.APPROVED_FOR_DEMO_ONLY
    assert a["external_actions_performed"] is False
    assert len(a["manifest_ids"]) == len(job.departments)
    assert len(a["handoff_ids"]) == len(job.departments)
    assert set(a["departments"]) == set(job.departments)
    assert "containment_events" in a and "dispatch_events" in a


def test_forbidden_action_appears_as_blocked_state(ran_job):
    job, _, _, ex = ran_job
    ex.attempt_external_action(job, "MKT", "publish")
    blocks = [e for e in ex.audit if e.get("event") == "EXTERNAL_ACTION_BLOCKED"]
    assert blocks and blocks[0]["action"] == "publish"
    assert blocks[0]["decision"] == "blocked"


def test_no_secrets_in_artifacts(ran_job):
    job, _, _, _ = ran_job
    for f in Path(job.approved_workspace).glob("*"):
        content = f.read_text(errors="ignore")
        for marker in _SECRET_MARKERS:
            assert marker not in content, f"{marker} leaked into {f.name}"
