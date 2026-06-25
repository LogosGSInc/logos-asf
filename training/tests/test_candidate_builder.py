"""
TR-01 Candidate Builder — Unit Tests
Covers all five lanes, eligibility rules, security invariants, and
deterministic ID generation.
"""
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from candidate_builder import (
    BUILDER_VERSION,
    MIN_CONFIDENCE,
    G4_MARGINAL_VECTORS,
    check_eligibility,
    check_group_eligibility,
    classify_lane,
    compute_candidate_id,
    compute_source_hashes,
    build_candidate,
    group_by_signature,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _rec(
    vector_id="TAX2:MT-G4-01",
    generation="G4",
    level="C",
    stage="pressure_phase",
    memory_action="quarantine",
    sentinel_source="sentinel_overwatch",
    sentinel_action="block_and_escalate",
    sentinel_reason="DRS=60 authorization required",
    haap_requirement="conditional",
    distortion_type="emotional_exploitation",
    vector_name="Emotional Reasoning Seed Chain",
    confidence=0.95,
    safety_status="store2_analysis_only",
    enforcement_allowed=False,
    store1_write_allowed=False,
    abigail_training_allowed=False,
    recommended_store1_delta=None,
    signature_id=None,
    bd1a_vectors=None,
    phase_q_vectors=None,
    source_taxonomy="TAX2",
    audit_reason="FASDTEST Test Level C",
    turn_span=1,
):
    if signature_id is None:
        signature_id = f"{vector_id.split(':')[1]}-{level}-fc4d9cab"
    return {
        "signature_id": signature_id,
        "vector_id": vector_id,
        "generation": generation,
        "level": level,
        "stage": stage,
        "memory_action": memory_action,
        "sentinel_source": sentinel_source,
        "sentinel_action": sentinel_action,
        "sentinel_reason": sentinel_reason,
        "haap_requirement": haap_requirement,
        "distortion_type": distortion_type,
        "vector_name": vector_name,
        "confidence": confidence,
        "safety_status": safety_status,
        "enforcement_allowed": enforcement_allowed,
        "store1_write_allowed": store1_write_allowed,
        "abigail_training_allowed": abigail_training_allowed,
        "recommended_store1_delta": recommended_store1_delta,
        "bd1a_vectors": bd1a_vectors or ["BD1A:F01", "BD1A:F02"],
        "phase_q_vectors": phase_q_vectors or ["PHASE_Q:Q01"],
        "source_taxonomy": source_taxonomy,
        "audit_reason": audit_reason,
        "turn_span": turn_span,
        "store": "store_2",
        "scope": "analysis_tooling_development",
        "run_id": "20260624T080552Z",
        "loader_version": "2B.1",
        "promotion_status": "review_required",
        "recommended_store1_delta": recommended_store1_delta,
    }


def _group(n=6, **kwargs):
    base = _rec(**kwargs)
    sig = base["signature_id"]
    return [dict(base) for _ in range(n)]


def _candidate(lane="training_candidate", **kwargs):
    group = _group(**kwargs)
    return build_candidate(
        signature_id=group[0]["signature_id"],
        group=group,
        lane=lane,
        run_id="20260624T080552Z",
        loaded_at="2026-06-25T00:00:00+00:00",
    )


# ── check_eligibility: security violations ───────────────────────────────────

def test_enforcement_allowed_true_is_security_violation():
    r = _rec(enforcement_allowed=True)
    _, sv = check_eligibility(r)
    assert sv is not None
    assert "enforcement_allowed" in sv

def test_store1_write_allowed_true_is_security_violation():
    r = _rec(store1_write_allowed=True)
    _, sv = check_eligibility(r)
    assert sv is not None
    assert "store1_write_allowed" in sv

def test_abigail_training_allowed_true_is_security_violation():
    r = _rec(abigail_training_allowed=True)
    _, sv = check_eligibility(r)
    assert sv is not None
    assert "abigail_training_allowed" in sv

def test_recommended_store1_delta_non_null_is_security_violation():
    r = _rec()
    r["recommended_store1_delta"] = {"some": "delta"}
    _, sv = check_eligibility(r)
    assert sv is not None

# ── check_eligibility: provenance rejections ─────────────────────────────────

def test_heuristic_simulation_rejected():
    r = _rec(sentinel_source="heuristic_simulation")
    reason, sv = check_eligibility(r)
    assert sv is None
    assert reason is not None
    assert "heuristic" in reason or "invalid_sentinel_source" in reason

def test_missing_sentinel_source_rejected():
    r = _rec()
    del r["sentinel_source"]
    reason, sv = check_eligibility(r)
    assert sv is None
    assert reason is not None

def test_sentinel_overwatch_accepted():
    r = _rec(sentinel_source="sentinel_overwatch")
    reason, sv = check_eligibility(r)
    assert reason is None
    assert sv is None

def test_invalid_safety_status_rejected():
    r = _rec(safety_status="store1_promoted")
    reason, _ = check_eligibility(r)
    assert reason is not None
    assert "safety_status" in reason

def test_missing_vector_id_rejected():
    r = _rec()
    r["vector_id"] = ""
    reason, _ = check_eligibility(r)
    assert reason is not None

# ── check_group_eligibility: confidence floor ─────────────────────────────────

def test_group_below_confidence_floor_rejected():
    group = _group(confidence=0.72)
    reason, sv = check_group_eligibility("sig", group)
    assert sv is None
    assert reason is not None
    assert "confidence_below_floor" in reason

def test_group_at_confidence_floor_accepted():
    group = _group(confidence=MIN_CONFIDENCE)
    reason, sv = check_group_eligibility("sig", group)
    assert reason is None
    assert sv is None

def test_group_above_confidence_floor_accepted():
    group = _group(confidence=0.95)
    reason, sv = check_group_eligibility("sig", group)
    assert reason is None
    assert sv is None

# ── classify_lane: five lanes ─────────────────────────────────────────────────

def test_g4_marginal_vector_is_evaluator_candidate():
    for vid in G4_MARGINAL_VECTORS:
        for level in ("A", "B", "C", "D"):
            group = _group(vector_id=vid, generation="G4", level=level,
                           memory_action="deny_promotion" if level == "D" else "quarantine")
            assert classify_lane(group) == "evaluator_candidate", f"{vid} Level {level}"

def test_g5_level_d_quarantine_is_tooling_candidate():
    group = _group(generation="G5", level="D", memory_action="deny_promotion",
                   sentinel_action="quarantine",
                   vector_id="TAX2:MT-G5-01")
    assert classify_lane(group) == "tooling_candidate"

def test_g6_level_d_quarantine_is_tooling_candidate():
    group = _group(generation="G6", level="D", memory_action="deny_promotion",
                   sentinel_action="quarantine",
                   vector_id="TAX2:MT-G6-02")
    assert classify_lane(group) == "tooling_candidate"

def test_g4_level_c_quarantine_is_training_candidate():
    group = _group(generation="G4", level="C", memory_action="quarantine",
                   vector_id="TAX2:MT-G4-01")
    assert classify_lane(group) == "training_candidate"

def test_g4_level_d_deny_is_training_candidate():
    group = _group(generation="G4", level="D", memory_action="deny_promotion",
                   sentinel_action="block_and_escalate",
                   vector_id="TAX2:MT-G4-01")
    assert classify_lane(group) == "training_candidate"

def test_g5_level_c_quarantine_is_training_candidate():
    group = _group(generation="G5", level="C", memory_action="quarantine",
                   sentinel_action="block_and_escalate",
                   vector_id="TAX2:MT-G5-01")
    assert classify_lane(group) == "training_candidate"

def test_g6_level_c_is_training_candidate():
    group = _group(generation="G6", level="C", memory_action="quarantine",
                   sentinel_action="quarantine",
                   vector_id="TAX2:MT-G6-02")
    assert classify_lane(group) == "training_candidate"

def test_g5_level_a_is_skill_candidate():
    group = _group(generation="G5", level="A", memory_action="do_not_promote",
                   vector_id="TAX2:MT-G5-01")
    assert classify_lane(group) == "skill_candidate"

def test_g5_level_b_is_skill_candidate():
    group = _group(generation="G5", level="B", memory_action="do_not_promote",
                   vector_id="TAX2:MT-G5-01")
    assert classify_lane(group) == "skill_candidate"

def test_g6_level_a_is_skill_candidate():
    group = _group(generation="G6", level="A", memory_action="do_not_promote",
                   vector_id="TAX2:MT-G6-02")
    assert classify_lane(group) == "skill_candidate"

def test_unknown_pattern_is_doctrine_candidate():
    group = _group(generation="G4", level="A", memory_action="do_not_promote",
                   vector_id="TAX2:MT-G4-01", sentinel_action="flag")
    assert classify_lane(group) == "doctrine_candidate"

# ── compute_candidate_id: deterministic ──────────────────────────────────────

def test_candidate_id_is_deterministic():
    id1 = compute_candidate_id("TAX2:MT-G4-01", "C", "20260624T080552Z", "training_candidate")
    id2 = compute_candidate_id("TAX2:MT-G4-01", "C", "20260624T080552Z", "training_candidate")
    assert id1 == id2

def test_candidate_id_differs_by_lane():
    tc = compute_candidate_id("TAX2:MT-G4-01", "C", "20260624T080552Z", "training_candidate")
    sc = compute_candidate_id("TAX2:MT-G4-01", "C", "20260624T080552Z", "skill_candidate")
    assert tc != sc

def test_candidate_id_differs_by_level():
    id_c = compute_candidate_id("TAX2:MT-G4-01", "C", "20260624T080552Z", "training_candidate")
    id_d = compute_candidate_id("TAX2:MT-G4-01", "D", "20260624T080552Z", "training_candidate")
    assert id_c != id_d

def test_candidate_id_prefix_matches_lane():
    assert compute_candidate_id("TAX2:MT-G4-01", "C", "20260624T080552Z", "training_candidate").startswith("TC-")
    assert compute_candidate_id("TAX2:MT-G5-01", "A", "20260624T080552Z", "skill_candidate").startswith("SC-")
    assert compute_candidate_id("TAX2:MT-G5-01", "D", "20260624T080552Z", "tooling_candidate").startswith("TL-")
    assert compute_candidate_id("TAX2:MT-G4-04", "D", "20260624T080552Z", "evaluator_candidate").startswith("EC-")
    assert compute_candidate_id("TAX2:MT-G4-01", "A", "20260624T080552Z", "doctrine_candidate").startswith("DC-")

def test_candidate_id_date_from_run_id():
    cid = compute_candidate_id("TAX2:MT-G4-01", "C", "20260624T080552Z", "training_candidate")
    assert "20260624" in cid

# ── build_candidate: hard invariants ──────────────────────────────────────────

def test_training_allowed_is_false():
    c = _candidate(lane="training_candidate")
    assert c["training_allowed"] is False

def test_store1_write_allowed_is_false():
    c = _candidate(lane="training_candidate")
    assert c["store1_write_allowed"] is False

def test_runtime_deployment_allowed_is_false():
    c = _candidate(lane="skill_candidate", generation="G5", level="A",
                   memory_action="do_not_promote", vector_id="TAX2:MT-G5-01")
    assert c["runtime_deployment_allowed"] is False

def test_operator_review_required_is_true():
    c = _candidate(lane="training_candidate")
    assert c["operator_review_required"] is True

def test_promotion_status_is_candidate_only():
    c = _candidate(lane="training_candidate")
    assert c["promotion_status"] == "candidate_only"

def test_source_provenance_is_sentinel_overwatch():
    c = _candidate(lane="training_candidate")
    assert c["source_provenance"] == "sentinel_overwatch"

def test_no_harmful_content_in_candidate():
    c = _candidate(lane="training_candidate")
    assert c["safety_labels"]["is_harmful_content"] is False

def test_no_adversarial_payload_in_candidate():
    c = _candidate(lane="training_candidate")
    assert c["safety_labels"]["contains_adversarial_payload"] is False

def test_sentinel_source_verified():
    c = _candidate(lane="training_candidate")
    assert c["safety_labels"]["sentinel_source_verified"] is True

# ── build_candidate: tooling and evaluator lanes ─────────────────────────────

def test_tooling_candidate_also_has_false_invariants():
    c = _candidate(
        lane="tooling_candidate",
        generation="G5", level="D", memory_action="deny_promotion",
        sentinel_action="quarantine", vector_id="TAX2:MT-G5-01",
    )
    assert c["training_allowed"] is False
    assert c["store1_write_allowed"] is False
    assert c["runtime_deployment_allowed"] is False

def test_evaluator_candidate_also_has_false_invariants():
    c = _candidate(
        lane="evaluator_candidate",
        generation="G4", level="D", memory_action="deny_promotion",
        vector_id="TAX2:MT-G4-04",
    )
    assert c["training_allowed"] is False
    assert c["runtime_deployment_allowed"] is False

# ── source_hashes ─────────────────────────────────────────────────────────────

def test_source_hashes_are_sha256():
    group = _group()
    hashes = compute_source_hashes(group)
    assert len(hashes) == 6
    for h in hashes:
        assert len(h["sha256"]) == 64
        assert all(c in "0123456789abcdef" for c in h["sha256"])

def test_source_hashes_are_deterministic():
    group = _group()
    h1 = compute_source_hashes(group)
    h2 = compute_source_hashes(group)
    assert h1 == h2

# ── grouping ──────────────────────────────────────────────────────────────────

def test_group_by_signature_produces_correct_groups():
    records = _group(6, signature_id="SIG-A") + _group(3, signature_id="SIG-B")
    groups = group_by_signature(records)
    assert len(groups) == 2
    assert len(groups["SIG-A"]) == 6
    assert len(groups["SIG-B"]) == 3

# ── no subprocess / no external calls ────────────────────────────────────────

def test_no_subprocess_import():
    import importlib.util, ast
    src = Path(__file__).parent.parent / "candidate_builder.py"
    tree = ast.parse(src.read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    forbidden = {"subprocess", "os.system", "requests", "groq", "openai", "anthropic"}
    for f in forbidden:
        assert f not in imports, f"forbidden import: {f}"

def test_no_eval_or_exec_calls():
    src = (Path(__file__).parent.parent / "candidate_builder.py").read_text()
    for pattern in ["\neval(", "\nexec(", " eval(", " exec("]:
        assert pattern not in src, f"forbidden pattern: {pattern!r}"

def test_no_store1_apply_call():
    src = (Path(__file__).parent.parent / "candidate_builder.py").read_text()
    # Check for actual invocation patterns — field-name references are expected
    assert "store1_apply(" not in src
    assert "run_store1_delta(" not in src
    assert "apply_store1(" not in src
    assert "import store1" not in src

def test_no_training_execution_call():
    src = (Path(__file__).parent.parent / "candidate_builder.py").read_text()
    for pattern in ["fine_tune(", "train(", ".fit(", "training_job.run"]:
        assert pattern not in src, f"forbidden pattern: {pattern!r}"
