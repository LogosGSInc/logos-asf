"""
TR-05 tests — Model Registry and Lineage.

Tests cover:
  - Schema files parse correctly.
  - Empty registry creation and validation.
  - Dry-run candidate registration from real TR-04B pipeline output.
  - All governance constants enforced (training_allowed=false, etc.).
  - All rejection conditions (bad envelope flags, bad manifest, bad ingress, weight paths).
  - Lineage record provenance preservation.
  - Deterministic artifact and lineage IDs.
  - Summarize and find_artifact / assert_not_promoted helpers.
  - Module purity (no external provider imports).

No real training. No model weights. No Store 1 writes. TR-06 not started.
"""
import ast
import hashlib
import json
from pathlib import Path

import pytest

from training.model_registry import (
    GENESIS_HASH,
    PROMOTION_STATUSES,
    REGISTRY_VERSION,
    SCHEMA_VERSION,
    ModelRegistryBlockedError,
    ModelRegistryValidationError,
    _compute_lineage_hash,
    _model_artifact_id,
    assert_not_promoted,
    build_lineage_record,
    create_empty_registry,
    find_artifact,
    load_registry,
    register_dry_run_candidate,
    save_registry,
    summarize_registry,
    validate_lineage_record,
    validate_registry,
)

_TRAINING_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _valid_envelope(**overrides) -> dict:
    """Factory for a minimal valid dry_run_envelope dict."""
    base = {
        "schema": "logos-asf:training:dry-run-envelope:v1.0.0",
        "dry_run_id": "DR-aabbccdd11223344",
        "created_at": "2026-06-27T00:00:00Z",
        "adapter_version": "dry_run_adapter:1.0.0",
        "source_dataset_manifest_id": "DS-test-001",
        "source_dataset_checksum": "sha256:" + "a" * 64,
        "training_allowed": False,
        "dry_run_only": True,
        "operator_promotion_required": True,
        "store1_write_allowed": False,
        "runtime_deployment_allowed": False,
        "model_promotion_allowed": False,
        "external_calls_allowed": False,
        "job_intent": {
            "description": "Test dry run",
            "mode": "simulation",
            "operator_id": "TEST_OP",
            "source_id": "L1-001",
            "requested_use": "sft_candidate",
            "source_registry_cleared": True,
            "ledger_cleared": True,
        },
        "dataset_summary": {
            "dataset_id": "DS-test-001",
            "dataset_status": "ready",
            "build_mode": "simulation",
            "accepted_record_count": 10,
            "train_count": 8,
            "validation_count": 1,
            "test_count": 1,
            "contamination_scan_status": "clean",
            "evaluation_set_exclusion_status": "clean",
        },
        "validation_summary": {
            "checksum_verified": True,
            "governance_flags_valid": True,
            "scan_report_clean": True,
            "split_counts_match": True,
            "operator_identity_valid": True,
            "manifest_version_supported": True,
            "source_registry_cleared": True,
            "ledger_cleared": True,
        },
        "estimated_compute": {
            "estimated_char_volume": 5000,
            "estimated_tokens_approx": 1200,
            "train_record_count": 8,
            "validation_record_count": 1,
        },
        "blocked_real_actions": ["training", "store1_write"],
        "next_required_gate": "TR-05 model registry",
    }
    base.update(overrides)
    return base


def _valid_manifest(**overrides) -> dict:
    """Factory for a minimal valid dataset manifest dict."""
    base = {
        "schema": "logos-asf:training:dataset-manifest:v1.0.0",
        "dataset_id": "DS-test-001",
        "version": "1.0.0",
        "build_mode": "simulation",
        "created_at": "2026-06-27T00:00:00Z",
        "operator_id": "TEST_OP",
        "source_ids": ["L1-001"],
        "content_hash": "sha256:" + "b" * 64,
        "accepted_record_count": 10,
        "training_allowed": False,
        "store1_write_allowed": False,
        "runtime_deployment_allowed": False,
        "operator_promotion_required": True,
        "contamination_scan_status": "clean",
        "evaluation_set_exclusion_status": "clean",
    }
    base.update(overrides)
    return base


def _valid_ingress_for_tr05(**overrides) -> dict:
    """Factory for a DEP.KEYSTONE ingress record that allows tr05_model_registry."""
    base = {
        "dep_keystone_ingress_id": "DKI-test-tr05-001",
        "schema_version": "1.0.0",
        "created_at": "2026-06-27T00:00:00Z",
        "source_id": "L1-001",
        "source_name": "Buildspec Volumes I, II, III",
        "source_type": "logos_owned_doctrine",
        "classification": "LOGOS_INTERNAL",
        "admissibility_status": "approved",
        "admissibility_decision": "accepted_for_clearance",
        "keystone_evidence_ref": "keystone-evidence://L1-001/tr05/v1",
        "keystone_verification_report_ref": "keystone-report://L1-001/tr05/v1",
        "keystone_sbom_ref": "keystone-sbom://L1-001/tr05/v1",
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
        "notes": "Test ingress for TR-05.",
    }
    base.update(overrides)
    return base


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_pipeline_files(tmp_path, envelope_overrides=None, manifest_overrides=None):
    """Create mock envelope + manifest files in tmp_path."""
    env_data = _valid_envelope(**(envelope_overrides or {}))
    mfst_data = _valid_manifest(**(manifest_overrides or {}))
    env_path = tmp_path / "dry_run_envelope.json"
    mfst_path = tmp_path / "manifest.json"
    _write_json(env_path, env_data)
    _write_json(mfst_path, mfst_data)
    return env_path, mfst_path


def _make_ingress_file(tmp_path, **overrides):
    """Create a mock DEP.KEYSTONE ingress file in tmp_path."""
    data = _valid_ingress_for_tr05(**overrides)
    p = tmp_path / "dep_keystone_ingress.json"
    _write_json(p, data)
    return p


# ---------------------------------------------------------------------------
# Integration helpers (real TR-04B pipeline output)
# ---------------------------------------------------------------------------

def _build_valid_ledger(tmp_path):
    """Build a valid clearance ledger for L1-001."""
    from training.clearance_ledger import (
        create_empty_ledger,
        append_decision,
        save_ledger,
    )
    ledger = create_empty_ledger(
        {"human_principal_id": "DWS-001", "display_name": "Test HP"},
        ledger_id="test-tr05-ledger",
        created_at="2026-06-27T09:00:00Z",
    )
    append_decision(ledger, {
        "source_id": "L1-001",
        "decision_type": "hp_approve",
        "from_status": "hp_pending",
        "to_status": "approved",
        "actor_id": "DWS-001",
        "actor_role": "human_principal",
        "decision_status": "recorded",
        "decision_reason": "HP approved L1-001.",
        "hp_decision_status": "approved",
        "timestamp": "2026-06-27T09:00:01Z",
    })
    path = tmp_path / "clearance_ledger.json"
    save_ledger(ledger, path)
    return path


def _candidate(cid, i=0):
    from training.review_queue import _decision_id, _decision_hash as rdh
    return {
        "candidate_id": cid,
        "schema_version": "1.0.0",
        "candidate_version": 1,
        "candidate_lane": "training_candidate",
        "source_store2_ids": ["tr01_20260627T000000Z"],
        "source_session_ids": ["20260627T000000Z"],
        "source_signature_ids": [f"SIG-{i:03d}"],
        "source_provenance": "sentinel_overwatch",
        "source_hashes": [{"signature_id": f"SIG-{i:03d}", "sha256": "a" * 64}],
        "task_type": "refusal_correct",
        "title": f"Test candidate {cid}",
        "summary": "A governed refusal example.",
        "problem_observed": "User attempts bypass.",
        "proposed_improvement": "Clear refusal.",
        "input": f"Question {i}: bypass?",
        "desired_output": f"Response {i}: I cannot assist with that.",
        "evidence": {
            "generation": "G4",
            "vector_id": "TAX2:MT-G4-01",
            "vector_name": "Test",
            "level": "C",
            "stage": "pressure_phase",
            "distortion_type": "emotional_exploitation",
            "sentinel_action": "block_and_escalate",
            "sentinel_reason": "DRS=60",
            "haap_requirement": "conditional",
            "memory_action": "quarantine",
            "bd1a_vectors": ["BD1A:F01"],
            "phase_q_vectors": ["PHASE_Q:Q01"],
            "turn_count": 6,
            "source_taxonomy": "TAX2",
            "audit_reason": "Level C test",
        },
        "confidence": 0.95,
        "safety_labels": {
            "is_harmful_content": False,
            "contains_adversarial_payload": False,
            "contains_credentials": False,
            "contains_evaluation_instrument_content": False,
            "sentinel_source_verified": True,
        },
        "privacy_labels": {
            "contains_pii": False,
            "contains_user_derived_data": False,
            "redaction_required": False,
        },
        "redaction_log": [],
        "duplicate_group": None,
        "operator_review_required": True,
        "promotion_status": "dataset_promotion_pending",
        "training_allowed": False,
        "store1_write_allowed": False,
        "runtime_deployment_allowed": False,
        "created_at": "2026-06-27T00:00:00+00:00",
        "builder_version": "candidate_builder:1.0.0",
    }


def _approval_decision(cid, operator_id="TEST_OP_001"):
    from training.review_queue import _decision_id, _decision_hash as rdh
    ts = "2026-06-27T12:00:00+00:00"
    did = _decision_id(cid, "approve", operator_id, ts)
    record = {
        "schema_version": "1.0.0",
        "decision_id": did,
        "candidate_id": cid,
        "candidate_version": 1,
        "operator_id": operator_id,
        "operator_role": "governance_lead",
        "action": "approve",
        "reason": "Approved for dataset.",
        "evidence_reviewed": True,
        "redactions": [],
        "rewritten_fields": [],
        "previous_lane": None,
        "new_lane": None,
        "source_candidate_ids": [],
        "resulting_status": "dataset_promotion_pending",
        "training_allowed": False,
        "store1_write_allowed": False,
        "runtime_deployment_allowed": False,
        "timestamp": ts,
        "queue_version": "review_queue:1.0.0",
        "decision_hash": "",
    }
    record["decision_hash"] = rdh(record)
    return record


def _build_full_pipeline(tmp_path, n=15):
    """Build TR-03 dataset + TR-04B dry run. Returns (envelope, dr_out_dir, ds_dir, ledger_path)."""
    from training.dataset_builder import build_dataset
    from training.dry_run_trainer import run_dry_run

    candidates = [
        _candidate(f"TC-20260627-{i:08d}", i=i)
        for i in range(n)
    ]
    decisions = [_approval_decision(c["candidate_id"]) for c in candidates]

    cands_path = tmp_path / "candidates.jsonl"
    decs_path  = tmp_path / "decisions.jsonl"
    ds_dir     = tmp_path / "dataset"

    cands_path.write_text(
        "\n".join(json.dumps(c) for c in candidates) + "\n", encoding="utf-8"
    )
    decs_path.write_text(
        "\n".join(json.dumps(d) for d in decisions) + "\n", encoding="utf-8"
    )

    build_dataset(cands_path, decs_path, ds_dir, run_id="tr05_test", mode="simulation")

    ledger_path = _build_valid_ledger(tmp_path)
    dr_out_dir  = tmp_path / "dry_run_out"

    run_dry_run(
        ds_dir,
        dr_out_dir,
        mode="simulation",
        operator_id="TEST_OP_001",
        source_id="L1-001",
        requested_use="sft_candidate",
        clearance_ledger_path=ledger_path,
    )

    return dr_out_dir, ds_dir, ledger_path


# ---------------------------------------------------------------------------
# TestSchemas
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_model_registry_schema_parses(self):
        path = _TRAINING_DIR / "MODEL_REGISTRY.schema.json"
        data = json.loads(path.read_text())
        assert data["$id"] == "logos-asf:training:model-registry:v1.0.0"

    def test_model_lineage_schema_parses(self):
        path = _TRAINING_DIR / "MODEL_LINEAGE_RECORD.schema.json"
        data = json.loads(path.read_text())
        assert data["$id"] == "logos-asf:training:model-lineage-record:v1.0.0"

    def test_model_registry_schema_has_governance_const_false(self):
        path = _TRAINING_DIR / "MODEL_REGISTRY.schema.json"
        data = json.loads(path.read_text())
        entry_props = data["$defs"]["RegistryEntry"]["properties"]
        assert entry_props["training_allowed"].get("const") is False
        assert entry_props["model_weights_present"].get("const") is False

    def test_model_lineage_schema_governance_flags_const(self):
        path = _TRAINING_DIR / "MODEL_LINEAGE_RECORD.schema.json"
        data = json.loads(path.read_text())
        gov_props = data["properties"]["governance_flags"]["properties"]
        assert gov_props["training_allowed"].get("const") is False
        assert gov_props["model_weights_present"].get("const") is False
        assert gov_props["operator_promotion_required"].get("const") is True


# ---------------------------------------------------------------------------
# TestCreateEmptyRegistry
# ---------------------------------------------------------------------------

class TestCreateEmptyRegistry:
    def test_creates_empty_registry(self):
        reg = create_empty_registry()
        assert reg["registry_id"] == "LOGOS-MODEL-REGISTRY-001"
        assert reg["entries"] == []
        assert reg["version"] == SCHEMA_VERSION

    def test_empty_registry_validates(self):
        reg = create_empty_registry()
        result = validate_registry(reg)
        assert result["valid"] is True
        assert result["entry_count"] == 0

    def test_save_and_load_roundtrip(self, tmp_path):
        reg = create_empty_registry()
        p = tmp_path / "registry.json"
        save_registry(reg, p)
        loaded = load_registry(p)
        assert loaded["registry_id"] == reg["registry_id"]
        assert loaded["entries"] == []

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(ModelRegistryValidationError, match="not found"):
            load_registry(tmp_path / "no_such.json")

    def test_governance_flags_in_empty_registry(self):
        reg = create_empty_registry()
        gov = reg["governance"]
        assert gov["training_allowed"] is False
        assert gov["model_weights_present"] is False
        assert gov["operator_promotion_required"] is True


# ---------------------------------------------------------------------------
# TestIntegration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_registers_from_real_tr04b_output(self, tmp_path):
        dr_out, ds_dir, _ = _build_full_pipeline(tmp_path)
        reg = create_empty_registry()
        register_dry_run_candidate(
            reg,
            dry_run_envelope_path=dr_out / "dry_run_envelope.json",
            dataset_manifest_path=ds_dir / "manifest.json",
        )
        assert len(reg["entries"]) == 1

    def test_integration_with_dep_keystone_ingress(self, tmp_path):
        dr_out, ds_dir, _ = _build_full_pipeline(tmp_path)
        ingress_path = _make_ingress_file(tmp_path)
        reg = create_empty_registry()
        register_dry_run_candidate(
            reg,
            dry_run_envelope_path=dr_out / "dry_run_envelope.json",
            dataset_manifest_path=ds_dir / "manifest.json",
            dep_keystone_ingress_path=ingress_path,
        )
        entry = reg["entries"][0]
        assert entry["dep_keystone_ingress_ref"] == "DKI-test-tr05-001"

    def test_integration_artifact_id_is_deterministic(self, tmp_path):
        dr_out, ds_dir, _ = _build_full_pipeline(tmp_path)
        r1 = create_empty_registry()
        register_dry_run_candidate(
            r1,
            dry_run_envelope_path=dr_out / "dry_run_envelope.json",
            dataset_manifest_path=ds_dir / "manifest.json",
        )
        r2 = create_empty_registry()
        register_dry_run_candidate(
            r2,
            dry_run_envelope_path=dr_out / "dry_run_envelope.json",
            dataset_manifest_path=ds_dir / "manifest.json",
        )
        assert r1["entries"][0]["model_artifact_id"] == r2["entries"][0]["model_artifact_id"]

    def test_integration_ledger_entry_id_in_lineage(self, tmp_path):
        dr_out, ds_dir, _ = _build_full_pipeline(tmp_path)
        reg = create_empty_registry()
        register_dry_run_candidate(
            reg,
            dry_run_envelope_path=dr_out / "dry_run_envelope.json",
            dataset_manifest_path=ds_dir / "manifest.json",
        )
        prov = reg["entries"][0]["provenance"]
        assert prov["ledger_entry_id"] is not None
        assert prov["ledger_entry_id"].startswith("LE-")


# ---------------------------------------------------------------------------
# TestGovernanceFlags
# ---------------------------------------------------------------------------

class TestGovernanceFlags:
    def _register(self, tmp_path, **env_overrides):
        env_path, mfst_path = _make_pipeline_files(tmp_path, envelope_overrides=env_overrides)
        reg = create_empty_registry()
        register_dry_run_candidate(reg, env_path, mfst_path)
        return reg

    def test_training_allowed_is_false(self, tmp_path):
        reg = self._register(tmp_path)
        assert reg["entries"][0]["training_allowed"] is False

    def test_model_weights_present_is_false(self, tmp_path):
        reg = self._register(tmp_path)
        assert reg["entries"][0]["model_weights_present"] is False

    def test_runtime_deployment_allowed_is_false(self, tmp_path):
        reg = self._register(tmp_path)
        assert reg["entries"][0]["runtime_deployment_allowed"] is False

    def test_store1_write_allowed_is_false(self, tmp_path):
        reg = self._register(tmp_path)
        assert reg["entries"][0]["store1_write_allowed"] is False

    def test_external_calls_allowed_is_false(self, tmp_path):
        reg = self._register(tmp_path)
        assert reg["entries"][0]["external_calls_allowed"] is False

    def test_operator_promotion_required_is_true(self, tmp_path):
        reg = self._register(tmp_path)
        assert reg["entries"][0]["operator_promotion_required"] is True

    def test_promotion_status_is_not_promoted(self, tmp_path):
        reg = self._register(tmp_path)
        assert reg["entries"][0]["promotion_status"] == "not_promoted"

    def test_lineage_governance_flags(self, tmp_path):
        reg = self._register(tmp_path)
        gov = reg["entries"][0]["lineage"]["governance_flags"]
        assert gov["training_allowed"] is False
        assert gov["model_weights_present"] is False
        assert gov["operator_promotion_required"] is True


# ---------------------------------------------------------------------------
# TestRegistrationRejections
# ---------------------------------------------------------------------------

class TestRegistrationRejections:
    def _make_env(self, tmp_path, **env_overrides):
        env_path, mfst_path = _make_pipeline_files(tmp_path, envelope_overrides=env_overrides)
        return env_path, mfst_path

    def test_rejects_training_allowed_true(self, tmp_path):
        env_path, mfst_path = self._make_env(tmp_path)
        data = json.loads(env_path.read_text())
        data["training_allowed"] = True
        env_path.write_text(json.dumps(data))
        with pytest.raises(ModelRegistryBlockedError, match="training_allowed"):
            register_dry_run_candidate(create_empty_registry(), env_path, mfst_path)

    def test_rejects_runtime_deployment_true(self, tmp_path):
        env_path, mfst_path = self._make_env(tmp_path)
        data = json.loads(env_path.read_text())
        data["runtime_deployment_allowed"] = True
        env_path.write_text(json.dumps(data))
        with pytest.raises(ModelRegistryBlockedError, match="runtime_deployment_allowed"):
            register_dry_run_candidate(create_empty_registry(), env_path, mfst_path)

    def test_rejects_store1_write_true(self, tmp_path):
        env_path, mfst_path = self._make_env(tmp_path)
        data = json.loads(env_path.read_text())
        data["store1_write_allowed"] = True
        env_path.write_text(json.dumps(data))
        with pytest.raises(ModelRegistryBlockedError, match="store1_write_allowed"):
            register_dry_run_candidate(create_empty_registry(), env_path, mfst_path)

    def test_rejects_external_calls_true(self, tmp_path):
        env_path, mfst_path = self._make_env(tmp_path)
        data = json.loads(env_path.read_text())
        data["external_calls_allowed"] = True
        env_path.write_text(json.dumps(data))
        with pytest.raises(ModelRegistryBlockedError, match="external_calls_allowed"):
            register_dry_run_candidate(create_empty_registry(), env_path, mfst_path)

    def test_rejects_source_registry_not_cleared(self, tmp_path):
        env_path, mfst_path = self._make_env(tmp_path)
        data = json.loads(env_path.read_text())
        data["validation_summary"]["source_registry_cleared"] = False
        env_path.write_text(json.dumps(data))
        with pytest.raises(ModelRegistryBlockedError, match="source_registry_cleared"):
            register_dry_run_candidate(create_empty_registry(), env_path, mfst_path)

    def test_rejects_ledger_not_cleared(self, tmp_path):
        env_path, mfst_path = self._make_env(tmp_path)
        data = json.loads(env_path.read_text())
        data["validation_summary"]["ledger_cleared"] = False
        env_path.write_text(json.dumps(data))
        with pytest.raises(ModelRegistryBlockedError, match="ledger_cleared"):
            register_dry_run_candidate(create_empty_registry(), env_path, mfst_path)

    def test_rejects_manifest_training_allowed_true(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        data = json.loads(mfst_path.read_text())
        data["training_allowed"] = True
        mfst_path.write_text(json.dumps(data))
        with pytest.raises(ModelRegistryBlockedError, match="training_allowed"):
            register_dry_run_candidate(create_empty_registry(), env_path, mfst_path)

    def test_rejects_model_weights_path(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        with pytest.raises(ModelRegistryBlockedError, match="model_weights_path"):
            register_dry_run_candidate(
                create_empty_registry(), env_path, mfst_path,
                model_weights_path="/fake/weights.bin"
            )

    def test_rejects_adapter_checkpoint_path(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        with pytest.raises(ModelRegistryBlockedError, match="adapter_checkpoint_path"):
            register_dry_run_candidate(
                create_empty_registry(), env_path, mfst_path,
                adapter_checkpoint_path="/fake/adapter.pt"
            )

    def test_rejects_invalid_dep_keystone_ingress(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        ingress_path = tmp_path / "ingress.json"
        bad_ingress = _valid_ingress_for_tr05(admissibility_status="blocked")
        _write_json(ingress_path, bad_ingress)
        with pytest.raises(ModelRegistryBlockedError, match="DEP.KEYSTONE"):
            register_dry_run_candidate(
                create_empty_registry(), env_path, mfst_path,
                dep_keystone_ingress_path=ingress_path,
            )

    def test_rejects_ingress_not_allowing_tr05(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        ingress_path = tmp_path / "ingress.json"
        bad_ingress = _valid_ingress_for_tr05(
            allowed_next_gates=["tr04a_source_registry"]  # missing tr05_model_registry
        )
        _write_json(ingress_path, bad_ingress)
        with pytest.raises(ModelRegistryBlockedError, match="DEP.KEYSTONE"):
            register_dry_run_candidate(
                create_empty_registry(), env_path, mfst_path,
                dep_keystone_ingress_path=ingress_path,
            )


# ---------------------------------------------------------------------------
# TestLineagePreservation
# ---------------------------------------------------------------------------

class TestLineagePreservation:
    def _register_with_ingress(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        ingress_path = _make_ingress_file(tmp_path)
        reg = create_empty_registry()
        register_dry_run_candidate(
            reg, env_path, mfst_path,
            dep_keystone_ingress_path=ingress_path,
        )
        return reg["entries"][0]

    def _register_without_ingress(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        reg = create_empty_registry()
        register_dry_run_candidate(reg, env_path, mfst_path)
        return reg["entries"][0]

    def test_lineage_preserves_dep_keystone_ingress_ref(self, tmp_path):
        entry = self._register_with_ingress(tmp_path)
        assert "DKI-test-tr05-001" in entry["lineage"]["dep_keystone_ingress_refs"]

    def test_lineage_preserves_keystone_evidence_ref(self, tmp_path):
        entry = self._register_with_ingress(tmp_path)
        assert "keystone-evidence://L1-001/tr05/v1" in entry["lineage"]["keystone_evidence_refs"]

    def test_lineage_preserves_keystone_report_ref(self, tmp_path):
        entry = self._register_with_ingress(tmp_path)
        assert "keystone-report://L1-001/tr05/v1" in entry["lineage"]["keystone_verification_report_refs"]

    def test_lineage_preserves_dataset_id(self, tmp_path):
        entry = self._register_without_ingress(tmp_path)
        assert any("DS-test-001" in r for r in entry["lineage"]["dataset_manifest_refs"])

    def test_lineage_preserves_dry_run_id(self, tmp_path):
        entry = self._register_without_ingress(tmp_path)
        assert any("DR-aabbccdd11223344" in r for r in entry["lineage"]["dry_run_envelope_refs"])

    def test_lineage_preserves_source_id(self, tmp_path):
        entry = self._register_without_ingress(tmp_path)
        assert entry["provenance"]["source_id"] == "L1-001"

    def test_lineage_preserves_requested_use(self, tmp_path):
        entry = self._register_without_ingress(tmp_path)
        assert entry["provenance"]["requested_use"] == "sft_candidate"

    def test_lineage_includes_source_registry_ref(self, tmp_path):
        entry = self._register_without_ingress(tmp_path)
        assert len(entry["lineage"]["source_registry_refs"]) > 0
        assert "L1-001" in entry["lineage"]["source_registry_refs"][0]

    def test_ingress_ref_on_entry(self, tmp_path):
        entry = self._register_with_ingress(tmp_path)
        assert entry["dep_keystone_ingress_ref"] == "DKI-test-tr05-001"

    def test_govsec_layer_preserved_in_provenance(self, tmp_path):
        entry = self._register_with_ingress(tmp_path)
        assert entry["provenance"]["govsec_layer"] == "layer_zero_reality_formation"


# ---------------------------------------------------------------------------
# TestDeterminism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_artifact_id_is_deterministic(self):
        id1 = _model_artifact_id("DR-abc", "DS-001", "L1-001")
        id2 = _model_artifact_id("DR-abc", "DS-001", "L1-001")
        assert id1 == id2
        assert id1.startswith("MA-")

    def test_artifact_id_differs_on_different_input(self):
        id1 = _model_artifact_id("DR-abc", "DS-001", "L1-001")
        id2 = _model_artifact_id("DR-abc", "DS-001", "L1-003")
        assert id1 != id2

    def test_lineage_hash_changes_when_refs_change(self):
        r1 = build_lineage_record(
            "MA-001", "dry_run_adapter_candidate",
            dep_keystone_ingress_refs=["DKI-001"],
        )
        r2 = build_lineage_record(
            "MA-001", "dry_run_adapter_candidate",
            dep_keystone_ingress_refs=["DKI-002"],
        )
        assert r1["lineage_hash"] != r2["lineage_hash"]

    def test_lineage_hash_stable_for_same_input(self):
        r1 = build_lineage_record(
            "MA-001", "dry_run_adapter_candidate",
            dataset_manifest_refs=["dataset:DS-001"],
        )
        r2 = build_lineage_record(
            "MA-001", "dry_run_adapter_candidate",
            dataset_manifest_refs=["dataset:DS-001"],
        )
        assert r1["lineage_hash"] == r2["lineage_hash"]

    def test_lineage_record_id_stable_for_same_input(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        r1 = create_empty_registry()
        r2 = create_empty_registry()
        register_dry_run_candidate(r1, env_path, mfst_path)
        register_dry_run_candidate(r2, env_path, mfst_path)
        assert (
            r1["entries"][0]["lineage_record_id"]
            == r2["entries"][0]["lineage_record_id"]
        )


# ---------------------------------------------------------------------------
# TestSummarizeAndFind
# ---------------------------------------------------------------------------

class TestSummarizeAndFind:
    def test_summary_has_expected_keys(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        reg = create_empty_registry()
        register_dry_run_candidate(reg, env_path, mfst_path)
        summary = summarize_registry(reg)
        assert "total_entries" in summary
        assert "by_artifact_status" in summary
        assert "by_promotion_status" in summary

    def test_summary_counts_by_status(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        reg = create_empty_registry()
        register_dry_run_candidate(reg, env_path, mfst_path)
        summary = summarize_registry(reg)
        assert summary["total_entries"] == 1
        assert summary["by_artifact_status"].get("dry_run_only", 0) == 1
        assert summary["by_promotion_status"].get("not_promoted", 0) == 1

    def test_find_artifact_returns_entry(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        reg = create_empty_registry()
        register_dry_run_candidate(reg, env_path, mfst_path)
        artifact_id = reg["entries"][0]["model_artifact_id"]
        found = find_artifact(reg, artifact_id)
        assert found is not None
        assert found["model_artifact_id"] == artifact_id

    def test_find_artifact_returns_none_for_unknown(self):
        reg = create_empty_registry()
        assert find_artifact(reg, "MA-nonexistent") is None

    def test_assert_not_promoted_passes_for_not_promoted(self, tmp_path):
        env_path, mfst_path = _make_pipeline_files(tmp_path)
        reg = create_empty_registry()
        register_dry_run_candidate(reg, env_path, mfst_path)
        artifact_id = reg["entries"][0]["model_artifact_id"]
        assert_not_promoted(reg, artifact_id)

    def test_assert_not_promoted_fails_for_missing_artifact(self):
        reg = create_empty_registry()
        with pytest.raises(ModelRegistryValidationError, match="not found"):
            assert_not_promoted(reg, "MA-nonexistent")


# ---------------------------------------------------------------------------
# TestLineageRecordValidation
# ---------------------------------------------------------------------------

class TestLineageRecordValidation:
    def test_valid_lineage_record_validates(self):
        rec = build_lineage_record(
            "MA-test-001", "dry_run_adapter_candidate",
            dataset_manifest_refs=["dataset:DS-001"],
            dry_run_envelope_refs=["dry_run:DR-abc"],
        )
        result = validate_lineage_record(rec)
        assert result["valid"] is True

    def test_lineage_governance_flags_correct(self):
        rec = build_lineage_record("MA-001", "dry_run_adapter_candidate")
        assert rec["governance_flags"]["training_allowed"] is False
        assert rec["governance_flags"]["model_weights_present"] is False
        assert rec["governance_flags"]["operator_promotion_required"] is True

    def test_lineage_previous_hash_genesis(self):
        rec = build_lineage_record("MA-001", "dry_run_adapter_candidate")
        assert rec["previous_lineage_hash"] == GENESIS_HASH

    def test_lineage_evaluation_refs_empty(self):
        rec = build_lineage_record("MA-001", "dry_run_adapter_candidate")
        assert rec["evaluation_refs"] == []


# ---------------------------------------------------------------------------
# TestModulePurity
# ---------------------------------------------------------------------------

class TestModulePurity:
    def test_no_external_provider_imports(self):
        src = (_TRAINING_DIR / "model_registry.py").read_text(encoding="utf-8")
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
                    top = alias.name.split(".")[0]
                    for prefix in blocked_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"Blocked import: {alias.name!r}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mod = node.module or ""
                for prefix in blocked_prefixes:
                    assert not mod.startswith(prefix), (
                        f"Blocked from-import: {mod!r}"
                    )

    def test_no_model_training_in_source(self):
        src = (_TRAINING_DIR / "model_registry.py").read_text(encoding="utf-8")
        blocked_terms = (
            "torch.nn", "model.train()", "optimizer.step",
            "loss.backward", "model.load_weights",
        )
        for term in blocked_terms:
            assert term not in src, f"Blocked term in source: {term!r}"
