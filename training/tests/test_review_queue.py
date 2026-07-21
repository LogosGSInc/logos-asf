"""
TR-02 Review Queue — Unit Tests
Covers all seven review actions, operator identity requirements, state machine
transitions, immutability, append-only log, deterministic hashes, and invariants.
"""
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from review_queue import (
    ReviewQueue,
    VALID_LANES,
    LANE_APPROVED_STATES,
    TERMINAL_STATUSES,
    APPROVE_FROM,
    _decision_hash,
    _decision_id,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _candidate(cid="TC-20260625-aabbccdd", lane="training_candidate",
               confidence=0.95, version=1):
    return {
        "candidate_id":               cid,
        "schema_version":             "1.0.0",
        "candidate_version":          version,
        "candidate_lane":             lane,
        "source_store2_ids":          ["tr01_20260625T000000Z"],
        "source_session_ids":         ["20260625T000000Z"],
        "source_signature_ids":       ["MT-G4-01-C-fc4d9cab"],
        "source_provenance":          "sentinel_overwatch",
        "source_hashes":              [{"signature_id": "MT-G4-01-C-fc4d9cab",
                                        "sha256": "a" * 64}],
        "task_type":                  "refusal_correct",
        "title":                      "Test candidate",
        "summary":                    "Test summary",
        "problem_observed":           "Test problem",
        "proposed_improvement":       "Test improvement",
        "evidence": {
            "generation":    "G4",
            "vector_id":     "TAX2:MT-G4-01",
            "vector_name":   "Test Vector",
            "level":         "C",
            "stage":         "pressure_phase",
            "distortion_type": "emotional_exploitation",
            "sentinel_action": "block_and_escalate",
            "sentinel_reason": "DRS=60",
            "haap_requirement": "conditional",
            "memory_action": "quarantine",
            "bd1a_vectors":  ["BD1A:F01"],
            "phase_q_vectors": ["PHASE_Q:Q01"],
            "turn_count":    6,
            "source_taxonomy": "TAX2",
            "audit_reason":  "Level C test",
        },
        "confidence":                 confidence,
        "safety_labels": {
            "is_harmful_content":                  False,
            "contains_adversarial_payload":        False,
            "contains_credentials":                False,
            "contains_evaluation_instrument_content": False,
            "sentinel_source_verified":            True,
        },
        "privacy_labels": {
            "contains_pii":            False,
            "contains_user_derived_data": False,
            "redaction_required":      False,
        },
        "redaction_log":              [],
        "duplicate_group":            None,
        "operator_review_required":   True,
        "promotion_status":           "candidate_only",
        "training_allowed":           False,
        "store1_write_allowed":       False,
        "runtime_deployment_allowed": False,
        "created_at":                 "2026-06-25T00:00:00+00:00",
        "builder_version":            "candidate_builder:1.0.0",
    }


def _write_candidates(path: Path, candidates: list) -> None:
    path.write_text("\n".join(json.dumps(c) for c in candidates) + "\n")


@pytest.fixture
def rq(tmp_path):
    """Return a ReviewQueue pointed at tmp_path, with a single TC candidate."""
    cands_path = tmp_path / "candidates.jsonl"
    c = _candidate()
    _write_candidates(cands_path, [c])
    out = tmp_path / "out"
    return ReviewQueue(cands_path, out), cands_path, out, c


def _queue_with_lanes(tmp_path, lanes):
    """Build a ReviewQueue with one candidate per lane."""
    prefix_map = {
        "training_candidate":  "TC",
        "skill_candidate":     "SC",
        "tooling_candidate":   "TL",
        "evaluator_candidate": "EC",
        "doctrine_candidate":  "DC",
    }
    candidates = [
        _candidate(cid=f"{prefix_map[lane]}-20260625-000000{i:02d}", lane=lane)
        for i, lane in enumerate(lanes)
    ]
    cands_path = tmp_path / "candidates.jsonl"
    _write_candidates(cands_path, candidates)
    out = tmp_path / "out"
    q = ReviewQueue(cands_path, out)
    return q, candidates


# ── approve: all five lanes ───────────────────────────────────────────────────

@pytest.mark.parametrize("lane,expected_status", LANE_APPROVED_STATES.items())
def test_approve_lane_produces_correct_pending_status(tmp_path, lane, expected_status):
    prefix = {"training_candidate":"TC","skill_candidate":"SC","tooling_candidate":"TL",
              "evaluator_candidate":"EC","doctrine_candidate":"DC"}[lane]
    cid = f"{prefix}-20260625-aaaaaaaa"
    c = _candidate(cid=cid, lane=lane)
    cands_path = tmp_path / "c.jsonl"
    _write_candidates(cands_path, [c])
    q = ReviewQueue(cands_path, tmp_path / "out")
    cands = q.load_candidates()
    q.cmd_approve(cands, [], cid, "op1", "governance_lead",
                  f"evidence reviewed, approving {lane}")
    decisions = q.load_decisions()
    assert len(decisions) == 1
    assert decisions[0]["resulting_status"] == expected_status


def test_approve_training_candidate_leaves_training_allowed_false(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_approve(cands, [], c["candidate_id"], "op1", "governance_lead", "approved")
    decisions = q.load_decisions()
    assert decisions[0]["training_allowed"] is False


def test_approve_leaves_store1_write_allowed_false(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_approve(cands, [], c["candidate_id"], "op1", "governance_lead", "approved")
    decisions = q.load_decisions()
    assert decisions[0]["store1_write_allowed"] is False


def test_approve_leaves_runtime_deployment_allowed_false(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_approve(cands, [], c["candidate_id"], "op1", "governance_lead", "approved")
    decisions = q.load_decisions()
    assert decisions[0]["runtime_deployment_allowed"] is False


# ── reject ────────────────────────────────────────────────────────────────────

def test_reject_sets_operator_rejected(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_reject(cands, [], c["candidate_id"], "op1", "governance_lead", "not useful")
    decisions = q.load_decisions()
    assert decisions[0]["resulting_status"] == "operator_rejected"


def test_reject_training_allowed_stays_false(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_reject(cands, [], c["candidate_id"], "op1", "governance_lead", "rejected")
    assert q.load_decisions()[0]["training_allowed"] is False


# ── redact ────────────────────────────────────────────────────────────────────

def test_redact_creates_new_version_file(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_redact(cands, [], c["candidate_id"], "op1", "governance_lead",
                 "remove phrasing", ["summary"])
    revised_files = list((out / "revised").glob("*.json"))
    assert len(revised_files) == 1


def test_redact_original_candidate_unchanged(rq):
    q, cands_path, out, c = rq
    original_bytes = cands_path.read_bytes()
    cands = q.load_candidates()
    q.cmd_redact(cands, [], c["candidate_id"], "op1", "governance_lead",
                 "remove phrasing", ["summary"])
    assert cands_path.read_bytes() == original_bytes


def test_redact_field_value_is_redacted_marker(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_redact(cands, [], c["candidate_id"], "op1", "governance_lead",
                 "redact", ["summary"])
    revised_path = list((out / "revised").glob("*.json"))[0]
    revised = json.loads(revised_path.read_text())
    assert revised["summary"] == "[REDACTED]"


def test_redact_increments_candidate_version(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_redact(cands, [], c["candidate_id"], "op1", "governance_lead",
                 "redact", ["summary"])
    revised_path = list((out / "revised").glob("*.json"))[0]
    revised = json.loads(revised_path.read_text())
    assert revised["candidate_version"] == 2


def test_redact_revised_candidate_has_candidate_only_status(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_redact(cands, [], c["candidate_id"], "op1", "governance_lead",
                 "redact", ["summary"])
    revised_path = list((out / "revised").glob("*.json"))[0]
    revised = json.loads(revised_path.read_text())
    assert revised["promotion_status"] == "candidate_only"


def test_redact_resulting_status_is_changes_requested(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_redact(cands, [], c["candidate_id"], "op1", "governance_lead",
                 "redact", ["summary"])
    assert q.load_decisions()[0]["resulting_status"] == "changes_requested"


def test_redact_invariants_hold_on_revised(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_redact(cands, [], c["candidate_id"], "op1", "governance_lead",
                 "redact", ["problem_observed"])
    revised_path = list((out / "revised").glob("*.json"))[0]
    revised = json.loads(revised_path.read_text())
    assert revised["training_allowed"] is False
    assert revised["store1_write_allowed"] is False
    assert revised["runtime_deployment_allowed"] is False
    assert revised["operator_review_required"] is True


def test_redact_then_approve_v2_succeeds(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    cid = c["candidate_id"]
    q.cmd_redact(cands, [], cid, "op1", "governance_lead", "redact", ["summary"])
    decisions1 = q.load_decisions()
    state = q.compute_state(cands, decisions1)
    assert state[cid]["current_version"] == 2
    assert state[cid]["promotion_status"] == "candidate_only"
    q.cmd_approve(cands, decisions1, cid, "op1", "governance_lead", "approved v2")
    decisions2 = q.load_decisions()
    assert decisions2[-1]["resulting_status"] == "dataset_promotion_pending"
    assert decisions2[-1]["candidate_version"] == 2


# ── rewrite ───────────────────────────────────────────────────────────────────

def test_rewrite_creates_revised_candidate(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_rewrite(cands, [], c["candidate_id"], "op1", "governance_lead",
                  "improve title", {"title": "New title"})
    revised_path = list((out / "revised").glob("*.json"))[0]
    revised = json.loads(revised_path.read_text())
    assert revised["title"] == "New title"


def test_rewrite_original_unchanged(rq):
    q, cands_path, out, c = rq
    original_bytes = cands_path.read_bytes()
    cands = q.load_candidates()
    q.cmd_rewrite(cands, [], c["candidate_id"], "op1", "governance_lead",
                  "improve", {"title": "Better title"})
    assert cands_path.read_bytes() == original_bytes


def test_rewrite_invariant_field_fails(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    with pytest.raises(SystemExit):
        q.cmd_rewrite(cands, [], c["candidate_id"], "op1", "governance_lead",
                      "try to enable training", {"training_allowed": True})


def test_rewrite_promotion_status_invariant(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    with pytest.raises(SystemExit):
        q.cmd_rewrite(cands, [], c["candidate_id"], "op1", "governance_lead",
                      "try to promote", {"promotion_status": "dataset_promotion_pending"})


# ── reclassify ────────────────────────────────────────────────────────────────

def test_reclassify_creates_candidate_in_new_lane(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_reclassify(cands, [], c["candidate_id"], "op1", "governance_lead",
                     "better fit as skill", "skill_candidate")
    revised_files = list((out / "revised").glob("*.json"))
    assert len(revised_files) == 1
    revised = json.loads(revised_files[0].read_text())
    assert revised["candidate_lane"] == "skill_candidate"
    assert revised["candidate_id"].startswith("SC-")


def test_reclassify_original_unchanged(rq):
    q, cands_path, out, c = rq
    original_bytes = cands_path.read_bytes()
    cands = q.load_candidates()
    q.cmd_reclassify(cands, [], c["candidate_id"], "op1", "governance_lead",
                     "reclassify", "skill_candidate")
    assert cands_path.read_bytes() == original_bytes


def test_reclassify_same_lane_fails(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    with pytest.raises(SystemExit):
        q.cmd_reclassify(cands, [], c["candidate_id"], "op1", "governance_lead",
                         "no change", "training_candidate")


def test_reclassify_invalid_lane_fails(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    with pytest.raises(SystemExit):
        q.cmd_reclassify(cands, [], c["candidate_id"], "op1", "governance_lead",
                         "bad lane", "deployment_candidate")


def test_reclassify_original_becomes_changes_requested(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    cid = c["candidate_id"]
    q.cmd_reclassify(cands, [], cid, "op1", "governance_lead", "reclassify", "skill_candidate")
    decisions = q.load_decisions()
    state = q.compute_state(cands, decisions)
    assert state[cid]["promotion_status"] == "changes_requested"


def test_reclassify_new_candidate_starts_candidate_only(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_reclassify(cands, [], c["candidate_id"], "op1", "governance_lead",
                     "reclassify", "skill_candidate")
    revised_files = list((out / "revised").glob("*.json"))
    revised = json.loads(revised_files[0].read_text())
    assert revised["promotion_status"] == "candidate_only"
    assert revised["training_allowed"] is False


# ── merge ─────────────────────────────────────────────────────────────────────

def test_merge_creates_combined_candidate(tmp_path):
    q, candidates = _queue_with_lanes(tmp_path, ["training_candidate", "training_candidate"])
    cands = q.load_candidates()
    ids = [c["candidate_id"] for c in candidates]
    q.cmd_merge(cands, [], ids, "op1", "governance_lead", "merge related candidates")
    revised_files = list((tmp_path / "out" / "revised").glob("*.json"))
    assert len(revised_files) == 1
    merged = json.loads(revised_files[0].read_text())
    assert set(merged["source_candidate_ids"]) == set(ids)


def test_merge_writes_one_decision_per_source(tmp_path):
    q, candidates = _queue_with_lanes(tmp_path, ["training_candidate", "skill_candidate"])
    cands = q.load_candidates()
    ids = [c["candidate_id"] for c in candidates]
    q.cmd_merge(cands, [], ids, "op1", "governance_lead", "merge")
    decisions = q.load_decisions()
    assert len(decisions) == 2


def test_merge_sources_become_changes_requested(tmp_path):
    q, candidates = _queue_with_lanes(tmp_path, ["training_candidate", "training_candidate"])
    cands = q.load_candidates()
    ids = [c["candidate_id"] for c in candidates]
    q.cmd_merge(cands, [], ids, "op1", "governance_lead", "merge")
    decisions = q.load_decisions()
    state = q.compute_state(cands, decisions)
    for cid in ids:
        assert state[cid]["promotion_status"] == "changes_requested"


def test_merge_requires_two_or_more_ids(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    with pytest.raises(SystemExit):
        q.cmd_merge(cands, [], [c["candidate_id"]], "op1", "governance_lead", "just one")


def test_merge_invariants_in_merged_candidate(tmp_path):
    q, candidates = _queue_with_lanes(tmp_path, ["training_candidate", "training_candidate"])
    cands = q.load_candidates()
    ids = [c["candidate_id"] for c in candidates]
    q.cmd_merge(cands, [], ids, "op1", "governance_lead", "merge")
    revised_files = list((tmp_path / "out" / "revised").glob("*.json"))
    merged = json.loads(revised_files[0].read_text())
    assert merged["training_allowed"] is False
    assert merged["store1_write_allowed"] is False
    assert merged["runtime_deployment_allowed"] is False
    assert merged["operator_review_required"] is True


# ── request_more_evidence ─────────────────────────────────────────────────────

def test_request_more_evidence_sets_evidence_required(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_request_more_evidence(cands, [], c["candidate_id"], "op1", "governance_lead",
                                "need more G5 runs")
    decisions = q.load_decisions()
    assert decisions[0]["resulting_status"] == "evidence_required"


def test_evidence_required_candidate_can_be_approved_after(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    cid = c["candidate_id"]
    q.cmd_request_more_evidence(cands, [], cid, "op1", "governance_lead", "need evidence")
    decisions1 = q.load_decisions()
    q.cmd_approve(cands, decisions1, cid, "op1", "governance_lead", "evidence reviewed, now approved")
    decisions2 = q.load_decisions()
    assert decisions2[-1]["resulting_status"] == "dataset_promotion_pending"


# ── operator identity ─────────────────────────────────────────────────────────

def test_missing_operator_id_fails_on_approve(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    with pytest.raises(SystemExit):
        q.cmd_approve(cands, [], c["candidate_id"], "", "governance_lead", "approved")


def test_missing_operator_role_fails_on_approve(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    with pytest.raises(SystemExit):
        q.cmd_approve(cands, [], c["candidate_id"], "op1", "", "approved")


def test_missing_operator_id_fails_on_reject(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    with pytest.raises(SystemExit):
        q.cmd_reject(cands, [], c["candidate_id"], "", "governance_lead", "rejected")


def test_missing_operator_id_fails_on_redact(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    with pytest.raises(SystemExit):
        q.cmd_redact(cands, [], c["candidate_id"], "", "role", "reason", ["title"])


# ── state machine: transitions ────────────────────────────────────────────────

def test_approve_after_reject_fails(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    cid = c["candidate_id"]
    q.cmd_reject(cands, [], cid, "op1", "governance_lead", "rejected")
    decisions1 = q.load_decisions()
    with pytest.raises(SystemExit):
        q.cmd_approve(cands, decisions1, cid, "op1", "governance_lead", "try to approve anyway")


def test_approve_after_approve_fails(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    cid = c["candidate_id"]
    q.cmd_approve(cands, [], cid, "op1", "governance_lead", "first approval")
    decisions1 = q.load_decisions()
    with pytest.raises(SystemExit):
        q.cmd_approve(cands, decisions1, cid, "op2", "governance_lead", "second approval")


def test_reject_after_reject_fails(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    cid = c["candidate_id"]
    q.cmd_reject(cands, [], cid, "op1", "governance_lead", "rejected")
    decisions1 = q.load_decisions()
    with pytest.raises(SystemExit):
        q.cmd_reject(cands, decisions1, cid, "op1", "governance_lead", "rejected again")


def test_reclassify_after_approve_fails(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    cid = c["candidate_id"]
    q.cmd_approve(cands, [], cid, "op1", "governance_lead", "approved")
    decisions1 = q.load_decisions()
    with pytest.raises(SystemExit):
        q.cmd_reclassify(cands, decisions1, cid, "op1", "governance_lead",
                         "try to reclassify after approve", "skill_candidate")


def test_duplicate_approval_same_version_fails(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    cid = c["candidate_id"]
    q.cmd_approve(cands, [], cid, "op1", "governance_lead", "first")
    decisions1 = q.load_decisions()
    with pytest.raises(SystemExit):
        q._check_no_duplicate_approve(cid, 1, decisions1)


# ── decision hash ──────────────────────────────────────────────────────────────

def test_decision_hash_is_deterministic(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_approve(cands, [], c["candidate_id"], "op1", "governance_lead", "approved")
    d = q.load_decisions()[0]
    # Recompute hash
    expected = _decision_hash(d)
    assert d["decision_hash"] == expected


def test_tampered_decision_hash_fails_on_load(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_approve(cands, [], c["candidate_id"], "op1", "governance_lead", "approved")
    # Tamper with the log
    log = q.decisions_log.read_text()
    d = json.loads(log.strip())
    d["reason"] = "TAMPERED"
    q.decisions_log.write_text(json.dumps(d) + "\n")
    with pytest.raises(SystemExit):
        q.load_decisions()


# ── append-only log ───────────────────────────────────────────────────────────

def test_decision_log_is_append_only(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    cid = c["candidate_id"]
    q.cmd_request_more_evidence(cands, [], cid, "op1", "governance_lead", "need evidence")
    decisions1 = q.load_decisions()
    assert len(decisions1) == 1

    q.cmd_approve(cands, decisions1, cid, "op1", "governance_lead", "approved after evidence")
    decisions2 = q.load_decisions()
    assert len(decisions2) == 2
    # First decision must still be present unchanged
    assert decisions2[0]["decision_id"] == decisions1[0]["decision_id"]


def test_decisions_are_attributable(rq):
    q, cands_path, out, c = rq
    cands = q.load_candidates()
    q.cmd_approve(cands, [], c["candidate_id"], "Alice", "governance_lead", "approved")
    d = q.load_decisions()[0]
    assert d["operator_id"] == "Alice"
    assert d["operator_role"] == "governance_lead"


# ── source file immutability ──────────────────────────────────────────────────

def test_source_candidates_byte_identical_after_all_actions(tmp_path):
    """Run all seven decision types and confirm source JSONL never changes."""
    q, candidates = _queue_with_lanes(tmp_path, [
        "training_candidate", "training_candidate", "skill_candidate",
        "tooling_candidate", "evaluator_candidate", "doctrine_candidate",
    ])
    cands_path = tmp_path / "candidates.jsonl"
    original_bytes = cands_path.read_bytes()
    cands = q.load_candidates()
    ids = [c["candidate_id"] for c in candidates]

    q.cmd_approve(cands, [], ids[0], "op1", "role1", "approve TC")
    d1 = q.load_decisions()
    q.cmd_reject(cands, d1, ids[1], "op1", "role1", "reject TC")
    d2 = q.load_decisions()
    q.cmd_redact(cands, d2, ids[2], "op1", "role1", "redact SC", ["title"])
    d3 = q.load_decisions()
    q.cmd_reclassify(cands, d3, ids[3], "op1", "role1", "reclassify TL", "doctrine_candidate")
    d4 = q.load_decisions()
    q.cmd_request_more_evidence(cands, d4, ids[4], "op1", "role1", "need evidence EC")
    d5 = q.load_decisions()
    # Merge two non-terminal candidates (ids[5] is DC, still candidate_only)
    # ids[0] is terminal — confirmed blocked in test_approve_after_approve_fails
    # Use a separate queue for the merge to keep ids[5] non-terminal
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    q2, candidates2 = _queue_with_lanes(fresh, ["training_candidate", "training_candidate"])
    cands_path2 = fresh / "candidates.jsonl"
    original_bytes2 = cands_path2.read_bytes()
    cands2 = q2.load_candidates()
    ids2 = [c["candidate_id"] for c in candidates2]
    q2.cmd_merge(cands2, [], ids2, "op1", "role1", "merge two TCs")
    assert cands_path2.read_bytes() == original_bytes2

    # Primary assertion: source bytes unchanged after all 5 actions on q
    assert cands_path.read_bytes() == original_bytes


# ── out-dir security ──────────────────────────────────────────────────────────

def test_out_dir_inside_repo_is_rejected(tmp_path):
    from review_queue import REPO_ROOT
    cands_path = tmp_path / "c.jsonl"
    _write_candidates(cands_path, [_candidate()])
    with pytest.raises(SystemExit):
        ReviewQueue(cands_path, REPO_ROOT / "training" / "review_output")


def test_missing_candidates_file_fails(tmp_path):
    with pytest.raises(SystemExit):
        q = ReviewQueue(tmp_path / "nonexistent.jsonl", tmp_path / "out")
        q.load_candidates()


# ── candidate invariant violations on load ────────────────────────────────────

def test_training_allowed_true_in_candidate_fails_on_load(tmp_path):
    c = _candidate()
    c["training_allowed"] = True
    cands_path = tmp_path / "c.jsonl"
    _write_candidates(cands_path, [c])
    q = ReviewQueue(cands_path, tmp_path / "out")
    with pytest.raises(SystemExit):
        q.load_candidates()


def test_store1_write_allowed_true_in_candidate_fails_on_load(tmp_path):
    c = _candidate()
    c["store1_write_allowed"] = True
    cands_path = tmp_path / "c.jsonl"
    _write_candidates(cands_path, [c])
    q = ReviewQueue(cands_path, tmp_path / "out")
    with pytest.raises(SystemExit):
        q.load_candidates()


def test_runtime_deployment_allowed_true_in_candidate_fails_on_load(tmp_path):
    c = _candidate()
    c["runtime_deployment_allowed"] = True
    cands_path = tmp_path / "c.jsonl"
    _write_candidates(cands_path, [c])
    q = ReviewQueue(cands_path, tmp_path / "out")
    with pytest.raises(SystemExit):
        q.load_candidates()


# ── no subprocess / forbidden patterns ───────────────────────────────────────

def test_no_subprocess_or_external_import():
    import ast
    src = (Path(__file__).parent.parent / "review_queue.py").read_text()
    tree = ast.parse(src)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    forbidden = {"subprocess", "requests", "groq", "openai", "anthropic", "urllib"}
    for f in forbidden:
        assert f not in imports, f"forbidden import: {f}"


def test_no_eval_or_exec_in_source():
    src = (Path(__file__).parent.parent / "review_queue.py").read_text()
    for pattern in ["\neval(", " eval(", "\nexec(", " exec("]:
        assert pattern not in src, f"forbidden pattern found: {pattern!r}"


def test_no_store1_apply_in_source():
    src = (Path(__file__).parent.parent / "review_queue.py").read_text()
    assert "store1_apply(" not in src
    assert "apply_store1(" not in src
    assert "import store1" not in src


def test_no_training_execution_in_source():
    src = (Path(__file__).parent.parent / "review_queue.py").read_text()
    for pattern in ["fine_tune(", ".fit(", "training_job.run", "lora_train"]:
        assert pattern not in src, f"forbidden pattern found: {pattern!r}"
