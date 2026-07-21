"""
TR-06B Metadata Evaluation Fixture Builder.

Builds a deterministic, in-memory fixture corpus for regression-testing the
TR-06A metadata evaluation harness. All fixtures are pure metadata — no network
access, no model loading, no real training, no promotion, no Store 1 writes.

The 15 fixture case types cover:
  - valid_complete_metadata       : reference pass case with synthetic provenance
  - non_synthetic_candidate       : honest not_evaluated for synthetic gate
  - missing_dep_keystone_refs     : provenance completeness gate fails
  - missing_source_registry_refs  : source registry gate fails
  - missing_clearance_ledger_refs : clearance ledger gate fails
  - missing_dry_run_refs          : dry-run integrity gate fails
  - missing_synthetic_provenance  : malformed synthetic refs → gate fails
  - tampered_lineage_hash         : hash mismatch → audit gate fails
  - raw_prompt_leak_violation     : oversized notes → audit gate fails
  - promotion_status_violation    : harness rejects before gate execution
  - model_weights_present_violation
  - runtime_deployment_violation
  - store1_write_violation
  - external_calls_violation
  - adapter_checkpoint_path_violation
"""

import hashlib
import json
from pathlib import Path

from training.evaluation_harness import (
    EVALUATION_GATES,
    EvaluationCandidateError,
    _assert_candidate_safe,
    build_evaluation_report,
    compute_lineage_hash,
    run_all_metadata_gates,
    save_evaluation_report,
    summarize_evaluation_reports,
    validate_evaluation_report,
)

SCHEMA_VERSION = "1.0.0"
CREATED_AT = "2026-06-27T00:00:00Z"

CASE_TYPES = frozenset({
    "valid_complete_metadata",
    "missing_dep_keystone_refs",
    "missing_source_registry_refs",
    "missing_clearance_ledger_refs",
    "missing_dry_run_refs",
    "missing_synthetic_provenance",
    "non_synthetic_candidate",
    "tampered_lineage_hash",
    "promotion_status_violation",
    "model_weights_present_violation",
    "runtime_deployment_violation",
    "store1_write_violation",
    "external_calls_violation",
    "adapter_checkpoint_path_violation",
    "raw_prompt_leak_violation",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _artifact_id_for_case(case_type: str) -> str:
    raw = f"tr06b-candidate:{case_type}"
    return "MA-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _fixture_case_id(case_type: str) -> str:
    raw = f"tr06b-fixture:{case_type}"
    return "FC-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _base_lineage(artifact_id: str) -> dict:
    lin = {
        "lineage_record_id":    "LR-" + hashlib.sha256(artifact_id.encode()).hexdigest()[:16],
        "schema_version":       "1.0.0",
        "created_at":           CREATED_AT,
        "artifact_id":          artifact_id,
        "artifact_type":        "dry_run_adapter_candidate",
        "parent_artifacts":     [],
        "dep_keystone_ingress_refs":               ["DKI-fix-l1001-001"],
        "dep_keystone_evidence_sha256_refs":
            ["dep-keystone://evidence.sha256/L1-001/tr06b"],
        "dep_keystone_verification_report_refs":
            ["dep-keystone://verification-report.json/L1-001/tr06b"],
        "source_registry_refs":               ["source_registry:L1-001"],
        "clearance_ledger_refs":              ["clearance_ledger:LE-fix-001"],
        "synthetic_manifest_refs":            [],
        "synthetic_review_bridge_refs":       [],
        "dataset_manifest_refs":              ["dataset:DS-fix-001"],
        "dry_run_envelope_refs":              ["dry_run:DR-fix00000000001"],
        "training_job_contract_refs":         [],
        "evaluation_refs":                    [],
        "promotion_decision_refs":            [],
        "lineage_hash":                       None,  # computed below
        "previous_lineage_hash":              "0" * 64,
        "governance_flags": {
            "training_allowed":           False,
            "model_weights_present":      False,
            "store1_write_allowed":       False,
            "runtime_deployment_allowed": False,
            "external_calls_allowed":     False,
            "operator_promotion_required": True,
        },
        "notes": "TR-06B fixture lineage record.",
    }
    lin["lineage_hash"] = compute_lineage_hash(lin)
    return lin


def _base_candidate(case_type: str) -> dict:
    artifact_id = _artifact_id_for_case(case_type)
    lin = _base_lineage(artifact_id)
    return {
        "model_artifact_id":          artifact_id,
        "artifact_type":              "dry_run_adapter_candidate",
        "artifact_status":            "dry_run_only",
        "created_at":                 CREATED_AT,
        "created_by":                 "TR06B_FIXTURE_BUILDER",
        "lineage_record_id":          lin["lineage_record_id"],
        "base_model_reference":       None,
        "adapter_reference":          None,
        "dep_keystone_ingress_ref":   "DKI-fix-l1001-001",
        "dep_keystone_evidence_sha256_ref":
            "dep-keystone://evidence.sha256/L1-001/tr06b",
        "dep_keystone_verification_report_ref":
            "dep-keystone://verification-report.json/L1-001/tr06b",
        "dataset_manifest_ref":       "dataset:DS-fix-001",
        "dry_run_envelope_ref":       "dry_run:DR-fix00000000001",
        "training_job_contract_ref":  None,
        "evaluation_ref":             None,
        "promotion_status":           "not_promoted",
        "training_allowed":           False,
        "model_weights_present":      False,
        "runtime_deployment_allowed": False,
        "store1_write_allowed":       False,
        "external_calls_allowed":     False,
        "operator_promotion_required": True,
        "checksum_manifest":          hashlib.sha256(artifact_id.encode()).hexdigest(),
        "lineage":                    lin,
        "provenance": {
            "source_id":       "L1-001",
            "requested_use":   "sft_candidate",
            "ledger_entry_id": "LE-fix-001",
            "dataset_id":      "DS-fix-001",
            "dry_run_id":      "DR-fix00000000001",
            "govsec_layer":    "layer_zero_reality_formation",
        },
        "notes": f"TR-06B fixture candidate for case_type={case_type!r}.",
    }


def _make_fixture_case(
    case_type: str,
    candidate: dict,
    candidate_mutations: dict,
    lineage_mutations: dict,
    expected_gate_results: dict,
    expected_harness_rejection: bool,
    notes: str,
) -> dict:
    return {
        "fixture_case_id":          _fixture_case_id(case_type),
        "schema_version":           SCHEMA_VERSION,
        "created_at":               CREATED_AT,
        "case_type":                case_type,
        "candidate_artifact_id":    candidate.get("model_artifact_id", ""),
        "candidate_mutations":      candidate_mutations,
        "lineage_mutations":        lineage_mutations,
        "expected_gate_results":    expected_gate_results,
        "expected_harness_rejection": expected_harness_rejection,
        "requires_live_inference":  False,
        "metadata_only":            True,
        "notes":                    notes,
        "_candidate":               candidate,
    }


# ---------------------------------------------------------------------------
# Public fixture factories
# ---------------------------------------------------------------------------

def build_valid_complete_candidate_fixture() -> dict:
    """Reference fixture: all metadata complete, synthetic provenance present.

    All 11 TR-06A metadata gates should pass.
    """
    c = _base_candidate("valid_complete_metadata")
    c["lineage"]["synthetic_manifest_refs"] = [
        "synthetic://manifest/syn-001/tr06b"
    ]
    c["lineage"]["synthetic_review_bridge_refs"] = [
        "synthetic://bridge/syn-001/tr06b"
    ]
    # Recompute hash (synthetic refs not in hash, but keeps it consistent)
    c["lineage"]["lineage_hash"] = compute_lineage_hash(c["lineage"])

    expected = {gate: "pass" for gate in EVALUATION_GATES}
    return _make_fixture_case(
        case_type="valid_complete_metadata",
        candidate=c,
        candidate_mutations={},
        lineage_mutations={
            "synthetic_manifest_refs": "added valid synthetic ref",
            "synthetic_review_bridge_refs": "added valid synthetic bridge ref",
        },
        expected_gate_results=expected,
        expected_harness_rejection=False,
        notes=(
            "Reference case: valid candidate with complete metadata and synthetic provenance. "
            "All 11 metadata gates should pass."
        ),
    )


def build_non_synthetic_candidate_fixture() -> dict:
    """Non-synthetic fixture: synthetic provenance gate returns not_evaluated.

    Proves the gate is honest about the absence of synthetic lineage rather
    than claiming 'pass' for something it cannot evaluate.
    """
    c = _base_candidate("non_synthetic_candidate")
    assert c["lineage"]["synthetic_manifest_refs"] == []
    assert c["lineage"]["synthetic_review_bridge_refs"] == []

    expected = {gate: "pass" for gate in EVALUATION_GATES}
    expected["synthetic_provenance_integrity"] = "not_evaluated"
    return _make_fixture_case(
        case_type="non_synthetic_candidate",
        candidate=c,
        candidate_mutations={},
        lineage_mutations={},
        expected_gate_results=expected,
        expected_harness_rejection=False,
        notes=(
            "Non-synthetic candidate: synthetic_provenance_integrity must return "
            "not_evaluated — not pass — because there are no synthetic refs. "
            "All other metadata gates should pass."
        ),
    )


def build_synthetic_candidate_fixture() -> dict:
    """Return a candidate fixture with synthetic provenance present.

    Identical to build_valid_complete_candidate_fixture() but named explicitly
    for tests that require a candidate with synthetic lineage.
    """
    return build_valid_complete_candidate_fixture()


def build_mutated_candidate_fixture(case_type: str) -> dict:
    """Build a fixture case for the given mutation case_type.

    Handles all 13 case types beyond valid_complete_metadata and
    non_synthetic_candidate.
    """
    if case_type == "valid_complete_metadata":
        return build_valid_complete_candidate_fixture()
    if case_type == "non_synthetic_candidate":
        return build_non_synthetic_candidate_fixture()

    c = _base_candidate(case_type)

    # ------------------------------------------------------------------ #
    # Missing provenance ref cases                                         #
    # ------------------------------------------------------------------ #

    if case_type == "missing_dep_keystone_refs":
        del c["dep_keystone_ingress_ref"]
        del c["dep_keystone_evidence_sha256_ref"]
        del c["dep_keystone_verification_report_ref"]
        c["lineage"]["dep_keystone_ingress_refs"] = []
        c["lineage"]["dep_keystone_evidence_sha256_refs"] = []
        c["lineage"]["dep_keystone_verification_report_refs"] = []
        c["lineage"]["lineage_hash"] = compute_lineage_hash(c["lineage"])
        return _make_fixture_case(
            case_type=case_type,
            candidate=c,
            candidate_mutations={
                "dep_keystone_ingress_ref": "removed",
                "dep_keystone_evidence_sha256_ref": "removed",
                "dep_keystone_verification_report_ref": "removed",
            },
            lineage_mutations={
                "dep_keystone_ingress_refs": "emptied",
                "dep_keystone_evidence_sha256_refs": "emptied",
                "dep_keystone_verification_report_refs": "emptied",
            },
            expected_gate_results={
                "dep_keystone_govsec_provenance_completeness": "fail",
                "constitutional_fidelity": "fail",
            },
            expected_harness_rejection=False,
            notes=(
                "DEP.KEYSTONE refs removed from candidate and lineage. "
                "dep_keystone_govsec_provenance_completeness and "
                "constitutional_fidelity should fail."
            ),
        )

    if case_type == "missing_source_registry_refs":
        c["lineage"]["source_registry_refs"] = []
        c["lineage"]["lineage_hash"] = compute_lineage_hash(c["lineage"])
        return _make_fixture_case(
            case_type=case_type,
            candidate=c,
            candidate_mutations={},
            lineage_mutations={"source_registry_refs": "emptied"},
            expected_gate_results={
                "source_registry_clearance_completeness": "fail",
                "constitutional_fidelity": "fail",
            },
            expected_harness_rejection=False,
            notes=(
                "source_registry_refs emptied in lineage. "
                "source_registry_clearance_completeness and constitutional_fidelity should fail."
            ),
        )

    if case_type == "missing_clearance_ledger_refs":
        c["lineage"]["clearance_ledger_refs"] = []
        c["lineage"]["lineage_hash"] = compute_lineage_hash(c["lineage"])
        del c["provenance"]["ledger_entry_id"]
        return _make_fixture_case(
            case_type=case_type,
            candidate=c,
            candidate_mutations={},
            lineage_mutations={
                "clearance_ledger_refs": "emptied",
                "provenance.ledger_entry_id": "removed",
            },
            expected_gate_results={
                "clearance_ledger_completeness": "fail",
                "constitutional_fidelity": "fail",
            },
            expected_harness_rejection=False,
            notes=(
                "clearance_ledger_refs emptied; ledger_entry_id removed from provenance. "
                "clearance_ledger_completeness and constitutional_fidelity should fail."
            ),
        )

    if case_type == "missing_dry_run_refs":
        c["lineage"]["dry_run_envelope_refs"] = []
        c["lineage"]["lineage_hash"] = compute_lineage_hash(c["lineage"])
        return _make_fixture_case(
            case_type=case_type,
            candidate=c,
            candidate_mutations={},
            lineage_mutations={"dry_run_envelope_refs": "emptied"},
            expected_gate_results={
                "dry_run_integrity": "fail",
                "routing_correctness": "fail",
            },
            expected_harness_rejection=False,
            notes=(
                "dry_run_envelope_refs emptied in lineage. "
                "dry_run_integrity and routing_correctness should fail."
            ),
        )

    # ------------------------------------------------------------------ #
    # Synthetic provenance cases                                           #
    # ------------------------------------------------------------------ #

    if case_type == "missing_synthetic_provenance":
        # Has synthetic marker but refs are invalid (empty strings)
        c["lineage"]["synthetic_manifest_refs"] = [""]
        c["lineage"]["synthetic_review_bridge_refs"] = ["valid://bridge/syn-001"]
        c["lineage"]["lineage_hash"] = compute_lineage_hash(c["lineage"])
        return _make_fixture_case(
            case_type=case_type,
            candidate=c,
            candidate_mutations={},
            lineage_mutations={
                "synthetic_manifest_refs": "set to [''] (empty string — invalid)",
                "synthetic_review_bridge_refs": "set to valid ref",
            },
            expected_gate_results={
                "synthetic_provenance_integrity": "fail",
            },
            expected_harness_rejection=False,
            notes=(
                "Candidate marked synthetic but synthetic_manifest_refs contains an empty string. "
                "synthetic_provenance_integrity should fail."
            ),
        )

    # ------------------------------------------------------------------ #
    # Tampered lineage hash                                                #
    # ------------------------------------------------------------------ #

    if case_type == "tampered_lineage_hash":
        # Compute real hash first, then overwrite with a deliberately wrong value
        real_hash = compute_lineage_hash(c["lineage"])
        tampered = "0" * 64
        assert tampered != real_hash, "Tampered hash collides with real hash (impossible in practice)"
        c["lineage"]["lineage_hash"] = tampered
        return _make_fixture_case(
            case_type=case_type,
            candidate=c,
            candidate_mutations={},
            lineage_mutations={"lineage_hash": f"deliberately set to {'0'*16}... (wrong)"},
            expected_gate_results={
                "audit_safe_json_ir_output": "fail",
            },
            expected_harness_rejection=False,
            notes=(
                "lineage_hash overwritten with zeros. "
                "audit_safe_json_ir_output should detect the mismatch and fail."
            ),
        )

    # ------------------------------------------------------------------ #
    # Raw prompt leak                                                      #
    # ------------------------------------------------------------------ #

    if case_type == "raw_prompt_leak_violation":
        c["notes"] = "LEAKED PROMPT CONTENT: " + "A" * 5000
        return _make_fixture_case(
            case_type=case_type,
            candidate=c,
            candidate_mutations={"notes": "set to >4096-char string simulating raw prompt leak"},
            lineage_mutations={},
            expected_gate_results={
                "audit_safe_json_ir_output": "fail",
            },
            expected_harness_rejection=False,
            notes=(
                "notes field set to >4096 chars to simulate raw prompt/example text leak. "
                "audit_safe_json_ir_output should detect and fail."
            ),
        )

    # ------------------------------------------------------------------ #
    # Harness rejection cases (unsafe flags / forbidden fields)            #
    # ------------------------------------------------------------------ #

    _rejection_mutations = {
        "promotion_status_violation": {
            "field": "promotion_status",
            "value": "promoted",
            "mutation_note": "set to 'promoted'",
        },
        "model_weights_present_violation": {
            "field": "model_weights_present",
            "value": True,
            "mutation_note": "set to True",
        },
        "runtime_deployment_violation": {
            "field": "runtime_deployment_allowed",
            "value": True,
            "mutation_note": "set to True",
        },
        "store1_write_violation": {
            "field": "store1_write_allowed",
            "value": True,
            "mutation_note": "set to True",
        },
        "external_calls_violation": {
            "field": "external_calls_allowed",
            "value": True,
            "mutation_note": "set to True",
        },
        "adapter_checkpoint_path_violation": {
            "field": "adapter_checkpoint_path",
            "value": "/tmp/lora_adapter.pt",
            "mutation_note": "forbidden field added",
        },
    }

    if case_type in _rejection_mutations:
        spec = _rejection_mutations[case_type]
        c[spec["field"]] = spec["value"]
        return _make_fixture_case(
            case_type=case_type,
            candidate=c,
            candidate_mutations={spec["field"]: spec["mutation_note"]},
            lineage_mutations={},
            expected_gate_results={},  # harness rejects before gate execution
            expected_harness_rejection=True,
            notes=(
                f"Candidate has {spec['field']}={spec['value']!r}. "
                f"TR-06A harness must reject this candidate before any gate runs."
            ),
        )

    raise ValueError(f"Unknown case_type: {case_type!r}. Valid: {sorted(CASE_TYPES)}")


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def build_fixture_catalog() -> list:
    """Build and return all 15 fixture cases."""
    catalog = [
        build_valid_complete_candidate_fixture(),
        build_non_synthetic_candidate_fixture(),
    ]
    for ct in sorted(CASE_TYPES - {"valid_complete_metadata", "non_synthetic_candidate"}):
        catalog.append(build_mutated_candidate_fixture(ct))
    return catalog


def write_fixture_catalog(out_dir: str) -> Path:
    """Write fixture case metadata (without _candidate) to out_dir/fixture_catalog.json."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog = build_fixture_catalog()
    # Strip operational _candidate field — catalog is metadata only
    catalog_meta = [{k: v for k, v in case.items() if k != "_candidate"} for case in catalog]
    path = out / "fixture_catalog.json"
    path.write_text(json.dumps(catalog_meta, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_fixture_case(case: dict, out_dir: str = None) -> dict:
    """Run a fixture case through the TR-06A harness. Returns a result dict."""
    candidate = case.get("_candidate")
    if candidate is None:
        raise ValueError(
            f"Fixture case {case.get('fixture_case_id')!r} has no _candidate. "
            "Use build_fixture_catalog() or a builder function to get runnable cases."
        )

    expected_rejection = case.get("expected_harness_rejection", False)
    expected_results = case.get("expected_gate_results", {})

    # 1. Try harness safety check
    try:
        _assert_candidate_safe(candidate)
        harness_rejected = False
        rejection_reason = None
    except EvaluationCandidateError as exc:
        harness_rejected = True
        rejection_reason = str(exc)
        rejection_ok = expected_rejection is True
        return {
            "fixture_case_id":          case["fixture_case_id"],
            "case_type":                case["case_type"],
            "harness_rejected":         True,
            "rejection_reason":         rejection_reason,
            "expected_harness_rejection": expected_rejection,
            "rejection_ok":             rejection_ok,
            "gate_results":             {},
            "expected_gate_results":    expected_results,
            "gate_expectation_mismatches": [],
            "all_expectations_met":     rejection_ok,
            "promotion_blocked":        True,
            "reports_valid":            True,
        }

    # 2. Run all gates
    gate_results_raw = run_all_metadata_gates(candidate)
    gate_results = {gr["gate"]: gr["result"] for gr in gate_results_raw}

    # 3. Check expectations
    mismatches = []
    for gate, expected in expected_results.items():
        actual = gate_results.get(gate)
        if actual != expected:
            mismatches.append(
                f"{gate}: expected={expected!r}, actual={actual!r}"
            )

    # 4. Build, validate, and optionally save reports
    reports = []
    for gr in gate_results_raw:
        rpt = build_evaluation_report(
            candidate, gr, evaluated_by="TR06B_FIXTURE_RUNNER"
        )
        validate_evaluation_report(rpt)
        if out_dir:
            save_evaluation_report(rpt, out_dir)
        reports.append(rpt)

    rejection_ok = not expected_rejection

    return {
        "fixture_case_id":          case["fixture_case_id"],
        "case_type":                case["case_type"],
        "harness_rejected":         False,
        "rejection_reason":         None,
        "expected_harness_rejection": expected_rejection,
        "rejection_ok":             rejection_ok,
        "gate_results":             gate_results,
        "expected_gate_results":    expected_results,
        "gate_expectation_mismatches": mismatches,
        "all_expectations_met":     rejection_ok and len(mismatches) == 0,
        "promotion_blocked":        True,
        "reports_valid":            True,
    }


def summarize_fixture_results(results: list) -> dict:
    """Aggregate a list of run_fixture_case results into a summary dict."""
    total = len(results)
    passed = sum(1 for r in results if r.get("all_expectations_met"))
    failed = total - passed
    rejection_mismatches = [
        r["case_type"]
        for r in results
        if r.get("harness_rejected") != r.get("expected_harness_rejection")
    ]
    return {
        "total_cases":               total,
        "passed":                    passed,
        "failed":                    failed,
        "all_cases_met_expectations": failed == 0,
        "rejection_mismatches":      rejection_mismatches,
        "any_rejection_mismatch":    bool(rejection_mismatches),
        "promotion_blocked":         True,
    }
