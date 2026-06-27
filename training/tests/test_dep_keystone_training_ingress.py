"""
TR-04D tests — DEP.KEYSTONE / GovSec V2 Training Ingress Gate.

Recon result (2026-06-27): No pre-existing DEP.KEYSTONE / GovSec training-ingress
gate was found in the LOGOS ASF codebase. All matches for DEP/KEYSTONE/GovSec/
Layer Zero/admissibility/ingress/sbom in training/, abigail/, governance-spine/,
agents/, and docs/ were either department IDs (DEPT-*) or env-var references
(GOVMEM_DEPARTMENT_ID). No callable training-ingress gate existed.
dep_keystone_ingress.py implements that gate as a new narrow bridge (TR-04D).
"""
import ast
import json
from pathlib import Path

import pytest

from training.dep_keystone_ingress import (
    INGRESS_VERSION,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    VALID_ADMISSIBILITY_DECISIONS,
    VALID_ADMISSIBILITY_STATUSES,
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
    """Factory for a minimal valid approved DEP.KEYSTONE ingress record."""
    base = {
        "dep_keystone_ingress_id": "DKI-test-l1001-001",
        "schema_version": "1.0.0",
        "created_at": "2026-06-27T00:00:00Z",
        "source_id": "L1-001",
        "source_name": "Buildspec Volumes I, II, III",
        "source_type": "logos_owned_doctrine",
        "classification": "LOGOS_INTERNAL",
        "admissibility_status": "approved",
        "admissibility_decision": "accepted_for_clearance",
        "keystone_evidence_ref": "keystone-evidence://L1-001/v1",
        "keystone_verification_report_ref": "keystone-report://L1-001/v1",
        "keystone_sbom_ref": "keystone-sbom://L1-001/v1",
        "evidence_sha256": "a" * 64,
        "artifact_sha256": "b" * 64,
        "govsec_layer": "layer_zero_reality_formation",
        "reality_formation_input": True,
        "ingress_actor_id": "TEST_INGRESS_OP_001",
        "ingress_actor_role": "ingress_reviewer",
        "operator_review_required": True,
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

    def test_schema_has_admissibility_status_enum(self):
        schema_path = _TRAINING_DIR / "DEP_KEYSTONE_TRAINING_INGRESS.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        enum_vals = set(schema["properties"]["admissibility_status"]["enum"])
        assert enum_vals == VALID_ADMISSIBILITY_STATUSES

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
        assert result["admissibility_status"] == "approved"

    def test_missing_required_field_raises(self):
        rec = _valid_ingress()
        del rec["evidence_sha256"]
        with pytest.raises(KeystoneIngressValidationError, match="evidence_sha256"):
            validate_ingress_record(rec)

    def test_multiple_missing_fields_reported(self):
        rec = _valid_ingress()
        del rec["evidence_sha256"]
        del rec["artifact_sha256"]
        with pytest.raises(KeystoneIngressValidationError, match="2 error"):
            validate_ingress_record(rec)

    def test_invalid_admissibility_status_raises(self):
        rec = _valid_ingress(admissibility_status="unknown_status")
        with pytest.raises(KeystoneIngressValidationError, match="admissibility_status"):
            validate_ingress_record(rec)

    def test_invalid_admissibility_decision_raises(self):
        rec = _valid_ingress(admissibility_decision="maybe")
        with pytest.raises(KeystoneIngressValidationError, match="admissibility_decision"):
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
        assert result["admissibility_status"] == "approved"
        assert result["admissibility_decision"] == "accepted_for_clearance"

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

    def test_missing_evidence_sha256_blocks(self):
        rec = _valid_ingress()
        del rec["evidence_sha256"]
        rec["evidence_sha256"] = ""
        with pytest.raises(KeystoneIngressNotAllowedError, match="evidence_sha256"):
            assert_training_ingress_allowed(rec)

    def test_empty_evidence_sha256_blocks(self):
        rec = _valid_ingress(evidence_sha256="")
        with pytest.raises(KeystoneIngressNotAllowedError, match="evidence_sha256"):
            assert_training_ingress_allowed(rec)

    def test_missing_artifact_sha256_blocks(self):
        rec = _valid_ingress(artifact_sha256="")
        with pytest.raises(KeystoneIngressNotAllowedError, match="artifact_sha256"):
            assert_training_ingress_allowed(rec)

    def test_missing_keystone_evidence_ref_blocks(self):
        rec = _valid_ingress(keystone_evidence_ref="")
        with pytest.raises(KeystoneIngressNotAllowedError, match="keystone_evidence_ref"):
            assert_training_ingress_allowed(rec)

    def test_missing_keystone_verification_report_ref_blocks(self):
        rec = _valid_ingress(keystone_verification_report_ref="")
        with pytest.raises(KeystoneIngressNotAllowedError, match="keystone_verification_report_ref"):
            assert_training_ingress_allowed(rec)

    def test_pending_status_blocks(self):
        rec = _valid_ingress(admissibility_status="pending")
        with pytest.raises(KeystoneIngressNotAllowedError, match="pending"):
            assert_training_ingress_allowed(rec)

    def test_draft_status_blocks(self):
        rec = _valid_ingress(admissibility_status="draft")
        with pytest.raises(KeystoneIngressNotAllowedError, match="draft"):
            assert_training_ingress_allowed(rec)

    def test_blocked_status_raises_blocked_error(self):
        rec = _valid_ingress(admissibility_status="blocked")
        with pytest.raises(KeystoneIngressBlockedError, match="blocked"):
            assert_training_ingress_allowed(rec)

    def test_rejected_status_raises_blocked_error(self):
        rec = _valid_ingress(admissibility_status="rejected")
        with pytest.raises(KeystoneIngressBlockedError, match="rejected"):
            assert_training_ingress_allowed(rec)

    def test_archived_status_raises_blocked_error(self):
        rec = _valid_ingress(admissibility_status="archived")
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

    def test_wrong_admissibility_decision_blocks(self):
        rec = _valid_ingress(admissibility_decision="requires_more_evidence")
        with pytest.raises(KeystoneIngressNotAllowedError, match="admissibility_decision"):
            assert_training_ingress_allowed(rec)

    def test_clearance_result_includes_govsec_layer(self):
        result = assert_training_ingress_allowed(_valid_ingress())
        assert result["govsec_layer"] == "layer_zero_reality_formation"
        assert result["reality_formation_input"] is True


# ---------------------------------------------------------------------------
# TestSummarizeIngress
# ---------------------------------------------------------------------------

class TestSummarizeIngress:
    def test_summarize_has_expected_fields(self):
        summary = summarize_ingress(_valid_ingress())
        assert summary["dep_keystone_ingress_id"] == "DKI-test-l1001-001"
        assert summary["admissibility_status"] == "approved"
        assert summary["training_pipeline_allowed"] is True
        assert "tr04a_source_registry" in summary["allowed_next_gates"]

    def test_summarize_excludes_raw_evidence_hashes(self):
        summary = summarize_ingress(_valid_ingress())
        assert "evidence_sha256" not in summary
        assert "artifact_sha256" not in summary
        assert "keystone_sbom_ref" not in summary

    def test_summarize_includes_actor(self):
        summary = summarize_ingress(_valid_ingress())
        assert summary["ingress_actor_id"] == "TEST_INGRESS_OP_001"
        assert summary["ingress_actor_role"] == "ingress_reviewer"


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_schema_version_constant(self):
        assert SCHEMA_VERSION == "1.0.0"

    def test_ingress_version_constant(self):
        assert INGRESS_VERSION == "dep_keystone_ingress:1.0.0"

    def test_valid_admissibility_statuses(self):
        assert "approved" in VALID_ADMISSIBILITY_STATUSES
        assert "blocked" in VALID_ADMISSIBILITY_STATUSES
        assert "pending" in VALID_ADMISSIBILITY_STATUSES
        assert "rejected" in VALID_ADMISSIBILITY_STATUSES

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
