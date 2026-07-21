# -*- coding: utf-8 -*-
"""
job_spec.py — AG-01 governed local job specification.

Defines the multi-department job contract and the DEMO-MKT-001 marketing launch-kit
job. Jobs are constrained to local sandbox modes and an approved workspace under
runtime/jobs/. No forbidden external actions are permitted.
"""
import dataclasses
from pathlib import Path


class ContainmentMode:
    RUNNING = "running"
    PAUSED = "paused"
    WRITES_DISABLED = "writes_disabled"
    FULLY_KILLED = "fully_killed"


ALLOWED_JOB_MODES = frozenset({"active_dryrun", "active_sandboxed_local"})

# Actions that are never performed in AG-01 — requesting one yields an explicit block.
FORBIDDEN_ACTIONS = frozenset({
    "publish", "send_email", "ad_spend", "cloud_deploy",
    "network_recon", "external_action", "db_mutation",
})


@dataclasses.dataclass
class JobSpec:
    job_id: str
    title: str
    description: str
    approved_workspace: str
    departments: list
    department_tasks: dict          # dept -> bounded task string
    expected_artifacts: dict        # dept -> artifact filename
    mode: str = "active_sandboxed_local"

    def __post_init__(self):
        if self.mode not in ALLOWED_JOB_MODES:
            raise ValueError(f"job mode must be one of {sorted(ALLOWED_JOB_MODES)}, got {self.mode!r}")
        parts = Path(self.approved_workspace).parts
        if "runtime" not in parts or "jobs" not in parts:
            raise ValueError("approved_workspace must be under runtime/jobs/")
        missing = [d for d in self.departments if d not in self.department_tasks]
        if missing:
            raise ValueError(f"departments missing a bounded task: {missing}")

    def artifact_for(self, dept):
        return self.expected_artifacts.get(dept)

    def all_expected_files(self):
        """Every artifact the job should yield: per-department + supervisor merge outputs."""
        return sorted(set(self.expected_artifacts.values())) + [
            "final_abigail_launch_packet.md", "audit_summary.json",
        ]


# ── DEMO-MKT-001 — Abigail governed launch kit (demo-safe, no outbound actions) ──
DEMO_DEPARTMENT_TASKS = {
    "EXE": "Define mission, buyer, decision criteria, and final business objective.",
    "PRD": "Define product promise, pain, wedge use case, and MVP boundary.",
    "MKT": "Create campaign angles, ad themes, content hooks, and brand narrative.",
    "REV": "Create sales motion, discovery questions, objections, and pilot close path.",
    "LGL": "Review claims, disclaimers, prohibited language, and customer-facing risk.",
    "FIN": "Draft pricing hypothesis, cost assumptions, pilot economics, and margin notes.",
    "SEC": "Review prompt-injection risk, security claims, and unsafe automation promises.",
    "GRC": "Map visible controls to governance language and audit-readiness claims.",
    "OPS": "Create launch checklist, owner map, handoff process, and delivery sequence.",
    "ENG": "Prepare local build/demo artifact plan, static landing-page stub, or implementation notes.",
    "DAT": "Define funnel metrics, telemetry requirements, and success criteria.",
    "HR": "Define operator roles, approval responsibilities, and internal SOP language for outreach.",
}

# 1:1 department -> artifact (uses every content filename in the AG-01 spec).
DEMO_ARTIFACTS = {
    "EXE": "executive_brief.md",
    "PRD": "product_positioning.md",
    "MKT": "ad_campaign_angles.md",
    "REV": "sales_discovery_script.md",
    "LGL": "legal_claims_review.md",
    "FIN": "pricing_hypothesis.md",
    "SEC": "security_posture_one_pager.md",
    "GRC": "governance_control_map.md",
    "OPS": "operations_checklist.md",
    "ENG": "landing_page_copy.md",
    "DAT": "metrics_plan.md",
    "HR": "outreach_email_drafts.md",
}

DEMO_DEPARTMENTS = ["EXE", "PRD", "MKT", "REV", "LGL", "FIN", "SEC", "GRC", "OPS", "ENG", "DAT", "HR"]


def build_demo_job(workspace_root="runtime/jobs", mode="active_sandboxed_local"):
    return JobSpec(
        job_id="DEMO-MKT-001",
        title="Build Abigail Governed AI Workflow Pilot Launch Kit",
        description=("Create a demo-safe marketing and advertising launch kit for Abigail "
                     "without publishing, sending, spending, or contacting anyone."),
        approved_workspace=f"{workspace_root}/DEMO-MKT-001",
        departments=list(DEMO_DEPARTMENTS),
        department_tasks=dict(DEMO_DEPARTMENT_TASKS),
        expected_artifacts=dict(DEMO_ARTIFACTS),
        mode=mode,
    )
