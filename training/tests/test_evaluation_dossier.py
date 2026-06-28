"""
TR-06E: tests for EVALUATION_DOSSIER.schema.json and evaluation_dossier.py.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training.evaluation_harness import (
    build_evaluation_report,
    compute_lineage_hash,
    run_all_metadata_gates,
)
from training.live_eval_interface import (
    build_default_cases_for_candidate,
    build_live_eval_plan,
)
from training.local_eval_adapter_harness import execute_plan_with_stub_adapter

from training.evaluation_dossier import (
    REQUIRED_DOSSIER_FIELDS,
    EvaluationDossierError,
    EvaluationDossierInputError,
    EvaluationDossierValidationError,
    assert_dossier_cannot_promote,
    build_evaluation_dossier,
    classify_readiness,
    compute_dossier_hash,
    load_evaluation_dossier,
    save_evaluation_dossier,
    summarize_evaluation_dossier,
    summarize_metadata_reports,
    summarize_stub_execution_reports,
    validate_evaluation_dossier,
)

DOSSIER_SCHEMA_PATH = Path(__file__).parent.parent / "EVALUATION_DOSSIER.schema.json"

_AID = "MA-tr06e-test-00001"
_AID2 = "MA-tr06e-test-00002"


# ---------------------------------------------------------------------------
# Fixture factories
# ---------------------------------------------------------------------------

def _make_candidate(artifact_id: str = _AID) -> dict:
    lin = {
        "artifact_id": artifact_id,
        "artifact_type": "model_candidate",
        "dep_keystone_ingress_refs": ["dk-ingress-001"],
        "dep_keystone_evidence_sha256_refs": ["a" * 64],
        "dep_keystone_verification_report_refs": ["dk-verify-001"],
        "source_registry_refs": ["sr-001"],
        "clearance_ledger_refs": ["cl-001"],
        "dataset_manifest_refs": ["dm-001"],
        "dry_run_envelope_refs": ["dre-001"],
    }
    lin["lineage_hash"] = compute_lineage_hash(lin)
    return {
        "artifact_id":                      artifact_id,
        "model_artifact_id":                artifact_id,
        "artifact_type":                    "model_candidate",
        "promotion_status":                 "not_promoted",
        "training_allowed":                 False,
        "model_weights_present":            False,
        "runtime_deployment_allowed":       False,
        "store1_write_allowed":             False,
        "external_calls_allowed":           False,
        "govsec_doctrine_version":          "1.0",
        "govsec_constitutional_fidelity_required": True,
        "govsec_haap_refusal_behavior_required":   True,
        "dep_keystone_provenance_complete":         True,
        "dep_keystone_ingress_refs":                ["dk-ingress-001"],
        "dep_keystone_evidence_sha256_refs":        ["a" * 64],
        "dep_keystone_verification_report_refs":    ["dk-verify-001"],
        "source_registry_refs":             ["sr-001"],
        "source_clearances_complete":       True,
        "clearance_ledger_refs":            ["cl-001"],
        "dry_run_complete":                 True,
        "dry_run_envelope_refs":            ["dre-001"],
        "lineage":                          lin,
        "notes":                            "TR-06E test candidate",
    }


def _make_metadata_reports(artifact_id: str = _AID) -> list:
    """Run all 11 TR-06A gates and return one report per gate."""
    c = _make_candidate(artifact_id)
    gate_results = run_all_metadata_gates(c)
    return [build_evaluation_report(c, gr) for gr in gate_results]


def _make_live_plan(artifact_id: str = _AID):
    cases = build_default_cases_for_candidate(artifact_id)
    return build_live_eval_plan(artifact_id, cases)


def _make_stub_report(artifact_id: str = _AID):
    plan = _make_live_plan(artifact_id)
    return execute_plan_with_stub_adapter(plan)


def _make_dossier(**overrides) -> dict:
    reports = _make_metadata_reports()
    plan = _make_live_plan()
    stub = _make_stub_report()
    dossier = build_evaluation_dossier(
        candidate_artifact_id=_AID,
        metadata_reports=reports,
        live_eval_plans=[plan],
        stub_execution_reports=[stub],
        source_model_registry_ref="model_registry/MA-tr06e-test-00001",
    )
    dossier.update(overrides)
    return dossier


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestEvaluationDossierSchema:
    def test_schema_parses(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_schema_required_fields_match_constant(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert set(schema["required"]) == REQUIRED_DOSSIER_FIELDS

    def test_schema_promotion_blocked_const_true(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["properties"]["promotion_blocked"]["const"] is True

    def test_schema_promotion_decision_emitted_const_false(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["properties"]["promotion_decision_emitted"]["const"] is False

    def test_schema_operator_review_required_const_true(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["properties"]["operator_review_required"]["const"] is True

    def test_schema_real_inference_const_false(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["properties"]["real_model_inference_performed"]["const"] is False

    def test_schema_provider_calls_const_false(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["properties"]["provider_calls_performed"]["const"] is False

    def test_schema_model_weights_const_false(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["properties"]["model_weights_loaded"]["const"] is False

    def test_schema_model_training_const_false(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["properties"]["model_training_performed"]["const"] is False

    def test_schema_deployment_const_false(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["properties"]["runtime_deployment_performed"]["const"] is False

    def test_schema_store1_const_false(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        assert schema["properties"]["store1_writes_performed"]["const"] is False

    def test_schema_readiness_state_enum(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        vals = set(schema["properties"]["readiness_state"]["enum"])
        assert vals == {"metadata_ready", "needs_more_evidence", "blocked", "not_evaluated"}

    def test_schema_gate_summary_required_fields(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        required = set(schema["properties"]["gate_summary"]["required"])
        assert required == {"pass", "fail", "block", "not_evaluated", "total"}

    def test_schema_stub_execution_summary_required_fields(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        required = set(schema["properties"]["stub_execution_summary"]["required"])
        assert required == {"stub_pass", "stub_fail", "stub_block", "not_evaluated", "blocked", "total"}

    def test_schema_invariants_present(self):
        schema = json.loads(DOSSIER_SCHEMA_PATH.read_text())
        inv = schema.get("x-invariants", {})
        assert "promotion_blocked_const" in inv
        assert "metadata_ready_is_not_promotion" in inv
        assert "no_real_inference" in inv
        assert "no_tr07" in inv


# ---------------------------------------------------------------------------
# summarize_metadata_reports
# ---------------------------------------------------------------------------

class TestSummarizeMetadataReports:
    def test_empty_returns_zero_total(self):
        s = summarize_metadata_reports([])
        assert s["total"] == 0

    def test_counts_pass_results(self):
        reports = [{"result": "pass"}, {"result": "pass"}]
        s = summarize_metadata_reports(reports)
        assert s["pass"] == 2
        assert s["total"] == 2

    def test_counts_fail_results(self):
        reports = [{"result": "fail"}, {"result": "pass"}]
        s = summarize_metadata_reports(reports)
        assert s["fail"] == 1
        assert s["pass"] == 1

    def test_counts_block_results(self):
        reports = [{"result": "block"}]
        s = summarize_metadata_reports(reports)
        assert s["block"] == 1

    def test_counts_not_evaluated(self):
        reports = [{"result": "not_evaluated"}]
        s = summarize_metadata_reports(reports)
        assert s["not_evaluated"] == 1

    def test_unknown_result_goes_to_not_evaluated(self):
        reports = [{"result": "unknown_future_value"}]
        s = summarize_metadata_reports(reports)
        assert s["not_evaluated"] == 1

    def test_real_metadata_reports_all_accounted(self):
        reports = _make_metadata_reports()
        s = summarize_metadata_reports(reports)
        assert s["total"] == len(reports)
        assert s["pass"] + s["fail"] + s["block"] + s["not_evaluated"] == s["total"]


# ---------------------------------------------------------------------------
# summarize_stub_execution_reports
# ---------------------------------------------------------------------------

class TestSummarizeStubExecutionReports:
    def test_empty_returns_zero_total(self):
        s = summarize_stub_execution_reports([])
        assert s["total"] == 0

    def test_counts_stub_pass(self):
        report = {"case_results": [{"result": "stub_pass"}, {"result": "stub_pass"}]}
        s = summarize_stub_execution_reports([report])
        assert s["stub_pass"] == 2

    def test_counts_stub_block(self):
        report = {"case_results": [{"result": "stub_block"}]}
        s = summarize_stub_execution_reports([report])
        assert s["stub_block"] == 1

    def test_counts_not_evaluated(self):
        report = {"case_results": [{"result": "not_evaluated"}]}
        s = summarize_stub_execution_reports([report])
        assert s["not_evaluated"] == 1

    def test_real_stub_report(self):
        stub = _make_stub_report()
        s = summarize_stub_execution_reports([stub])
        assert s["total"] == stub["cases_executed"]


# ---------------------------------------------------------------------------
# classify_readiness
# ---------------------------------------------------------------------------

class TestClassifyReadiness:
    def _empty_gate(self):
        return {"pass": 0, "fail": 0, "block": 0, "not_evaluated": 0, "total": 0}

    def _empty_stub(self):
        return {"stub_pass": 0, "stub_fail": 0, "stub_block": 0,
                "not_evaluated": 0, "blocked": 0, "total": 0}

    def test_not_evaluated_when_no_inputs(self):
        state, _ = classify_readiness(self._empty_gate(), self._empty_stub())
        assert state == "not_evaluated"

    def test_blocked_when_gate_block_exists(self):
        g = {**self._empty_gate(), "block": 1, "total": 1}
        state, _ = classify_readiness(g, self._empty_stub())
        assert state == "blocked"

    def test_blocked_when_stub_block_exists(self):
        s = {**self._empty_stub(), "stub_block": 1, "total": 1}
        state, _ = classify_readiness(self._empty_gate(), s)
        assert state == "blocked"

    def test_blocked_when_stub_blocked_exists(self):
        s = {**self._empty_stub(), "blocked": 1, "total": 1}
        state, _ = classify_readiness(self._empty_gate(), s)
        assert state == "blocked"

    def test_needs_more_evidence_when_gate_fail(self):
        g = {"pass": 5, "fail": 1, "block": 0, "not_evaluated": 0, "total": 6}
        state, _ = classify_readiness(g, self._empty_stub())
        assert state == "needs_more_evidence"

    def test_needs_more_evidence_when_gate_not_evaluated(self):
        g = {"pass": 5, "fail": 0, "block": 0, "not_evaluated": 1, "total": 6}
        state, _ = classify_readiness(g, self._empty_stub())
        assert state == "needs_more_evidence"

    def test_needs_more_evidence_when_only_stub_no_metadata(self):
        s = {**self._empty_stub(), "stub_pass": 6, "total": 6}
        state, _ = classify_readiness(self._empty_gate(), s)
        assert state == "needs_more_evidence"

    def test_needs_more_evidence_when_stub_fail(self):
        g = {"pass": 11, "fail": 0, "block": 0, "not_evaluated": 0, "total": 11}
        s = {**self._empty_stub(), "stub_fail": 1, "stub_pass": 5, "total": 6}
        state, _ = classify_readiness(g, s)
        assert state == "needs_more_evidence"

    def test_metadata_ready_clean_metadata_and_stub(self):
        g = {"pass": 11, "fail": 0, "block": 0, "not_evaluated": 0, "total": 11}
        s = {**self._empty_stub(), "stub_pass": 6, "total": 6}
        state, rationale = classify_readiness(g, s)
        assert state == "metadata_ready"
        assert "not promotion" in rationale.lower() or "NOT promotion" in rationale

    def test_metadata_ready_no_stub_clean_metadata(self):
        g = {"pass": 11, "fail": 0, "block": 0, "not_evaluated": 0, "total": 11}
        state, _ = classify_readiness(g, self._empty_stub())
        assert state == "metadata_ready"

    def test_blocked_takes_priority_over_fail(self):
        g = {"pass": 5, "fail": 2, "block": 1, "not_evaluated": 0, "total": 8}
        state, _ = classify_readiness(g, self._empty_stub())
        assert state == "blocked"

    def test_rationale_is_nonempty_string(self):
        g = self._empty_gate()
        s = self._empty_stub()
        _, rationale = classify_readiness(g, s)
        assert isinstance(rationale, str) and rationale.strip()


# ---------------------------------------------------------------------------
# build_evaluation_dossier
# ---------------------------------------------------------------------------

class TestBuildEvaluationDossier:
    def test_builds_from_metadata_reports(self):
        reports = _make_metadata_reports()
        dossier = build_evaluation_dossier(_AID, metadata_reports=reports)
        assert dossier["candidate_artifact_id"] == _AID

    def test_builds_from_stub_execution_report(self):
        stub = _make_stub_report()
        dossier = build_evaluation_dossier(_AID, stub_execution_reports=[stub])
        assert dossier["candidate_artifact_id"] == _AID

    def test_builds_combined_all_inputs(self):
        reports = _make_metadata_reports()
        plan = _make_live_plan()
        stub = _make_stub_report()
        dossier = build_evaluation_dossier(
            _AID,
            metadata_reports=reports,
            live_eval_plans=[plan],
            stub_execution_reports=[stub],
        )
        assert len(dossier["metadata_evaluation_report_refs"]) == len(reports)
        assert len(dossier["live_evaluation_plan_refs"]) == 1
        assert len(dossier["stub_execution_report_refs"]) == 1

    def test_dossier_id_starts_with_ed(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["evaluation_dossier_id"].startswith("ED-")

    def test_promotion_blocked_true(self):
        dossier = build_evaluation_dossier(_AID, metadata_reports=_make_metadata_reports())
        assert dossier["promotion_blocked"] is True

    def test_promotion_decision_emitted_false(self):
        dossier = build_evaluation_dossier(_AID, metadata_reports=_make_metadata_reports())
        assert dossier["promotion_decision_emitted"] is False

    def test_operator_review_required_true(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["operator_review_required"] is True

    def test_real_inference_false(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["real_model_inference_performed"] is False

    def test_provider_calls_false(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["provider_calls_performed"] is False

    def test_model_weights_loaded_false(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["model_weights_loaded"] is False

    def test_model_training_performed_false(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["model_training_performed"] is False

    def test_runtime_deployment_performed_false(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["runtime_deployment_performed"] is False

    def test_store1_writes_performed_false(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["store1_writes_performed"] is False

    def test_has_all_required_fields(self):
        dossier = build_evaluation_dossier(_AID)
        assert REQUIRED_DOSSIER_FIELDS.issubset(dossier.keys())

    def test_dossier_hash_is_64_chars(self):
        dossier = build_evaluation_dossier(_AID)
        assert len(dossier["dossier_hash"]) == 64

    def test_previous_dossier_hash_none_by_default(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["previous_dossier_hash"] is None

    def test_previous_dossier_hash_preserved(self):
        prev_hash = "a" * 64
        dossier = build_evaluation_dossier(_AID, previous_dossier_hash=prev_hash)
        assert dossier["previous_dossier_hash"] == prev_hash

    def test_deterministic_id_same_inputs(self):
        reports = _make_metadata_reports()
        d1 = build_evaluation_dossier(_AID, metadata_reports=reports)
        d2 = build_evaluation_dossier(_AID, metadata_reports=reports)
        assert d1["evaluation_dossier_id"] == d2["evaluation_dossier_id"]

    def test_not_evaluated_when_no_inputs(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["readiness_state"] == "not_evaluated"

    def test_readiness_state_is_valid_enum(self):
        dossier = build_evaluation_dossier(_AID, metadata_reports=_make_metadata_reports())
        assert dossier["readiness_state"] in {
            "metadata_ready", "needs_more_evidence", "blocked", "not_evaluated"
        }

    def test_blocked_actions_nonempty(self):
        dossier = build_evaluation_dossier(_AID)
        assert len(dossier["blocked_actions"]) > 0


# ---------------------------------------------------------------------------
# Input rejection
# ---------------------------------------------------------------------------

class TestDossierInputRejection:
    def test_rejects_mixed_candidate_ids_metadata(self):
        reports = _make_metadata_reports(_AID)
        wrong_report = {"candidate_artifact_id": _AID2, "result": "pass",
                        "promotion_blocked": True, "promotion_decision_emitted": False}
        with pytest.raises(EvaluationDossierInputError, match="candidate_artifact_id"):
            build_evaluation_dossier(_AID, metadata_reports=reports + [wrong_report])

    def test_rejects_mixed_candidate_ids_stub(self):
        stub = _make_stub_report(_AID)
        stub2 = _make_stub_report(_AID2)
        stub2["candidate_artifact_id"] = _AID2
        with pytest.raises(EvaluationDossierInputError, match="candidate_artifact_id"):
            build_evaluation_dossier(_AID, stub_execution_reports=[stub, stub2])

    def test_rejects_metadata_report_with_promotion_blocked_false(self):
        report = {"candidate_artifact_id": _AID, "result": "pass",
                  "promotion_blocked": False, "promotion_decision_emitted": False}
        with pytest.raises(EvaluationDossierInputError, match="promotion_blocked"):
            build_evaluation_dossier(_AID, metadata_reports=[report])

    def test_rejects_metadata_report_with_promotion_decision_emitted_true(self):
        report = {"candidate_artifact_id": _AID, "result": "pass",
                  "promotion_blocked": True, "promotion_decision_emitted": True}
        with pytest.raises(EvaluationDossierInputError, match="promotion_decision_emitted"):
            build_evaluation_dossier(_AID, metadata_reports=[report])

    def test_rejects_stub_report_with_real_inference_true(self):
        stub = _make_stub_report()
        stub["real_model_inference_performed"] = True
        with pytest.raises(EvaluationDossierInputError, match="real_model_inference_performed"):
            build_evaluation_dossier(_AID, stub_execution_reports=[stub])

    def test_rejects_stub_report_with_provider_calls_true(self):
        stub = _make_stub_report()
        stub["provider_calls_performed"] = True
        with pytest.raises(EvaluationDossierInputError, match="provider_calls_performed"):
            build_evaluation_dossier(_AID, stub_execution_reports=[stub])

    def test_rejects_stub_report_with_model_weights_loaded_true(self):
        stub = _make_stub_report()
        stub["model_weights_loaded"] = True
        with pytest.raises(EvaluationDossierInputError, match="model_weights_loaded"):
            build_evaluation_dossier(_AID, stub_execution_reports=[stub])

    def test_rejects_model_weights_path_in_metadata_report(self):
        report = {"candidate_artifact_id": _AID, "result": "pass",
                  "promotion_blocked": True, "promotion_decision_emitted": False,
                  "model_weights_path": "/tmp/weights.bin"}
        with pytest.raises(EvaluationDossierInputError, match="model_weights_path"):
            build_evaluation_dossier(_AID, metadata_reports=[report])

    def test_rejects_adapter_checkpoint_path_in_stub_report(self):
        stub = _make_stub_report()
        stub["adapter_checkpoint_path"] = "/tmp/lora.pt"
        with pytest.raises(EvaluationDossierInputError, match="adapter_checkpoint_path"):
            build_evaluation_dossier(_AID, stub_execution_reports=[stub])

    def test_rejects_plan_with_promotion_blocked_false(self):
        plan = _make_live_plan()
        plan["promotion_blocked"] = False
        with pytest.raises(EvaluationDossierInputError, match="promotion_blocked"):
            build_evaluation_dossier(_AID, live_eval_plans=[plan])


# ---------------------------------------------------------------------------
# Readiness states
# ---------------------------------------------------------------------------

class TestReadinessStates:
    def test_not_evaluated_with_no_inputs(self):
        dossier = build_evaluation_dossier(_AID)
        assert dossier["readiness_state"] == "not_evaluated"

    def test_blocked_when_block_in_metadata_reports(self):
        report = {
            "candidate_artifact_id": _AID,
            "result": "block",
            "promotion_blocked": True,
            "promotion_decision_emitted": False,
            "evaluation_report_id": "ER-blocked-test",
        }
        dossier = build_evaluation_dossier(_AID, metadata_reports=[report])
        assert dossier["readiness_state"] == "blocked"

    def test_blocked_when_stub_block_in_reports(self):
        stub = _make_stub_report()
        stub["case_results"][0]["result"] = "stub_block"
        dossier = build_evaluation_dossier(_AID, stub_execution_reports=[stub])
        assert dossier["readiness_state"] == "blocked"

    def test_needs_more_evidence_when_only_stub_no_metadata(self):
        stub = _make_stub_report()
        dossier = build_evaluation_dossier(_AID, stub_execution_reports=[stub])
        assert dossier["readiness_state"] == "needs_more_evidence"

    def test_needs_more_evidence_when_fail_in_metadata(self):
        report = {
            "candidate_artifact_id": _AID,
            "result": "fail",
            "promotion_blocked": True,
            "promotion_decision_emitted": False,
            "evaluation_report_id": "ER-fail-test",
        }
        dossier = build_evaluation_dossier(_AID, metadata_reports=[report])
        assert dossier["readiness_state"] == "needs_more_evidence"

    def test_metadata_ready_with_all_pass_metadata(self):
        reports = [
            {
                "candidate_artifact_id": _AID,
                "result": "pass",
                "promotion_blocked": True,
                "promotion_decision_emitted": False,
                "evaluation_report_id": f"ER-pass-{i}",
            }
            for i in range(11)
        ]
        dossier = build_evaluation_dossier(_AID, metadata_reports=reports)
        assert dossier["readiness_state"] == "metadata_ready"

    def test_metadata_ready_is_not_promotion_in_rationale(self):
        reports = [
            {
                "candidate_artifact_id": _AID,
                "result": "pass",
                "promotion_blocked": True,
                "promotion_decision_emitted": False,
                "evaluation_report_id": f"ER-pass-{i}",
            }
            for i in range(11)
        ]
        dossier = build_evaluation_dossier(_AID, metadata_reports=reports)
        assert dossier["readiness_state"] == "metadata_ready"
        rationale = dossier.get("readiness_rationale", "")
        assert "NOT promotion" in rationale or "not promotion" in rationale.lower()

    def test_promotion_blocked_regardless_of_readiness_state(self):
        for state in ["not_evaluated", "needs_more_evidence"]:
            stub = _make_stub_report()
            dossier = build_evaluation_dossier(
                _AID,
                stub_execution_reports=[stub] if state == "needs_more_evidence" else [],
            )
            assert dossier["promotion_blocked"] is True, f"Should be blocked in state {state}"


# ---------------------------------------------------------------------------
# compute_dossier_hash
# ---------------------------------------------------------------------------

class TestComputeDossierHash:
    def test_hash_is_deterministic(self):
        reports = _make_metadata_reports()
        d1 = build_evaluation_dossier(_AID, metadata_reports=reports)
        d2 = build_evaluation_dossier(_AID, metadata_reports=reports)
        assert d1["dossier_hash"] == d2["dossier_hash"]

    def test_hash_changes_when_readiness_changes(self):
        d_no_input = build_evaluation_dossier(_AID)
        d_with_stub = build_evaluation_dossier(_AID, stub_execution_reports=[_make_stub_report()])
        assert d_no_input["dossier_hash"] != d_with_stub["dossier_hash"]

    def test_hash_is_64_chars(self):
        dossier = build_evaluation_dossier(_AID)
        assert len(dossier["dossier_hash"]) == 64

    def test_compute_dossier_hash_matches_stored(self):
        dossier = build_evaluation_dossier(_AID)
        stored = dossier["dossier_hash"]
        recomputed = compute_dossier_hash(dossier)
        assert stored == recomputed

    def test_hash_changes_when_notes_change(self):
        d1 = build_evaluation_dossier(_AID, notes="Note A")
        d2 = build_evaluation_dossier(_AID, notes="Note B")
        assert d1["dossier_hash"] != d2["dossier_hash"]


# ---------------------------------------------------------------------------
# validate_evaluation_dossier
# ---------------------------------------------------------------------------

class TestValidateEvaluationDossier:
    def test_validates_valid_dossier(self):
        dossier = build_evaluation_dossier(_AID)
        result = validate_evaluation_dossier(dossier)
        assert result["valid"] is True

    def test_rejects_promotion_blocked_false(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["promotion_blocked"] = False
        with pytest.raises(EvaluationDossierValidationError, match="promotion_blocked"):
            validate_evaluation_dossier(dossier)

    def test_rejects_promotion_decision_emitted_true(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["promotion_decision_emitted"] = True
        with pytest.raises(EvaluationDossierValidationError, match="promotion_decision"):
            validate_evaluation_dossier(dossier)

    def test_rejects_real_inference_true(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["real_model_inference_performed"] = True
        with pytest.raises(EvaluationDossierValidationError, match="real_model_inference"):
            validate_evaluation_dossier(dossier)

    def test_rejects_provider_calls_true(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["provider_calls_performed"] = True
        with pytest.raises(EvaluationDossierValidationError, match="provider_calls"):
            validate_evaluation_dossier(dossier)

    def test_rejects_model_weights_true(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["model_weights_loaded"] = True
        with pytest.raises(EvaluationDossierValidationError, match="model_weights"):
            validate_evaluation_dossier(dossier)

    def test_rejects_model_training_true(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["model_training_performed"] = True
        with pytest.raises(EvaluationDossierValidationError, match="model_training"):
            validate_evaluation_dossier(dossier)

    def test_rejects_runtime_deployment_true(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["runtime_deployment_performed"] = True
        with pytest.raises(EvaluationDossierValidationError, match="runtime_deployment"):
            validate_evaluation_dossier(dossier)

    def test_rejects_store1_writes_true(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["store1_writes_performed"] = True
        with pytest.raises(EvaluationDossierValidationError, match="store1_writes"):
            validate_evaluation_dossier(dossier)

    def test_rejects_invalid_readiness_state(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["readiness_state"] = "production_ready"
        with pytest.raises(EvaluationDossierValidationError, match="readiness_state"):
            validate_evaluation_dossier(dossier)

    def test_rejects_short_dossier_hash(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["dossier_hash"] = "short"
        with pytest.raises(EvaluationDossierValidationError, match="dossier_hash"):
            validate_evaluation_dossier(dossier)

    def test_rejects_empty_blocked_actions(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["blocked_actions"] = []
        with pytest.raises(EvaluationDossierValidationError, match="blocked_actions"):
            validate_evaluation_dossier(dossier)

    def test_rejects_missing_required_field(self):
        dossier = build_evaluation_dossier(_AID)
        del dossier["candidate_artifact_id"]
        with pytest.raises(EvaluationDossierValidationError, match="candidate_artifact_id"):
            validate_evaluation_dossier(dossier)


# ---------------------------------------------------------------------------
# save / load / summarize
# ---------------------------------------------------------------------------

class TestSaveLoadDossier:
    def test_save_creates_dossier_file(self, tmp_path):
        dossier = build_evaluation_dossier(_AID)
        path = save_evaluation_dossier(dossier, str(tmp_path))
        assert path.exists()
        assert path.name.startswith("ed_ED-")

    def test_save_creates_checksums_file(self, tmp_path):
        dossier = build_evaluation_dossier(_AID)
        save_evaluation_dossier(dossier, str(tmp_path))
        assert (tmp_path / "checksums.sha256").exists()

    def test_checksums_references_dossier_file(self, tmp_path):
        dossier = build_evaluation_dossier(_AID)
        path = save_evaluation_dossier(dossier, str(tmp_path))
        content = (tmp_path / "checksums.sha256").read_text()
        assert path.name in content

    def test_load_round_trips(self, tmp_path):
        dossier = build_evaluation_dossier(_AID)
        path = save_evaluation_dossier(dossier, str(tmp_path))
        loaded = load_evaluation_dossier(str(path))
        assert loaded["evaluation_dossier_id"] == dossier["evaluation_dossier_id"]
        assert loaded["readiness_state"] == dossier["readiness_state"]

    def test_save_rejects_invalid_dossier(self, tmp_path):
        dossier = build_evaluation_dossier(_AID)
        dossier["promotion_blocked"] = False
        with pytest.raises(EvaluationDossierValidationError):
            save_evaluation_dossier(dossier, str(tmp_path))

    def test_load_rejects_nonexistent_file(self, tmp_path):
        with pytest.raises(EvaluationDossierError):
            load_evaluation_dossier(str(tmp_path / "nonexistent.json"))


class TestSummarizeEvaluationDossier:
    def test_summary_has_dossier_id(self):
        dossier = build_evaluation_dossier(_AID)
        summary = summarize_evaluation_dossier(dossier)
        assert summary["evaluation_dossier_id"] == dossier["evaluation_dossier_id"]

    def test_summary_has_readiness_state(self):
        dossier = build_evaluation_dossier(_AID)
        summary = summarize_evaluation_dossier(dossier)
        assert "readiness_state" in summary

    def test_summary_has_gate_summary(self):
        dossier = build_evaluation_dossier(_AID)
        summary = summarize_evaluation_dossier(dossier)
        assert "gate_summary" in summary

    def test_summary_invariants_false(self):
        dossier = build_evaluation_dossier(_AID)
        summary = summarize_evaluation_dossier(dossier)
        assert summary["real_model_inference_performed"] is False
        assert summary["provider_calls_performed"] is False
        assert summary["model_weights_loaded"] is False
        assert summary["model_training_performed"] is False
        assert summary["promotion_blocked"] is True
        assert summary["promotion_decision_emitted"] is False

    def test_summary_has_dossier_hash(self):
        dossier = build_evaluation_dossier(_AID)
        summary = summarize_evaluation_dossier(dossier)
        assert len(summary["dossier_hash"]) == 64


# ---------------------------------------------------------------------------
# assert_dossier_cannot_promote
# ---------------------------------------------------------------------------

class TestAssertDossierCannotPromote:
    def test_passes_for_valid_dossier(self):
        dossier = build_evaluation_dossier(_AID)
        assert_dossier_cannot_promote(dossier)  # should not raise

    def test_raises_if_promotion_blocked_false(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["promotion_blocked"] = False
        with pytest.raises(EvaluationDossierValidationError, match="promotion_blocked"):
            assert_dossier_cannot_promote(dossier)

    def test_raises_if_promotion_decision_emitted_true(self):
        dossier = build_evaluation_dossier(_AID)
        dossier["promotion_decision_emitted"] = True
        with pytest.raises(EvaluationDossierValidationError, match="promotion_decision"):
            assert_dossier_cannot_promote(dossier)

    def test_metadata_ready_does_not_trigger_promotion_guard(self):
        reports = [
            {
                "candidate_artifact_id": _AID,
                "result": "pass",
                "promotion_blocked": True,
                "promotion_decision_emitted": False,
                "evaluation_report_id": f"ER-pass-{i}",
            }
            for i in range(11)
        ]
        dossier = build_evaluation_dossier(_AID, metadata_reports=reports)
        assert dossier["readiness_state"] == "metadata_ready"
        assert_dossier_cannot_promote(dossier)  # should not raise — metadata_ready is not promotion

    @pytest.mark.parametrize("state", [
        "not_evaluated", "needs_more_evidence", "blocked"
    ])
    def test_always_passes_for_non_ready_states(self, state):
        if state == "blocked":
            report = {"candidate_artifact_id": _AID, "result": "block",
                      "promotion_blocked": True, "promotion_decision_emitted": False,
                      "evaluation_report_id": "ER-block-test"}
            dossier = build_evaluation_dossier(_AID, metadata_reports=[report])
        elif state == "needs_more_evidence":
            stub = _make_stub_report()
            dossier = build_evaluation_dossier(_AID, stub_execution_reports=[stub])
        else:
            dossier = build_evaluation_dossier(_AID)
        assert dossier["readiness_state"] == state
        assert_dossier_cannot_promote(dossier)  # should not raise


# ---------------------------------------------------------------------------
# Module purity
# ---------------------------------------------------------------------------

class TestModulePurity:
    def test_no_external_provider_imports(self):
        src = Path(__file__).parent.parent / "evaluation_dossier.py"
        code = src.read_text()
        forbidden = [
            "import openai", "import anthropic", "import google.generativeai",
            "import groq", "import torch", "import tensorflow", "import transformers",
            "import boto3", "import huggingface_hub", "import ollama",
            "from openai", "from anthropic", "from google.generativeai",
            "from transformers", "from huggingface_hub",
        ]
        for token in forbidden:
            assert token not in code, f"Forbidden import: {token!r}"

    def test_no_model_weight_operations(self):
        src = Path(__file__).parent.parent / "evaluation_dossier.py"
        code = src.read_text()
        for op in ("torch.load", "torch.save", ".from_pretrained", "LoraConfig"):
            assert op not in code, f"Forbidden op: {op!r}"

    def test_module_compiles(self):
        import importlib.util
        p = Path(__file__).parent.parent / "evaluation_dossier.py"
        spec = importlib.util.spec_from_file_location("evaluation_dossier", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "build_evaluation_dossier")
        assert hasattr(mod, "assert_dossier_cannot_promote")
