"""
TR-04D tests — DEP.KEYSTONE / GovSec V2 Training Ingress Gate.

Recon result (2026-06-27): No pre-existing DEP.KEYSTONE / GovSec training-ingress
gate was found in the LOGOS ASF codebase. All matches for DEP/KEYSTONE/GovSec/
Layer Zero/admissibility/ingress/sbom in training/, abigail/, governance-spine/,
agents/, and docs/ were either department IDs (DEPT-*) or env-var references
(GOVMEM_DEPARTMENT_ID). No callable training-ingress gate existed.
dep_keystone_ingress.py implements that gate as a new narrow bridge (TR-04D).

TR-05A semantic alignment: DEP.KEYSTONE is LogosGSInc/dep.keystone — a standalone
supply-chain trust product. Abigail references its trust-bundle outputs
(verification-report.json, evidence.sha256, sbom.cdx.json). Abigail does not
redefine or duplicate DEP.KEYSTONE. GovSec V2 / Layer Zero is the broader
training-admissibility doctrine. Source Registry and Clearance Ledger are
separate, independent gates.
"""
import ast
import json
from pathlib import Path

import pytest

from training.dep_keystone_ingress import (
    INGRESS_VERSION,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    VALID_DEP_KEYSTONE_STATUSES,
    VALID_GOVSEC_ADMISSIBILITY_DECISIONS,
    VALID_GOVSEC_ADMISSIBILITY_STATUSES,
    VALID_GOVSEC_LAYERS,
    VALID_NEXT_GATES,
    KeystoneIngressBlockedError,
    KeystoneIngressNotAllowedError,
    KeystoneIngressValidationError,
    assert_training_ingress_allowed,
    load_ingress_record,
    summarize_ingress,
    validate_ingress_record,
)

_TRAINING_DIR = Path(__file__).resolve().parent.parent


def _valid_ingress(**overrides) -> dict:
    """Factory for a minimal valid approved TR-04D ingress record."""
    base = {
        "dep_keystone_ingress_id":   "DKI-test-l1001-001",
        "schema_version":            "1.0.0",
        "created_at":                "2026-06-27T00:00:00Z",
        "source_id":                 "L1-001",
        "source_name":               "Buildspec Volumes I, II, III",
        "source_type":               "logos_owned_doctrine",
        "classification":            "LOGOS_INTERNAL",
        # DEP.KEYSTONE trust-bundle fields (from LogosGSInc/dep.keystone)
        "dep_keystone_project_name": "LogosGSInc/dep.keystone",
        "dep_keystone_status":       "VERIFIED",
        "dep_keystone_trust_score":  95,
        "dep_keystone_findings_count": 0,
        "dep_keystone_haap_drs_escalation_required": False,
        "dep_keystone_verification_report_ref":
            "dep-keystone://verification-report.json/L1-001/v1",
        "dep_keystone_evidence_sha256_ref":
            "dep-keystone://evidence.sha256/L1-001/v1",
        "dep_keystone_sbom_ref":     "dep-keystone://sbom.cdx.json/L1-001/v1",
        "dep_keystone_trust_cert_ref": "dep-keystone://trust-cert/L1-001/v1",
        # Abigail artifact hash
        "artifact_sha256":           "b" * 64,
        # GovSec V2 training-admissibility fields
        "govsec_admissibility_status":   "approved",
        "govsec_admissibility_decision": "accepted_for_clearance",
        "govsec_layer":              "layer_zero_reality_formation",
        "reality_formation_input":   True,
        "ingress_actor_id":          "TEST_INGRESS_OP_001",
        "ingress_actor_role":        "ingress_reviewer",
        "operator_review_required":  True,
        "training_pipeline_allowed": True,
        "allowed_next_gates": [
            "tr04a_source_registry",
            "tr04a_clearance_ledger",
            "tr03_dataset_builder",
            "tr04b_dry_run",
            "tr05_model_registry",
        ],
        "notes": "Test ingress record for L1-001.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TestSchema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_schema_file_exists(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        assert schema_path.exists(), "DEP_KEYSTONE_TRAINING_INGRESS.schema.json not found"

    def test_schema_is_valid_json(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        assert data["$id"] == "logos-asf:training:dep-keystone-training-ingress:v1.0.0"

    def test_schema_required_fields_match_module(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema_required = set(schema["required"])
        assert schema_required == REQUIRED_FIELDS

    def test_schema_has_govsec_admissibility_status_enum(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        enum_vals = set(schema["properties"]["govsec_admissibility_status"]["enum"])
        assert enum_vals == VALID_GOVSEC_ADMISSIBILITY_STATUSES

    def test_schema_has_dep_keystone_status_enum(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        enum_vals = set(schema["properties"]["dep_keystone_status"]["enum"])
        assert enum_vals == VALID_DEP_KEYSTONE_STATUSES

    def test_schema_has_allowed_next_gates_enum(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        gate_enum = set(schema["properties"]["allowed_next_gates"]["items"]["enum"])
        assert gate_enum == VALID_NEXT_GATES

    def test_schema_no_additional_properties(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema.get("additionalProperties") is False


# ---------------------------------------------------------------------------
# TestReconResult
# ---------------------------------------------------------------------------

class TestReconResult:
    def test_recon_no_prior_gate_documented_in_module(self):
        src = (_TRAINING_DIR / "dep_keystone_ingress.py").read_text(encoding="utf-8")
        assert "No pre-existing DEP.KEYSTONE" in src
        assert "department identifiers" in src

    def test_source_registry_schema_has_optional_dep_keystone_ingress_id(self):
        sr_schema = _TRAINING_DIR / "SOURCE_REGISTRY.schema.json"
        schema = json.loads(sr_schema.read_text(encoding="utf-8"))
        entry_props = schema["$defs"]["SourceEntry"]["properties"]
        assert "dep_keystone_ingress_id" in entry_props
        required = schema["$defs"]["SourceEntry"].get("required", [])
        assert "dep_keystone_ingress_id" not in required


# ---------------------------------------------------------------------------
# TestLoadIngressRecord
# ---------------------------------------------------------------------------

class TestLoadIngressRecord:
    def test_load_valid_file(self, tmp_path):
        rec = _valid_ingress()
        p = tmp_path / "ingress.json"
        p.write_text(json.dumps(rec), encoding="utf-8")
        loaded = load_ingress_record(p)
        assert loaded["dep_keystone_ingress_id"] == rec["dep_keystone_ingress_id"]

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(KeystoneIngressValidationError, match="not found"):
            load_ingress_record(tmp_path / "no_such_file.json")

    def test_load_invalid_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{ not valid json }", encoding="utf-8")
        with pytest.raises(KeystoneIngressValidationError, match="not valid JSON"):
            load_ingress_record(p)


# ---------------------------------------------------------------------------
# TestValidateIngressRecord
# ---------------------------------------------------------------------------

class TestValidateIngressRecord:
    def test_valid_record_passes(self):
        result = validate_ingress_record(_valid_ingress())
        assert result["valid"] is True
        assert result["govsec_admissibility_status"] == "approved"
        assert result["dep_keystone_status"] == "VERIFIED"

    def test_missing_required_field_raises(self):
        rec = _valid_ingress()
        del rec["dep_keystone_status"]
        with pytest.raises(KeystoneIngressValidationError, match="dep_keystone_status"):
            validate_ingress_record(rec)

    def test_multiple_missing_fields_reported(self):
        rec = _valid_ingress()
        del rec["dep_keystone_status"]
        del rec["dep_keystone_trust_score"]
        with pytest.raises(KeystoneIngressValidationError, match="2 error"):
            validate_ingress_record(rec)

    def test_invalid_govsec_admissibility_status_raises(self):
        rec = _valid_ingress(govsec_admissibility_status="unknown_status")
        with pytest.raises(KeystoneIngressValidationError, match="govsec_admissibility_status"):
            validate_ingress_record(rec)

    def test_invalid_govsec_admissibility_decision_raises(self):
        rec = _valid_ingress(govsec_admissibility_decision="maybe")
        with pytest.raises(KeystoneIngressValidationError, match="govsec_admissibility_decision"):
            validate_ingress_record(rec)

    def test_invalid_dep_keystone_status_raises(self):
        rec = _valid_ingress(dep_keystone_status="UNKNOWN")
        with pytest.raises(KeystoneIngressValidationError, match="dep_keystone_status"):
            validate_ingress_record(rec)

    def test_invalid_govsec_layer_raises(self):
        rec = _valid_ingress(govsec_layer="made_up_layer")
        with pytest.raises(KeystoneIngressValidationError, match="govsec_layer"):
            validate_ingress_record(rec)

    def test_invalid_next_gate_raises(self):
        rec = _valid_ingress(allowed_next_gates=["tr04a_source_registry", "not_a_real_gate"])
        with pytest.raises(KeystoneIngressValidationError, match="allowed_next_gates"):
            validate_ingress_record(rec)


# ---------------------------------------------------------------------------
# TestAssertTrainingIngressAllowed
# ---------------------------------------------------------------------------

class TestAssertTrainingIngressAllowed:
    def test_approved_ingress_clears(self):
        result = assert_training_ingress_allowed(_valid_ingress())
        assert result["cleared"] is True
        assert result["govsec_admissibility_status"] == "approved"
        assert result["govsec_admissibility_decision"] == "accepted_for_clearance"

    def test_approved_ingress_with_tr04a_source_registry(self):
        result = assert_training_ingress_allowed(
            _valid_ingress(), next_gate="tr04a_source_registry"
        )
        assert result["cleared"] is True
        assert result["next_gate"] == "tr04a_source_registry"

    def test_approved_ingress_with_tr03_when_listed(self):
        rec = _valid_ingress(allowed_next_gates=["tr04a_source_registry", "tr03_dataset_builder"])
        result = assert_training_ingress_allowed(rec, next_gate="tr03_dataset_builder")
        assert result["cleared"] is True

    def test_tr03_blocked_when_not_listed(self):
        rec = _valid_ingress(allowed_next_gates=["tr04a_source_registry"])
        with pytest.raises(KeystoneIngressNotAllowedError, match="tr03_dataset_builder"):
            assert_training_ingress_allowed(rec, next_gate="tr03_dataset_builder")

    # DEP.KEYSTONE status tests
    def test_dep_keystone_status_verified_and_score_passes(self):
        rec = _valid_ingress(dep_keystone_status="VERIFIED", dep_keystone_trust_score=95)
        result = assert_training_ingress_allowed(rec)
        assert result["cleared"] is True
        assert result["dep_keystone_status"] == "VERIFIED"
        assert result["dep_keystone_trust_score"] == 95

    def test_dep_keystone_status_failed_blocks(self):
        rec = _valid_ingress(dep_keystone_status="FAILED")
        with pytest.raises(KeystoneIngressBlockedError, match="FAILED"):
            assert_training_ingress_allowed(rec)

    def test_dep_keystone_trust_score_below_70_blocks(self):
        rec = _valid_ingress(dep_keystone_trust_score=65)
        with pytest.raises(KeystoneIngressNotAllowedError, match="trust_score"):
            assert_training_ingress_allowed(rec)

    def test_dep_keystone_trust_score_exactly_70_passes(self):
        rec = _valid_ingress(dep_keystone_trust_score=70)
        result = assert_training_ingress_allowed(rec)
        assert result["cleared"] is True

    def test_dep_keystone_haap_escalation_required_blocks(self):
        rec = _valid_ingress(dep_keystone_haap_drs_escalation_required=True)
        with pytest.raises(KeystoneIngressNotAllowedError, match="haap"):
            assert_training_ingress_allowed(rec)

    # DEP.KEYSTONE evidence ref tests
    def test_missing_dep_keystone_evidence_sha256_ref_blocks(self):
        rec = _valid_ingress(dep_keystone_evidence_sha256_ref="")
        with pytest.raises(KeystoneIngressNotAllowedError, match="dep_keystone_evidence_sha256_ref"):
            assert_training_ingress_allowed(rec)

    def test_missing_dep_keystone_verification_report_ref_blocks(self):
        rec = _valid_ingress(dep_keystone_verification_report_ref="")
        with pytest.raises(KeystoneIngressNotAllowedError, match="dep_keystone_verification_report_ref"):
            assert_training_ingress_allowed(rec)

    def test_missing_dep_keystone_sbom_ref_blocks(self):
        rec = _valid_ingress(dep_keystone_sbom_ref="")
        with pytest.raises(KeystoneIngressNotAllowedError, match="dep_keystone_sbom_ref"):
            assert_training_ingress_allowed(rec)

    def test_missing_artifact_sha256_blocks(self):
        rec = _valid_ingress(artifact_sha256="")
        with pytest.raises(KeystoneIngressNotAllowedError, match="artifact_sha256"):
            assert_training_ingress_allowed(rec)

    # GovSec status tests
    def test_govsec_pending_status_blocks(self):
        rec = _valid_ingress(govsec_admissibility_status="pending")
        with pytest.raises(KeystoneIngressNotAllowedError, match="pending"):
            assert_training_ingress_allowed(rec)

    def test_govsec_draft_status_blocks(self):
        rec = _valid_ingress(govsec_admissibility_status="draft")
        with pytest.raises(KeystoneIngressNotAllowedError, match="draft"):
            assert_training_ingress_allowed(rec)

    def test_govsec_blocked_status_raises_blocked_error(self):
        rec = _valid_ingress(govsec_admissibility_status="blocked")
        with pytest.raises(KeystoneIngressBlockedError, match="blocked"):
            assert_training_ingress_allowed(rec)

    def test_govsec_rejected_status_raises_blocked_error(self):
        rec = _valid_ingress(govsec_admissibility_status="rejected")
        with pytest.raises(KeystoneIngressBlockedError, match="rejected"):
            assert_training_ingress_allowed(rec)

    def test_govsec_archived_status_raises_blocked_error(self):
        rec = _valid_ingress(govsec_admissibility_status="archived")
        with pytest.raises(KeystoneIngressBlockedError, match="archived"):
            assert_training_ingress_allowed(rec)

    def test_training_pipeline_allowed_false_blocks(self):
        rec = _valid_ingress(training_pipeline_allowed=False)
        with pytest.raises(KeystoneIngressNotAllowedError, match="training_pipeline_allowed"):
            assert_training_ingress_allowed(rec)

    def test_wrong_source_id_blocks(self):
        rec = _valid_ingress(source_id="L1-001")
        with pytest.raises(KeystoneIngressNotAllowedError, match="source_id mismatch"):
            assert_training_ingress_allowed(rec, source_id="L1-003")

    def test_correct_source_id_passes(self):
        rec = _valid_ingress(source_id="L1-001")
        result = assert_training_ingress_allowed(rec, source_id="L1-001")
        assert result["cleared"] is True

    def test_wrong_next_gate_blocks(self):
        rec = _valid_ingress(allowed_next_gates=["tr04a_source_registry"])
        with pytest.raises(KeystoneIngressNotAllowedError, match="not in allowed_next_gates"):
            assert_training_ingress_allowed(rec, next_gate="tr05_model_registry")

    def test_wrong_govsec_admissibility_decision_blocks(self):
        rec = _valid_ingress(govsec_admissibility_decision="requires_more_evidence")
        with pytest.raises(KeystoneIngressNotAllowedError, match="govsec_admissibility_decision"):
            assert_training_ingress_allowed(rec)

    def test_clearance_result_includes_govsec_layer(self):
        result = assert_training_ingress_allowed(_valid_ingress())
        assert result["govsec_layer"] == "layer_zero_reality_formation"
        assert result["reality_formation_input"] is True

    def test_clearance_result_includes_dep_keystone_status(self):
        result = assert_training_ingress_allowed(_valid_ingress())
        assert result["dep_keystone_status"] == "VERIFIED"
        assert result["dep_keystone_trust_score"] == 95


# ---------------------------------------------------------------------------
# TestBoundaries — DEP.KEYSTONE does not replace source registry or ledger
# ---------------------------------------------------------------------------

class TestBoundaries:
    def test_dep_keystone_evidence_does_not_replace_source_registry_approval(self):
        # source_registry_cleared belongs to the dry-run envelope validation_summary,
        # not to this ingress record. The ingress schema must not claim that field.
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        props = schema.get("properties", {})
        assert "source_registry_cleared" not in props

    def test_dep_keystone_evidence_does_not_replace_clearance_ledger_approval(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        props = schema.get("properties", {})
        assert "ledger_cleared" not in props

    def test_schema_invariant_states_dep_keystone_is_standalone(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        inv = schema.get("x-invariants", {})
        assert "dep_keystone_is_standalone_product" in inv

    def test_schema_invariant_refs_are_refs_not_hashes(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        inv = schema.get("x-invariants", {})
        assert "dep_keystone_outputs_are_refs" in inv


# ---------------------------------------------------------------------------
# TestSummarizeIngress
# ---------------------------------------------------------------------------

class TestSummarizeIngress:
    def test_summarize_has_expected_fields(self):
        summary = summarize_ingress(_valid_ingress())
        assert summary["dep_keystone_ingress_id"] == "DKI-test-l1001-001"
        assert summary["govsec_admissibility_status"] == "approved"
        assert summary["dep_keystone_status"] == "VERIFIED"
        assert summary["dep_keystone_trust_score"] == 95
        assert summary["training_pipeline_allowed"] is True
        assert "tr04a_source_registry" in summary["allowed_next_gates"]

    def test_summarize_excludes_raw_artifact_hash_and_evidence_refs(self):
        summary = summarize_ingress(_valid_ingress())
        assert "artifact_sha256" not in summary
        assert "dep_keystone_evidence_sha256_ref" not in summary
        assert "dep_keystone_verification_report_ref" not in summary
        assert "dep_keystone_sbom_ref" not in summary
        assert "dep_keystone_trust_cert_ref" not in summary

    def test_summarize_includes_actor(self):
        summary = summarize_ingress(_valid_ingress())
        assert summary["ingress_actor_id"] == "TEST_INGRESS_OP_001"
        assert summary["ingress_actor_role"] == "ingress_reviewer"

    def test_summarize_includes_dep_keystone_risk_fields(self):
        summary = summarize_ingress(_valid_ingress())
        assert summary["dep_keystone_findings_count"] == 0
        assert summary["dep_keystone_haap_drs_escalation_required"] is False


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_schema_version_constant(self):
        assert SCHEMA_VERSION == "1.0.0"

    def test_ingress_version_constant(self):
        assert INGRESS_VERSION == "dep_keystone_ingress:1.0.0"

    def test_valid_govsec_admissibility_statuses(self):
        assert "approved" in VALID_GOVSEC_ADMISSIBILITY_STATUSES
        assert "blocked" in VALID_GOVSEC_ADMISSIBILITY_STATUSES
        assert "pending" in VALID_GOVSEC_ADMISSIBILITY_STATUSES
        assert "rejected" in VALID_GOVSEC_ADMISSIBILITY_STATUSES

    def test_valid_dep_keystone_statuses(self):
        assert "VERIFIED" in VALID_DEP_KEYSTONE_STATUSES
        assert "FAILED" in VALID_DEP_KEYSTONE_STATUSES
        assert len(VALID_DEP_KEYSTONE_STATUSES) == 2

    def test_valid_next_gates(self):
        assert "tr04a_source_registry" in VALID_NEXT_GATES
        assert "tr03_dataset_builder" in VALID_NEXT_GATES
        assert "tr05_model_registry" in VALID_NEXT_GATES

    def test_valid_govsec_layers(self):
        assert "layer_zero_reality_formation" in VALID_GOVSEC_LAYERS
        assert "dep_keystone_supply_chain" in VALID_GOVSEC_LAYERS


# ---------------------------------------------------------------------------
# TestModulePurity
# ---------------------------------------------------------------------------

class TestModulePurity:
    def test_no_external_provider_imports(self):
        src = (_TRAINING_DIR / "dep_keystone_ingress.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        blocked_prefixes = (
            "openai", "anthropic", "google.generativeai", "gemini",
            "groq", "xai", "huggingface_hub", "transformers",
            "boto3", "botocore", "requests", "httpx", "aiohttp",
            "urllib3", "torch", "tensorflow",
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in blocked_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"Blocked import found: {alias.name!r}"
                        )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for prefix in blocked_prefixes:
                    assert not mod.startswith(prefix), (
                        f"Blocked from-import found: {mod!r}"
                    )

    def test_stdlib_only_imports(self):
        src = (_TRAINING_DIR / "dep_keystone_ingress.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        allowed_top_level = {"json", "pathlib"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top in allowed_top_level, (
                        f"Unexpected import: {alias.name!r}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                top = (node.module or "").split(".")[0]
                assert top in allowed_top_level, (
                    f"Unexpected from-import: {node.module!r}"
                )
