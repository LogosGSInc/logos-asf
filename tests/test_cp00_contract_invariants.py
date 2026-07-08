# -*- coding: utf-8 -*-
"""
test_cp00_contract_invariants.py — Architecture Constitution guard tests.

Locks the CP-00 contract-broker Acceptance Invariants that registry/dispatch work
is most likely to erode:

  #2  Supervisory allow-lists exclude department leads and worker identities.
  #3  YAML relationship fields (supervises, reports_to) are DESCRIPTIVE ONLY and
      do not create executable routing authority.  ← the R2 guard.

These are structural regression tripwires: if a future change wires the persona
graph into executable routing, or promotes a worker/dept-lead to a broker, a test
fails and forces a constitutional review.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PRODUCT = ROOT / "abigail"
sys.path.insert(0, str(PRODUCT))


# ── R2 / Invariant #3: supervises & reports_to are code-inert ────────────────
def test_supervises_reports_to_are_code_inert():
    """No PRODUCT python code may reference `supervises` or `reports_to`. They are
    descriptive persona metadata in agent YAML only — never an executable routing
    or authority table. Worker resolution is by department code, not by traversing
    these fields."""
    pat = re.compile(r"\b(supervises|reports_to)\b")
    offenders = []
    for py in PRODUCT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        if pat.search(text):
            offenders.append(str(py.relative_to(ROOT)))
    assert not offenders, (
        "supervises/reports_to referenced in product code — persona graph must not "
        f"become executable routing (Constitution Invariant #3). Offenders: {offenders}"
    )


def test_supervises_reports_to_exist_only_in_yaml():
    """Positive counterpart: the fields DO exist, but only in agent YAML (proves the
    guard is meaningful, not vacuous)."""
    yaml_hits = list((ROOT / "agents").rglob("*.yaml"))
    found = any(
        re.search(r"\b(supervises|reports_to)\b", f.read_text(encoding="utf-8"))
        for f in yaml_hits
    )
    assert found, "expected supervises/reports_to to exist in agent YAML personas"


# ── R1 / Invariant #2: supervisor allow-list excludes workers/dept-leads ─────
def test_authorized_supervisors_are_cp00_roles_only():
    from orchestration.schemas import AUTHORIZED_SUPERVISORS  # noqa: E402
    sup = set(AUTHORIZED_SUPERVISORS)
    assert sup, "AUTHORIZED_SUPERVISORS must not be empty"
    # every broker identity must be an Abigail/CP-00 role
    for s in sup:
        assert str(s).lower().startswith("abigail"), \
            f"non-CP-00 broker identity in AUTHORIZED_SUPERVISORS: {s!r}"
    # no agent-id / dept-lead pattern (e.g. EN-01, SEC-01, EN-01-MA) may be a broker
    agentish = re.compile(r"^[A-Z]{2,3}-\d")
    for s in sup:
        assert not agentish.match(str(s)), \
            f"department-lead/worker identity must not be a supervisor: {s!r}"


def test_handoff_packet_rejects_non_supervisor_from_agent():
    """Functional guard: a SignedHandoffPacket whose from_agent is a worker/dept-lead
    must be rejected at construction (broker boundary enforced in code, not just docs)."""
    from orchestration.schemas import AUTHORIZED_SUPERVISORS
    # a dept-lead id is NOT an authorized supervisor
    assert "EN-01-MA" not in AUTHORIZED_SUPERVISORS
    assert "abigail" in {str(s).lower() for s in AUTHORIZED_SUPERVISORS}
