"""
TR-06B: tests for EVALUATION_FIXTURE_CASE.schema.json and evaluation_fixture_builder.py.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training.evaluation_harness import (
    EVALUATION_GATES,
    EvaluationCandidateError,
    _assert_candidate_safe,
    run_evaluation_gate,
)
from training.evaluation_fixture_builder import (
    CASE_TYPES,
    build_fixture_catalog,
    build_mutated_candidate_fixture,
    build_non_synthetic_candidate_fixture,
    build_synthetic_candidate_fixture,
    build_valid_complete_candidate_fixture,
    run_fixture_case,
    summarize_fixture_results,
    write_fixture_catalog,
)

FIXTURE_SCHEMA_PATH = Path(__file__).parent.parent / "EVALUATION_FIXTURE_CASE.schema.json"
EVAL_SCHEMA_PATH = Path(__file__).parent.parent / "EVALUATION_REPORT.schema.json"


# ---------------------------------------------------------------------------
# Fixture Case Schema
# ---------------------------------------------------------------------------

class TestFixtureCaseSchema:
    def test_schema_parses(self):
        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_schema_required_fields(self):
        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text())
        required = set(schema["required"])
        assert "fixture_case_id" in required
        assert "case_type" in required
        assert "expected_gate_results" in required
        assert "expected_harness_rejection" in required
        assert "metadata_only" in required
        assert "requires_live_inference" in required

    def test_schema_case_type_enum(self):
        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text())
        schema_types = set(schema["properties"]["case_type"]["enum"])
        assert schema_types == CASE_TYPES

    def test_schema_metadata_only_const_true(self):
        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text())
        assert schema["properties"]["metadata_only"]["const"] is True

    def test_schema_requires_live_inference_const_false(self):
        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text())
        assert schema["properties"]["requires_live_inference"]["const"] is False

    def test_schema_gate_result_enum(self):
        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text())
        enum = set(
            schema["properties"]["expected_gate_results"]["additionalProperties"]["enum"]
        )
        assert enum == {"pass", "fail", "block", "not_evaluated"}

    def test_schema_invariants_no_promotion(self):
        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text())
        invariants = schema.get("x-invariants", {})
        assert "no_promotion" in invariants

    def test_schema_invariant_no_tr06c(self):
        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text())
        assert "no_tr06c" in schema.get("x-invariants", {})


# ---------------------------------------------------------------------------
# Fixture builder module
# ---------------------------------------------------------------------------

class TestFixtureBuilderModule:
    def test_module_compiles(self):
        import importlib.util
        p = Path(__file__).parent.parent / "evaluation_fixture_builder.py"
        spec = importlib.util.spec_from_file_location("evaluation_fixture_builder", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "build_fixture_catalog")
        assert hasattr(mod, "run_fixture_case")

    def test_case_types_constant_covers_all_schema_enum_values(self):
        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text())
        schema_types = set(schema["properties"]["case_type"]["enum"])
        assert CASE_TYPES == schema_types


# ---------------------------------------------------------------------------
# Fixture catalog
# ---------------------------------------------------------------------------

class TestFixtureCatalog:
    def test_catalog_contains_all_case_types(self):
        catalog = build_fixture_catalog()
        catalog_types = {case["case_type"] for case in catalog}
        assert catalog_types == CASE_TYPES

    def test_catalog_length(self):
        catalog = build_fixture_catalog()
        assert len(catalog) == len(CASE_TYPES)

    def test_every_case_has_fixture_case_id(self):
        catalog = build_fixture_catalog()
        for case in catalog:
            assert case.get("fixture_case_id", "").startswith("FC-"), (
                f"Case {case.get('case_type')!r} missing fixture_case_id"
            )

    def test_every_case_has_expected_gate_results(self):
        catalog = build_fixture_catalog()
        for case in catalog:
            assert "expected_gate_results" in case, (
                f"Case {case.get('case_type')!r} missing expected_gate_results"
            )

    def test_every_case_has_metadata_only_true(self):
        catalog = build_fixture_catalog()
        for case in catalog:
            assert case.get("metadata_only") is True, (
                f"Case {case.get('case_type')!r}: metadata_only must be True"
            )

    def test_every_case_has_requires_live_inference_false(self):
        catalog = build_fixture_catalog()
        for case in catalog:
            assert case.get("requires_live_inference") is False, (
                f"Case {case.get('case_type')!r}: requires_live_inference must be False"
            )

    def test_every_case_has_candidate(self):
        catalog = build_fixture_catalog()
        for case in catalog:
            assert "_candidate" in case, (
                f"Case {case.get('case_type')!r} missing _candidate"
            )

    def test_fixture_case_ids_are_unique(self):
        catalog = build_fixture_catalog()
        ids = [c["fixture_case_id"] for c in catalog]
        assert len(ids) == len(set(ids)), "Duplicate fixture_case_id values found"

    def test_write_fixture_catalog_creates_file(self, tmp_path):
        path = write_fixture_catalog(str(tmp_path))
        assert path.exists()
        catalog = json.loads(path.read_text())
        assert len(catalog) == len(CASE_TYPES)
        # Static catalog should not include _candidate
        for case in catalog:
            assert "_candidate" not in case

    def test_catalog_is_deterministic(self):
        catalog1 = build_fixture_catalog()
        catalog2 = build_fixture_catalog()
        ids1 = [c["fixture_case_id"] for c in catalog1]
        ids2 = [c["fixture_case_id"] for c in catalog2]
        assert ids1 == ids2


# ---------------------------------------------------------------------------
# valid_complete_metadata fixture
# ---------------------------------------------------------------------------

class TestValidCompleteMetadata:
    def test_builds_without_error(self):
        case = build_valid_complete_candidate_fixture()
        assert case["case_type"] == "valid_complete_metadata"

    def test_expected_harness_rejection_false(self):
        case = build_valid_complete_candidate_fixture()
        assert case["expected_harness_rejection"] is False

    def test_all_expected_results_are_pass(self):
        case = build_valid_complete_candidate_fixture()
        for gate, expected in case["expected_gate_results"].items():
            assert expected == "pass", (
                f"valid_complete_metadata: gate {gate!r} expected pass, got {expected!r}"
            )

    def test_produces_typed_evaluation_reports(self):
        case = build_valid_complete_candidate_fixture()
        result = run_fixture_case(case)
        assert not result["harness_rejected"]
        assert result["reports_valid"] is True

    def test_all_reports_promotion_blocked_true(self):
        from training.evaluation_harness import build_evaluation_report, run_all_metadata_gates
        case = build_valid_complete_candidate_fixture()
        candidate = case["_candidate"]
        gate_results = run_all_metadata_gates(candidate)
        for gr in gate_results:
            report = build_evaluation_report(candidate, gr)
            assert report["promotion_blocked"] is True

    def test_all_reports_promotion_decision_emitted_false(self):
        from training.evaluation_harness import build_evaluation_report, run_all_metadata_gates
        case = build_valid_complete_candidate_fixture()
        candidate = case["_candidate"]
        gate_results = run_all_metadata_gates(candidate)
        for gr in gate_results:
            report = build_evaluation_report(candidate, gr)
            assert report["promotion_decision_emitted"] is False

    def test_all_reports_metadata_only_true(self):
        from training.evaluation_harness import build_evaluation_report, run_all_metadata_gates
        case = build_valid_complete_candidate_fixture()
        candidate = case["_candidate"]
        gate_results = run_all_metadata_gates(candidate)
        for gr in gate_results:
            report = build_evaluation_report(candidate, gr)
            assert report["metadata_only"] is True

    def test_all_gates_produce_passing_results(self):
        case = build_valid_complete_candidate_fixture()
        result = run_fixture_case(case)
        assert result["all_expectations_met"], (
            f"Valid complete fixture: mismatches: {result.get('gate_expectation_mismatches')}"
        )

    def test_promotion_blocking_invariants_passes(self):
        case = build_valid_complete_candidate_fixture()
        result = run_fixture_case(case)
        assert result["gate_results"].get("promotion_blocking_invariants") == "pass"

    def test_audit_safe_json_ir_passes(self):
        case = build_valid_complete_candidate_fixture()
        result = run_fixture_case(case)
        assert result["gate_results"].get("audit_safe_json_ir_output") == "pass"


# ---------------------------------------------------------------------------
# Synthetic provenance gate coverage
# ---------------------------------------------------------------------------

class TestSyntheticProvenanceGateCoverage:
    def test_non_synthetic_fixture_returns_not_evaluated(self):
        case = build_non_synthetic_candidate_fixture()
        result = run_fixture_case(case)
        assert result["gate_results"].get("synthetic_provenance_integrity") == "not_evaluated"

    def test_non_synthetic_fixture_meets_expectations(self):
        case = build_non_synthetic_candidate_fixture()
        result = run_fixture_case(case)
        assert result["all_expectations_met"], (
            f"Non-synthetic mismatches: {result.get('gate_expectation_mismatches')}"
        )

    def test_synthetic_fixture_passes_synthetic_gate(self):
        case = build_synthetic_candidate_fixture()
        result = run_fixture_case(case)
        assert result["gate_results"].get("synthetic_provenance_integrity") == "pass"

    def test_malformed_synthetic_fails_gate(self):
        case = build_mutated_candidate_fixture("missing_synthetic_provenance")
        result = run_fixture_case(case)
        assert result["gate_results"].get("synthetic_provenance_integrity") == "fail"


# ---------------------------------------------------------------------------
# Missing refs fixture cases
# ---------------------------------------------------------------------------

class TestMissingRefsFixtures:
    def test_missing_dep_keystone_refs_fails_provenance_gate(self):
        case = build_mutated_candidate_fixture("missing_dep_keystone_refs")
        result = run_fixture_case(case)
        assert result["gate_results"].get("dep_keystone_govsec_provenance_completeness") in ("fail", "block")

    def test_missing_dep_keystone_refs_fails_constitutional_fidelity(self):
        case = build_mutated_candidate_fixture("missing_dep_keystone_refs")
        result = run_fixture_case(case)
        assert result["gate_results"].get("constitutional_fidelity") in ("fail", "block")

    def test_missing_dep_keystone_refs_meets_expectations(self):
        case = build_mutated_candidate_fixture("missing_dep_keystone_refs")
        result = run_fixture_case(case)
        assert result["all_expectations_met"], result.get("gate_expectation_mismatches")

    def test_missing_source_registry_refs_fails_gate(self):
        case = build_mutated_candidate_fixture("missing_source_registry_refs")
        result = run_fixture_case(case)
        assert result["gate_results"].get("source_registry_clearance_completeness") in ("fail", "block")

    def test_missing_source_registry_refs_meets_expectations(self):
        case = build_mutated_candidate_fixture("missing_source_registry_refs")
        result = run_fixture_case(case)
        assert result["all_expectations_met"], result.get("gate_expectation_mismatches")

    def test_missing_clearance_ledger_refs_fails_gate(self):
        case = build_mutated_candidate_fixture("missing_clearance_ledger_refs")
        result = run_fixture_case(case)
        assert result["gate_results"].get("clearance_ledger_completeness") in ("fail", "block")

    def test_missing_clearance_ledger_refs_meets_expectations(self):
        case = build_mutated_candidate_fixture("missing_clearance_ledger_refs")
        result = run_fixture_case(case)
        assert result["all_expectations_met"], result.get("gate_expectation_mismatches")

    def test_missing_dry_run_refs_fails_integrity_gate(self):
        case = build_mutated_candidate_fixture("missing_dry_run_refs")
        result = run_fixture_case(case)
        assert result["gate_results"].get("dry_run_integrity") in ("fail", "block")

    def test_missing_dry_run_refs_meets_expectations(self):
        case = build_mutated_candidate_fixture("missing_dry_run_refs")
        result = run_fixture_case(case)
        assert result["all_expectations_met"], result.get("gate_expectation_mismatches")


# ---------------------------------------------------------------------------
# Integrity violation fixtures
# ---------------------------------------------------------------------------

class TestIntegrityViolationFixtures:
    def test_tampered_lineage_hash_fails_audit_gate(self):
        case = build_mutated_candidate_fixture("tampered_lineage_hash")
        result = run_fixture_case(case)
        assert result["gate_results"].get("audit_safe_json_ir_output") in ("fail", "block")

    def test_tampered_lineage_hash_meets_expectations(self):
        case = build_mutated_candidate_fixture("tampered_lineage_hash")
        result = run_fixture_case(case)
        assert result["all_expectations_met"], result.get("gate_expectation_mismatches")

    def test_raw_prompt_leak_fails_audit_gate(self):
        case = build_mutated_candidate_fixture("raw_prompt_leak_violation")
        result = run_fixture_case(case)
        assert result["gate_results"].get("audit_safe_json_ir_output") in ("fail", "block")

    def test_raw_prompt_leak_meets_expectations(self):
        case = build_mutated_candidate_fixture("raw_prompt_leak_violation")
        result = run_fixture_case(case)
        assert result["all_expectations_met"], result.get("gate_expectation_mismatches")


# ---------------------------------------------------------------------------
# Harness rejection cases
# ---------------------------------------------------------------------------

_REJECTION_CASES = [
    "promotion_status_violation",
    "model_weights_present_violation",
    "runtime_deployment_violation",
    "store1_write_violation",
    "external_calls_violation",
    "adapter_checkpoint_path_violation",
]


class TestHarnessRejectionCases:
    @pytest.mark.parametrize("case_type", _REJECTION_CASES)
    def test_harness_rejects_before_gate_execution(self, case_type):
        case = build_mutated_candidate_fixture(case_type)
        result = run_fixture_case(case)
        assert result["harness_rejected"] is True, (
            f"{case_type}: expected harness to reject, but it did not. "
            f"Gate results: {result.get('gate_results')}"
        )

    @pytest.mark.parametrize("case_type", _REJECTION_CASES)
    def test_rejection_is_expected(self, case_type):
        case = build_mutated_candidate_fixture(case_type)
        result = run_fixture_case(case)
        assert result["rejection_ok"] is True

    @pytest.mark.parametrize("case_type", _REJECTION_CASES)
    def test_no_gates_run_after_rejection(self, case_type):
        case = build_mutated_candidate_fixture(case_type)
        result = run_fixture_case(case)
        assert result["gate_results"] == {}

    @pytest.mark.parametrize("case_type", _REJECTION_CASES)
    def test_promotion_blocked_in_rejection_result(self, case_type):
        case = build_mutated_candidate_fixture(case_type)
        result = run_fixture_case(case)
        assert result["promotion_blocked"] is True

    def test_promotion_status_violation_rejected(self):
        case = build_mutated_candidate_fixture("promotion_status_violation")
        assert case["expected_harness_rejection"] is True
        result = run_fixture_case(case)
        assert result["harness_rejected"] is True

    def test_model_weights_present_violation_rejected(self):
        case = build_mutated_candidate_fixture("model_weights_present_violation")
        result = run_fixture_case(case)
        assert result["harness_rejected"] is True

    def test_runtime_deployment_violation_rejected(self):
        case = build_mutated_candidate_fixture("runtime_deployment_violation")
        result = run_fixture_case(case)
        assert result["harness_rejected"] is True

    def test_store1_write_violation_rejected(self):
        case = build_mutated_candidate_fixture("store1_write_violation")
        result = run_fixture_case(case)
        assert result["harness_rejected"] is True

    def test_external_calls_violation_rejected(self):
        case = build_mutated_candidate_fixture("external_calls_violation")
        result = run_fixture_case(case)
        assert result["harness_rejected"] is True

    def test_adapter_checkpoint_path_violation_rejected(self):
        case = build_mutated_candidate_fixture("adapter_checkpoint_path_violation")
        result = run_fixture_case(case)
        assert result["harness_rejected"] is True


# ---------------------------------------------------------------------------
# Gate coverage: all 11 gates exercised
# ---------------------------------------------------------------------------

class TestGateCoverage:
    def test_all_11_gates_exercised_by_catalog(self):
        """Every TR-06A gate must appear in at least one fixture's expected_gate_results."""
        catalog = build_fixture_catalog()
        covered_gates = set()
        for case in catalog:
            covered_gates.update(case.get("expected_gate_results", {}).keys())
        uncovered = EVALUATION_GATES - covered_gates
        assert not uncovered, (
            f"The following gates are not covered by any fixture case: {sorted(uncovered)}"
        )

    def test_constitutional_fidelity_covered_by_pass_and_fail(self):
        valid = run_fixture_case(build_valid_complete_candidate_fixture())
        invalid = run_fixture_case(build_mutated_candidate_fixture("missing_dep_keystone_refs"))
        assert valid["gate_results"].get("constitutional_fidelity") == "pass"
        assert invalid["gate_results"].get("constitutional_fidelity") in ("fail", "block")

    def test_promotion_blocking_invariants_covered_by_pass_and_block(self):
        valid = run_fixture_case(build_valid_complete_candidate_fixture())
        assert valid["gate_results"].get("promotion_blocking_invariants") == "pass"
        # Build a candidate that bypasses harness but has wrong promotion_status in gate
        # (promotion_blocking_invariants gate checks candidate.promotion_status directly)
        from training.evaluation_harness import run_evaluation_gate
        case = build_mutated_candidate_fixture("valid_complete_metadata")
        c = case["_candidate"].copy()
        c["promotion_status"] = "eligible_for_future_evaluation"
        gr = run_evaluation_gate(c, "promotion_blocking_invariants")
        assert gr["result"] == "block"

    def test_store1_govmem_covered_by_pass_and_block(self):
        valid = run_fixture_case(build_valid_complete_candidate_fixture())
        assert valid["gate_results"].get("store1_govmem_boundary_preservation") == "pass"
        case_store1 = build_mutated_candidate_fixture("store1_write_violation")
        # store1_write_violation case is rejected by harness, not gate
        # Use a direct gate call to test the block path
        from training.evaluation_harness import run_evaluation_gate
        c = build_valid_complete_candidate_fixture()["_candidate"].copy()
        c["store1_write_allowed"] = True
        gr = run_evaluation_gate(c, "store1_govmem_boundary_preservation")
        assert gr["result"] == "block"

    def test_haap_refusal_behavior_covered(self):
        valid = run_fixture_case(build_valid_complete_candidate_fixture())
        # haap gate uses metadata only (dep_keystone + govsec_layer)
        assert valid["gate_results"].get("haap_refusal_behavior") in ("pass", "fail", "not_evaluated")


# ---------------------------------------------------------------------------
# run_fixture_case + summarize
# ---------------------------------------------------------------------------

class TestRunFixtureCaseAndSummarize:
    def test_run_valid_case_all_expectations_met(self):
        case = build_valid_complete_candidate_fixture()
        result = run_fixture_case(case)
        assert result["all_expectations_met"] is True

    def test_run_rejection_case_expectations_met(self):
        case = build_mutated_candidate_fixture("promotion_status_violation")
        result = run_fixture_case(case)
        assert result["all_expectations_met"] is True

    def test_summarize_all_pass(self):
        catalog = build_fixture_catalog()
        results = [run_fixture_case(case) for case in catalog]
        summary = summarize_fixture_results(results)
        assert summary["total_cases"] == len(CASE_TYPES)
        assert summary["promotion_blocked"] is True
        assert summary["all_cases_met_expectations"] is True, (
            f"Some cases did not meet expectations: "
            + str([r for r in results if not r.get("all_expectations_met")])
        )

    def test_summarize_empty(self):
        summary = summarize_fixture_results([])
        assert summary["total_cases"] == 0
        assert summary["promotion_blocked"] is True
        assert summary["all_cases_met_expectations"] is True

    def test_summarize_detects_failure(self):
        # Inject a synthetic failure result
        fake = {
            "all_expectations_met": False,
            "harness_rejected": False,
            "expected_harness_rejection": False,
            "case_type": "valid_complete_metadata",
        }
        summary = summarize_fixture_results([fake])
        assert summary["failed"] == 1
        assert summary["all_cases_met_expectations"] is False

    def test_run_fixture_case_saves_reports(self, tmp_path):
        case = build_valid_complete_candidate_fixture()
        result = run_fixture_case(case, out_dir=str(tmp_path))
        report_files = list(tmp_path.glob("er_*.json"))
        assert len(report_files) == len(EVALUATION_GATES)


# ---------------------------------------------------------------------------
# Module purity
# ---------------------------------------------------------------------------

class TestModulePurity:
    def test_no_external_provider_imports_in_fixture_builder(self):
        builder_path = Path(__file__).parent.parent / "evaluation_fixture_builder.py"
        src = builder_path.read_text()
        forbidden = [
            "import openai", "import anthropic", "import google.generativeai",
            "import groq", "import torch", "import tensorflow", "import transformers",
            "import boto3", "import huggingface_hub",
            "from openai", "from anthropic", "from google.generativeai",
            "from transformers", "from huggingface_hub",
        ]
        for token in forbidden:
            assert token not in src, (
                f"evaluation_fixture_builder.py contains forbidden import: {token!r}"
            )

    def test_no_model_weight_operations_in_fixture_builder(self):
        builder_path = Path(__file__).parent.parent / "evaluation_fixture_builder.py"
        src = builder_path.read_text()
        forbidden_ops = [
            "torch.load", "torch.save", "model.load_state_dict",
            "load_pretrained", ".from_pretrained", "LoraConfig",
        ]
        for op in forbidden_ops:
            assert op not in src, (
                f"evaluation_fixture_builder.py contains forbidden model-weight op: {op!r}"
            )

    def test_no_real_file_paths_in_fixtures(self):
        catalog = build_fixture_catalog()
        for case in catalog:
            c = case.get("_candidate", {})
            assert "model_weights_path" not in c or c.get("expected_harness_rejection")
