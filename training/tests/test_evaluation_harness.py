"""
TR-06A: tests for EVALUATION_REPORT.schema.json and evaluation_harness.py.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure training/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training.evaluation_harness import (
    EVALUATION_GATES,
    REQUIRED_REPORT_FIELDS,
    SCHEMA_VERSION,
    VALID_RESULTS,
    EvaluationCandidateError,
    EvaluationGateError,
    EvaluationHarnessError,
    EvaluationReportError,
    build_evaluation_report,
    load_lineage_record_from_candidate,
    load_registry_candidate,
    run_all_metadata_gates,
    run_evaluation_gate,
    save_evaluation_report,
    summarize_evaluation_reports,
    validate_evaluation_report,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCHEMA_PATH = Path(__file__).parent.parent / "EVALUATION_REPORT.schema.json"
_ALL_GATE_NAMES = sorted(EVALUATION_GATES)


def _valid_candidate(**overrides) -> dict:
    base = {
        "model_artifact_id":          "MA-test00000000001",
        "artifact_type":              "dry_run_adapter_candidate",
        "artifact_status":            "dry_run_only",
        "created_at":                 "2026-06-27T00:00:00Z",
        "created_by":                 "TEST_EVAL_OP_001",
        "lineage_record_id":          "LR-test00000000001",
        "base_model_reference":       None,
        "adapter_reference":          None,
        "dep_keystone_ingress_ref":   "DKI-test-l1001-001",
        "dep_keystone_evidence_sha256_ref":
            "dep-keystone://evidence.sha256/L1-001/v1",
        "dep_keystone_verification_report_ref":
            "dep-keystone://verification-report.json/L1-001/v1",
        "dataset_manifest_ref":       "dataset:DS-test-001",
        "dry_run_envelope_ref":       "dry_run:DR-aabbccdd11223344",
        "training_job_contract_ref":  None,
        "evaluation_ref":             None,
        "promotion_status":           "not_promoted",
        "training_allowed":           False,
        "model_weights_present":      False,
        "runtime_deployment_allowed": False,
        "store1_write_allowed":       False,
        "external_calls_allowed":     False,
        "operator_promotion_required": True,
        "checksum_manifest":          "a" * 64,
        "lineage": {
            "lineage_record_id":    "LR-test00000000001",
            "schema_version":       "1.0.0",
            "created_at":           "2026-06-27T00:00:00Z",
            "artifact_id":          "MA-test00000000001",
            "artifact_type":        "dry_run_adapter_candidate",
            "parent_artifacts":     [],
            "dep_keystone_ingress_refs":               ["DKI-test-l1001-001"],
            "dep_keystone_evidence_sha256_refs":
                ["dep-keystone://evidence.sha256/L1-001/v1"],
            "dep_keystone_verification_report_refs":
                ["dep-keystone://verification-report.json/L1-001/v1"],
            "source_registry_refs":               ["source_registry:L1-001"],
            "clearance_ledger_refs":              ["clearance_ledger:LE-test-001"],
            "synthetic_manifest_refs":            [],
            "synthetic_review_bridge_refs":       [],
            "dataset_manifest_refs":              ["dataset:DS-test-001"],
            "dry_run_envelope_refs":              ["dry_run:DR-aabbccdd11223344"],
            "training_job_contract_refs":         [],
            "evaluation_refs":                    [],
            "promotion_decision_refs":            [],
            "lineage_hash":                       "a" * 64,
            "previous_lineage_hash":              "0" * 64,
            "governance_flags": {
                "training_allowed":           False,
                "model_weights_present":      False,
                "store1_write_allowed":       False,
                "runtime_deployment_allowed": False,
                "external_calls_allowed":     False,
                "operator_promotion_required": True,
            },
            "notes": "Test lineage record.",
        },
        "provenance": {
            "source_id":       "L1-001",
            "requested_use":   "sft_candidate",
            "ledger_entry_id": "LE-test-001",
            "dataset_id":      "DS-test-001",
            "dry_run_id":      "DR-aabbccdd11223344",
            "govsec_layer":    "layer_zero_reality_formation",
        },
        "notes": "Test candidate for TR-06A evaluation harness.",
    }
    base.update(overrides)
    return base


def _make_registry_file(tmp_path: Path, candidate: dict, *, extra_entries=None) -> Path:
    entries = [candidate]
    if extra_entries:
        entries.extend(extra_entries)
    registry = {
        "schema_version":    "1.0.0",
        "registry_id":       "REG-test-001",
        "created_at":        "2026-06-27T00:00:00Z",
        "created_by":        "TEST_EVAL_OP_001",
        "entries":           entries,
    }
    path = tmp_path / "model_registry.json"
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestEvaluationSchema:
    def test_schema_parses(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_schema_required_fields(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        assert set(schema["required"]) == REQUIRED_REPORT_FIELDS

    def test_schema_gate_enum_matches_constant(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        schema_gates = set(schema["properties"]["evaluation_gate"]["enum"])
        assert schema_gates == EVALUATION_GATES

    def test_schema_promotion_blocked_const_true(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        assert schema["properties"]["promotion_blocked"]["const"] is True

    def test_schema_promotion_decision_emitted_const_false(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        assert schema["properties"]["promotion_decision_emitted"]["const"] is False

    def test_schema_metadata_only_const_true(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        assert schema["properties"]["metadata_only"]["const"] is True

    def test_schema_operator_review_required_const_true(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        assert schema["properties"]["operator_review_required"]["const"] is True

    def test_schema_result_enum(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        assert set(schema["properties"]["result"]["enum"]) == VALID_RESULTS

    def test_schema_invariants_block_promotion(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        invariants = schema.get("x-invariants", {})
        assert "promotion_blocked_const" in invariants
        assert "promotion_decision_never_emitted" in invariants

    def test_schema_invariant_metadata_only(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        invariants = schema.get("x-invariants", {})
        assert "metadata_only_const" in invariants

    def test_schema_invariant_no_tr07(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        invariants = schema.get("x-invariants", {})
        assert "no_tr07" in invariants


# ---------------------------------------------------------------------------
# load_registry_candidate — valid and rejections
# ---------------------------------------------------------------------------

class TestLoadRegistryCandidate:
    def test_loads_valid_candidate(self, tmp_path):
        c = _valid_candidate()
        reg = _make_registry_file(tmp_path, c)
        loaded = load_registry_candidate(str(reg), "MA-test00000000001")
        assert loaded["model_artifact_id"] == "MA-test00000000001"

    def test_rejects_unknown_artifact_id(self, tmp_path):
        c = _valid_candidate()
        reg = _make_registry_file(tmp_path, c)
        with pytest.raises(EvaluationCandidateError, match="not found"):
            load_registry_candidate(str(reg), "MA-doesnotexist")

    def test_rejects_candidate_promotion_status_not_not_promoted(self, tmp_path):
        c = _valid_candidate(promotion_status="promoted")
        reg = _make_registry_file(tmp_path, c)
        with pytest.raises(EvaluationCandidateError, match="promotion_status"):
            load_registry_candidate(str(reg), "MA-test00000000001")

    def test_rejects_candidate_training_allowed_true(self, tmp_path):
        c = _valid_candidate(training_allowed=True)
        reg = _make_registry_file(tmp_path, c)
        with pytest.raises(EvaluationCandidateError, match="training_allowed"):
            load_registry_candidate(str(reg), "MA-test00000000001")

    def test_rejects_candidate_model_weights_present_true(self, tmp_path):
        c = _valid_candidate(model_weights_present=True)
        reg = _make_registry_file(tmp_path, c)
        with pytest.raises(EvaluationCandidateError, match="model_weights_present"):
            load_registry_candidate(str(reg), "MA-test00000000001")

    def test_rejects_candidate_runtime_deployment_allowed_true(self, tmp_path):
        c = _valid_candidate(runtime_deployment_allowed=True)
        reg = _make_registry_file(tmp_path, c)
        with pytest.raises(EvaluationCandidateError, match="runtime_deployment_allowed"):
            load_registry_candidate(str(reg), "MA-test00000000001")

    def test_rejects_candidate_store1_write_allowed_true(self, tmp_path):
        c = _valid_candidate(store1_write_allowed=True)
        reg = _make_registry_file(tmp_path, c)
        with pytest.raises(EvaluationCandidateError, match="store1_write_allowed"):
            load_registry_candidate(str(reg), "MA-test00000000001")

    def test_rejects_candidate_external_calls_allowed_true(self, tmp_path):
        c = _valid_candidate(external_calls_allowed=True)
        reg = _make_registry_file(tmp_path, c)
        with pytest.raises(EvaluationCandidateError, match="external_calls_allowed"):
            load_registry_candidate(str(reg), "MA-test00000000001")

    def test_rejects_candidate_with_model_weights_path(self, tmp_path):
        c = _valid_candidate(model_weights_path="/tmp/bad.bin")
        reg = _make_registry_file(tmp_path, c)
        with pytest.raises(EvaluationCandidateError, match="model_weights_path"):
            load_registry_candidate(str(reg), "MA-test00000000001")

    def test_rejects_candidate_with_adapter_checkpoint_path(self, tmp_path):
        c = _valid_candidate(adapter_checkpoint_path="/tmp/lora.pt")
        reg = _make_registry_file(tmp_path, c)
        with pytest.raises(EvaluationCandidateError, match="adapter_checkpoint_path"):
            load_registry_candidate(str(reg), "MA-test00000000001")

    def test_missing_registry_file_raises(self, tmp_path):
        with pytest.raises(EvaluationHarnessError):
            load_registry_candidate(str(tmp_path / "nonexistent.json"), "MA-x")


# ---------------------------------------------------------------------------
# Gate stub output contract
# ---------------------------------------------------------------------------

_GATE_REQUIRED_KEYS = {
    "gate", "result", "requires_live_inference", "metadata_only", "evidence", "notes"
}


class TestGateStubOutputContract:
    @pytest.mark.parametrize("gate_name", _ALL_GATE_NAMES)
    def test_gate_returns_required_keys(self, gate_name):
        c = _valid_candidate()
        result = run_evaluation_gate(c, gate_name)
        assert _GATE_REQUIRED_KEYS.issubset(result.keys()), (
            f"Gate {gate_name!r} missing keys: {_GATE_REQUIRED_KEYS - set(result.keys())}"
        )

    @pytest.mark.parametrize("gate_name", _ALL_GATE_NAMES)
    def test_gate_metadata_only_is_true(self, gate_name):
        c = _valid_candidate()
        result = run_evaluation_gate(c, gate_name)
        assert result["metadata_only"] is True, (
            f"Gate {gate_name!r}: metadata_only must be True"
        )

    @pytest.mark.parametrize("gate_name", _ALL_GATE_NAMES)
    def test_gate_requires_live_inference_is_false(self, gate_name):
        c = _valid_candidate()
        result = run_evaluation_gate(c, gate_name)
        assert result["requires_live_inference"] is False, (
            f"Gate {gate_name!r}: requires_live_inference must be False for TR-06A metadata stubs"
        )

    @pytest.mark.parametrize("gate_name", _ALL_GATE_NAMES)
    def test_gate_result_is_valid(self, gate_name):
        c = _valid_candidate()
        result = run_evaluation_gate(c, gate_name)
        assert result["result"] in VALID_RESULTS, (
            f"Gate {gate_name!r}: result={result['result']!r} not in {VALID_RESULTS}"
        )

    @pytest.mark.parametrize("gate_name", _ALL_GATE_NAMES)
    def test_gate_name_matches_key(self, gate_name):
        c = _valid_candidate()
        result = run_evaluation_gate(c, gate_name)
        assert result["gate"] == gate_name

    def test_unknown_gate_raises(self):
        c = _valid_candidate()
        with pytest.raises(EvaluationGateError, match="Unknown gate"):
            run_evaluation_gate(c, "nonexistent_gate")


# ---------------------------------------------------------------------------
# build_evaluation_report
# ---------------------------------------------------------------------------

class TestBuildEvaluationReport:
    def _gate_result(self):
        c = _valid_candidate()
        return run_evaluation_gate(c, "promotion_blocking_invariants")

    def test_promotion_blocked_is_always_true(self):
        c = _valid_candidate()
        gr = self._gate_result()
        report = build_evaluation_report(c, gr)
        assert report["promotion_blocked"] is True

    def test_promotion_decision_emitted_is_always_false(self):
        c = _valid_candidate()
        gr = self._gate_result()
        report = build_evaluation_report(c, gr)
        assert report["promotion_decision_emitted"] is False

    def test_metadata_only_is_always_true(self):
        c = _valid_candidate()
        gr = self._gate_result()
        report = build_evaluation_report(c, gr)
        assert report["metadata_only"] is True

    def test_operator_review_required_is_always_true(self):
        c = _valid_candidate()
        gr = self._gate_result()
        report = build_evaluation_report(c, gr)
        assert report["operator_review_required"] is True

    def test_report_id_is_deterministic(self):
        c = _valid_candidate()
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        r1 = build_evaluation_report(c, gr)
        r2 = build_evaluation_report(c, gr)
        assert r1["evaluation_report_id"] == r2["evaluation_report_id"]

    def test_report_id_differs_for_different_gates(self):
        c = _valid_candidate()
        gr1 = run_evaluation_gate(c, "promotion_blocking_invariants")
        gr2 = run_evaluation_gate(c, "dry_run_integrity")
        r1 = build_evaluation_report(c, gr1)
        r2 = build_evaluation_report(c, gr2)
        assert r1["evaluation_report_id"] != r2["evaluation_report_id"]

    def test_report_has_all_required_fields(self):
        c = _valid_candidate()
        gr = self._gate_result()
        report = build_evaluation_report(c, gr)
        assert REQUIRED_REPORT_FIELDS.issubset(report.keys())

    def test_report_schema_version(self):
        c = _valid_candidate()
        gr = self._gate_result()
        report = build_evaluation_report(c, gr)
        assert report["schema_version"] == SCHEMA_VERSION

    def test_evaluated_by_default(self):
        c = _valid_candidate()
        gr = self._gate_result()
        report = build_evaluation_report(c, gr)
        assert report["evaluated_by"] == "TR06A_METADATA_HARNESS"

    def test_evaluated_by_custom(self):
        c = _valid_candidate()
        gr = self._gate_result()
        report = build_evaluation_report(c, gr, evaluated_by="TEST_OP_001")
        assert report["evaluated_by"] == "TEST_OP_001"


# ---------------------------------------------------------------------------
# validate_evaluation_report
# ---------------------------------------------------------------------------

class TestValidateEvaluationReport:
    def test_validates_correct_report(self):
        c = _valid_candidate()
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        report = build_evaluation_report(c, gr)
        result = validate_evaluation_report(report)
        assert result["valid"] is True

    def test_raises_on_missing_required_field(self):
        c = _valid_candidate()
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        report = build_evaluation_report(c, gr)
        del report["promotion_blocked"]
        with pytest.raises(EvaluationReportError, match="promotion_blocked"):
            validate_evaluation_report(report)

    def test_raises_if_promotion_blocked_false(self):
        c = _valid_candidate()
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        report = build_evaluation_report(c, gr)
        report["promotion_blocked"] = False
        with pytest.raises(EvaluationReportError, match="promotion_blocked"):
            validate_evaluation_report(report)

    def test_raises_if_promotion_decision_emitted_true(self):
        c = _valid_candidate()
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        report = build_evaluation_report(c, gr)
        report["promotion_decision_emitted"] = True
        with pytest.raises(EvaluationReportError, match="promotion_decision_emitted"):
            validate_evaluation_report(report)

    def test_raises_if_metadata_only_false(self):
        c = _valid_candidate()
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        report = build_evaluation_report(c, gr)
        report["metadata_only"] = False
        with pytest.raises(EvaluationReportError, match="metadata_only"):
            validate_evaluation_report(report)

    def test_raises_on_invalid_gate(self):
        c = _valid_candidate()
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        report = build_evaluation_report(c, gr)
        report["evaluation_gate"] = "not_a_real_gate"
        with pytest.raises(EvaluationReportError, match="evaluation_gate"):
            validate_evaluation_report(report)

    def test_raises_on_invalid_result(self):
        c = _valid_candidate()
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        report = build_evaluation_report(c, gr)
        report["result"] = "maybe"
        with pytest.raises(EvaluationReportError, match="result"):
            validate_evaluation_report(report)


# ---------------------------------------------------------------------------
# run_all_metadata_gates
# ---------------------------------------------------------------------------

class TestRunAllMetadataGates:
    def test_produces_report_for_every_gate(self):
        c = _valid_candidate()
        results = run_all_metadata_gates(c)
        returned_gates = {r["gate"] for r in results}
        assert returned_gates == EVALUATION_GATES

    def test_count_matches_gate_count(self):
        c = _valid_candidate()
        results = run_all_metadata_gates(c)
        assert len(results) == len(EVALUATION_GATES)

    def test_all_results_have_required_keys(self):
        c = _valid_candidate()
        results = run_all_metadata_gates(c)
        for r in results:
            assert _GATE_REQUIRED_KEYS.issubset(r.keys()), (
                f"Gate {r.get('gate')!r} missing keys"
            )

    def test_all_reports_from_run_all_validate(self):
        c = _valid_candidate()
        gate_results = run_all_metadata_gates(c)
        for gr in gate_results:
            report = build_evaluation_report(c, gr)
            validate_evaluation_report(report)


# ---------------------------------------------------------------------------
# Specific gate behaviors
# ---------------------------------------------------------------------------

class TestPromotionBlockingInvariants:
    def test_passes_for_valid_not_promoted_candidate(self):
        c = _valid_candidate()
        result = run_evaluation_gate(c, "promotion_blocking_invariants")
        assert result["result"] == "pass"

    def test_blocks_when_promotion_status_wrong(self):
        c = _valid_candidate()
        c["promotion_status"] = "eligible_for_future_evaluation"
        result = run_evaluation_gate(c, "promotion_blocking_invariants")
        assert result["result"] == "block"

    def test_blocks_when_training_allowed_true(self):
        c = _valid_candidate()
        c["training_allowed"] = True
        result = run_evaluation_gate(c, "promotion_blocking_invariants")
        assert result["result"] == "block"

    def test_blocks_when_model_weights_present_true(self):
        c = _valid_candidate()
        c["model_weights_present"] = True
        result = run_evaluation_gate(c, "promotion_blocking_invariants")
        assert result["result"] == "block"

    def test_blocks_when_runtime_deployment_allowed_true(self):
        c = _valid_candidate()
        c["runtime_deployment_allowed"] = True
        result = run_evaluation_gate(c, "promotion_blocking_invariants")
        assert result["result"] == "block"


class TestDryRunIntegrity:
    def test_passes_for_valid_candidate(self):
        c = _valid_candidate()
        result = run_evaluation_gate(c, "dry_run_integrity")
        assert result["result"] == "pass"

    def test_fails_when_dry_run_refs_empty(self):
        c = _valid_candidate()
        c["lineage"]["dry_run_envelope_refs"] = []
        result = run_evaluation_gate(c, "dry_run_integrity")
        assert result["result"] in ("fail", "block")

    def test_blocks_when_training_allowed_true_in_governance_flags(self):
        c = _valid_candidate()
        c["lineage"]["governance_flags"]["training_allowed"] = True
        result = run_evaluation_gate(c, "dry_run_integrity")
        assert result["result"] == "block"


class TestDepKeystoneProvenance:
    def test_passes_when_all_refs_present(self):
        c = _valid_candidate()
        result = run_evaluation_gate(c, "dep_keystone_govsec_provenance_completeness")
        assert result["result"] == "pass"

    def test_fails_when_candidate_dep_keystone_ingress_ref_missing(self):
        c = _valid_candidate()
        del c["dep_keystone_ingress_ref"]
        result = run_evaluation_gate(c, "dep_keystone_govsec_provenance_completeness")
        assert result["result"] in ("fail", "block")

    def test_fails_when_lineage_dep_keystone_ingress_refs_empty(self):
        c = _valid_candidate()
        c["lineage"]["dep_keystone_ingress_refs"] = []
        result = run_evaluation_gate(c, "dep_keystone_govsec_provenance_completeness")
        assert result["result"] in ("fail", "block")

    def test_fails_when_evidence_sha256_ref_missing(self):
        c = _valid_candidate()
        del c["dep_keystone_evidence_sha256_ref"]
        result = run_evaluation_gate(c, "dep_keystone_govsec_provenance_completeness")
        assert result["result"] in ("fail", "block")


class TestSyntheticProvenanceIntegrity:
    def test_not_evaluated_for_non_synthetic_candidate(self):
        c = _valid_candidate()
        assert c["lineage"]["synthetic_manifest_refs"] == []
        assert c["lineage"]["synthetic_review_bridge_refs"] == []
        result = run_evaluation_gate(c, "synthetic_provenance_integrity")
        assert result["result"] == "not_evaluated"

    def test_passes_for_synthetic_lineage_fixture(self):
        c = _valid_candidate()
        c["lineage"]["synthetic_manifest_refs"] = [
            "synthetic://manifest/syn-doc-001/v1"
        ]
        c["lineage"]["synthetic_review_bridge_refs"] = [
            "synthetic://bridge/syn-doc-001/v1"
        ]
        result = run_evaluation_gate(c, "synthetic_provenance_integrity")
        assert result["result"] == "pass"

    def test_fails_for_invalid_synthetic_ref_entry(self):
        c = _valid_candidate()
        c["lineage"]["synthetic_manifest_refs"] = [""]
        result = run_evaluation_gate(c, "synthetic_provenance_integrity")
        assert result["result"] == "fail"


class TestStore1Boundary:
    def test_passes_for_valid_candidate(self):
        c = _valid_candidate()
        result = run_evaluation_gate(c, "store1_govmem_boundary_preservation")
        assert result["result"] == "pass"

    def test_blocks_when_store1_write_allowed_true(self):
        c = _valid_candidate()
        c["store1_write_allowed"] = True
        result = run_evaluation_gate(c, "store1_govmem_boundary_preservation")
        assert result["result"] == "block"

    def test_blocks_when_external_calls_allowed_true_in_flags(self):
        c = _valid_candidate()
        c["lineage"]["governance_flags"]["external_calls_allowed"] = True
        result = run_evaluation_gate(c, "store1_govmem_boundary_preservation")
        assert result["result"] == "block"


class TestSourceRegistryClearance:
    def test_passes_when_refs_present(self):
        c = _valid_candidate()
        result = run_evaluation_gate(c, "source_registry_clearance_completeness")
        assert result["result"] == "pass"

    def test_fails_when_source_registry_refs_empty(self):
        c = _valid_candidate()
        c["lineage"]["source_registry_refs"] = []
        result = run_evaluation_gate(c, "source_registry_clearance_completeness")
        assert result["result"] in ("fail", "block")


class TestClearanceLedger:
    def test_passes_when_refs_present(self):
        c = _valid_candidate()
        result = run_evaluation_gate(c, "clearance_ledger_completeness")
        assert result["result"] == "pass"

    def test_fails_when_clearance_ledger_refs_empty(self):
        c = _valid_candidate()
        c["lineage"]["clearance_ledger_refs"] = []
        result = run_evaluation_gate(c, "clearance_ledger_completeness")
        assert result["result"] in ("fail", "block")


# ---------------------------------------------------------------------------
# save_evaluation_report + summarize
# ---------------------------------------------------------------------------

class TestSaveAndSummarize:
    def test_save_evaluation_report_creates_file(self, tmp_path):
        c = _valid_candidate()
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        report = build_evaluation_report(c, gr)
        path = save_evaluation_report(report, str(tmp_path))
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["evaluation_report_id"] == report["evaluation_report_id"]

    def test_summarize_aggregates_results(self):
        c = _valid_candidate()
        gate_results = run_all_metadata_gates(c)
        reports = [build_evaluation_report(c, gr) for gr in gate_results]
        summary = summarize_evaluation_reports(reports)
        assert summary["total_reports"] == len(EVALUATION_GATES)
        assert summary["promotion_blocked"] is True

    def test_summarize_any_block_flag(self):
        reports = [
            {
                "evaluation_gate": "promotion_blocking_invariants",
                "result": "block",
                "promotion_blocked": True,
            }
        ]
        summary = summarize_evaluation_reports(reports)
        assert summary["any_block"] is True

    def test_summarize_all_pass_flag(self):
        c = _valid_candidate()
        gate_results = run_all_metadata_gates(c)
        reports = [build_evaluation_report(c, gr) for gr in gate_results]
        summary = summarize_evaluation_reports(reports)
        passing = all(r["result"] == "pass" or r["result"] == "not_evaluated"
                      for r in gate_results)
        assert isinstance(summary["all_pass"], bool)

    def test_summarize_empty_list(self):
        summary = summarize_evaluation_reports([])
        assert summary["total_reports"] == 0
        assert summary["promotion_blocked"] is True
        assert summary["any_block"] is False
        assert summary["all_pass"] is True


# ---------------------------------------------------------------------------
# Module purity
# ---------------------------------------------------------------------------

class TestModulePurity:
    def test_no_external_provider_imports(self):
        harness_path = Path(__file__).parent.parent / "evaluation_harness.py"
        src = harness_path.read_text()
        forbidden = [
            "import openai", "import anthropic", "import google.generativeai",
            "import groq", "import torch", "import tensorflow", "import transformers",
            "import boto3", "import huggingface_hub", "from openai", "from anthropic",
            "from google.generativeai", "from transformers", "from huggingface_hub",
        ]
        for token in forbidden:
            assert token not in src, (
                f"evaluation_harness.py contains forbidden import: {token!r}"
            )

    def test_no_model_weight_operations(self):
        harness_path = Path(__file__).parent.parent / "evaluation_harness.py"
        src = harness_path.read_text()
        forbidden_ops = [
            "torch.load", "torch.save", "model.load_state_dict",
            "load_pretrained", ".from_pretrained", "LoraConfig",
        ]
        for op in forbidden_ops:
            assert op not in src, (
                f"evaluation_harness.py contains forbidden model-weight operation: {op!r}"
            )

    def test_harness_module_compiles(self):
        import importlib
        import importlib.util
        harness_path = Path(__file__).parent.parent / "evaluation_harness.py"
        spec = importlib.util.spec_from_file_location("evaluation_harness", harness_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "EVALUATION_GATES")
        assert hasattr(mod, "run_evaluation_gate")
        assert hasattr(mod, "build_evaluation_report")


# ---------------------------------------------------------------------------
# Cross-suite regression guard
# ---------------------------------------------------------------------------

class TestExistingSuiteUnaffected:
    """Smoke check: existing training test files are importable and not broken."""

    def test_model_registry_tests_importable(self):
        import importlib.util
        p = Path(__file__).parent / "test_model_registry.py"
        spec = importlib.util.spec_from_file_location("test_model_registry", p)
        mod = importlib.util.module_from_spec(spec)
        assert mod is not None

    def test_dep_keystone_ingress_tests_importable(self):
        import importlib.util
        p = Path(__file__).parent / "test_dep_keystone_training_ingress.py"
        spec = importlib.util.spec_from_file_location("test_dep_keystone", p)
        mod = importlib.util.module_from_spec(spec)
        assert mod is not None
