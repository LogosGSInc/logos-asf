# -*- coding: utf-8 -*-
"""
swarm — LOGOS Governance Systems Inc. — Abigail CP-00 Governed Local Swarm (AG-01)

Activates the authored agent registry into a *governed, local, bounded* execution
harness. Not autonomous. Not networked. Not production. Workers produce local draft
artifacts only, under Abigail's supervision, bounded by MM-01 routing manifests +
scoped handoff packets, the MM-03 approval gate, the SEC-02 cost gate, external
containment/kill-switch control, and an approved workspace.

Truth-in-labeling: any capability claim must map to the verified activation state
achieved by tests. See docs/AG01_GOVERNED_LOCAL_SWARM_ACTIVATION.md.
"""
from .registry import SwarmRegistry, AgentRecord, ActivationState, FORBIDDEN_MODES
from .job_spec import (
    JobSpec, ContainmentMode, FORBIDDEN_ACTIONS, ALLOWED_JOB_MODES,
    build_demo_job, DEMO_DEPARTMENT_TASKS, DEMO_ARTIFACTS,
)
from .local_executor import (
    ContainmentController, LocalExecutor, SwarmDenied, DeptResult,
    execute_worker, default_cost_gate, default_approval_gate,
)
from .merge import supervisor_merge, SupervisorDecision, MergeResult

__all__ = [
    "SwarmRegistry", "AgentRecord", "ActivationState", "FORBIDDEN_MODES",
    "JobSpec", "ContainmentMode", "FORBIDDEN_ACTIONS", "ALLOWED_JOB_MODES",
    "build_demo_job", "DEMO_DEPARTMENT_TASKS", "DEMO_ARTIFACTS",
    "ContainmentController", "LocalExecutor", "SwarmDenied", "DeptResult",
    "execute_worker", "default_cost_gate", "default_approval_gate",
    "supervisor_merge", "SupervisorDecision", "MergeResult",
]
