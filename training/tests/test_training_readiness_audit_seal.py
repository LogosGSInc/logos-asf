"""
TR-06Z: tests for TRAINING_READINESS_AUDIT_SEAL.schema.json and
training_readiness_audit_seal.py.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training.training_readiness_audit_seal import (
    COVERED_PHASES,
    REQUIRED_SEAL_FIELDS,
    AuditSealError,
    AuditSealValidationError,
    assert_tr07_not_authorized,
    build_phase_status_summary,
    build_training_readiness_audit_seal,
    collect_training_file_inventory,
    compute_file_sha256,
    compute_seal_hash,
    load_training_readiness_audit_seal,
    save_training_readiness_audit_seal,
    scan_for_forbidden_model_artifacts,
    scan_training_for_forbidden_runtime_imports,
    summarize_training_readiness_audit_seal,
    validate_training_readiness_audit_seal,
)

SEAL_SCHEMA_PATH = (
    Path(__file__).parent.parent / "TRAINING_READINESS_AUDIT_SEAL.schema.json"
)
REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Fixture factory: build a valid seal using real repo state.
# Tests that require clean git state mock git data directly.
# ---------------------------------------------------------------------------

def _make_fixture_seal(**overrides) -> dict:
    """Build a minimal valid seal without real git dependency."""
    base = {
        "audit_seal_id":            "AS-0000000000000000",
        "schema_version":           "1.0.0",
        "created_at":               "2026-06-28T00:00:00Z",
        "branch":                   "sprint/full-doctrine-mode",
        "head_commit":              "1bbbb1b80e13511a1d089a431954ae32c16b408b",
        "expected_head_commit":     "1bbbb1b",
        "working_tree_clean":       True,
        "test_suite_status":        "passed",
        "test_count":               1164,
        "covered_phases":           list(COVERED_PHASES),
        "phase_status_summary":     build_phase_status_summary(),
        "training_file_inventory":  [],
        "schema_inventory":         [],
        "module_inventory":         [],
        "documentation_inventory":  [],
        "test_inventory":           [],
        "checksum_manifest":        {},
        "forbidden_artifact_scan":  {
            "scanned_extensions": [".bin"],
            "found_artifacts":    [],
            "clean":              True,
        },
        "forbidden_action_attestation": {
            "no_real_training":        True,
            "no_model_weights":        True,
            "no_real_model_inference": True,
            "no_provider_calls":       True,
            "no_store1_writes":        True,
            "no_runtime_deployment":   True,
            "no_model_promotion":      True,
        },
        "promotion_blocking_attestation": {
            "promotion_blocked":          True,
            "promotion_decision_emitted": False,
        },
        "dep_keystone_govsec_attestation": {
            "dep_keystone_boundary_respected": True,
            "govsec_doctrine_applied":         True,
            "no_dep_keystone_code_vendored":   True,
        },
        "evaluation_readiness_attestation": {
            "tr06a_metadata_gates_present":      True,
            "tr06b_fixture_corpus_present":      True,
            "tr06c_live_eval_interface_present": True,
            "tr06d_stub_adapter_present":        True,
            "tr06e_dossier_aggregator_present":  True,
            "live_inference_disabled":           True,
            "stub_execution_only":               True,
        },
        "readiness_state":          "sealed_metadata_only_training_readiness",
        "readiness_rationale":      (
            "All checks passed. sealed_metadata_only_training_readiness "
            "is NOT promotion eligibility. TR-07 is not authorized."
        ),
        "tr07_authorization_status": "not_authorized",
        "seal_hash":                "",
        "previous_seal_hash":       None,
        "notes":                    "Test fixture seal.",
    }
    base.update(overrides)
    # Recompute hash unless explicitly overriding it
    if "seal_hash" not in overrides or overrides.get("seal_hash") == "":
        base["seal_hash"] = compute_seal_hash(base)
    return base


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestAuditSealSchema:
    def test_schema_parses(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_schema_required_fields_match_constant(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        assert set(schema["required"]) == REQUIRED_SEAL_FIELDS

    def test_schema_working_tree_clean_const_true(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        assert schema["properties"]["working_tree_clean"]["const"] is True

    def test_schema_no_real_training_const_true(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        faa = schema["properties"]["forbidden_action_attestation"]["properties"]
        assert faa["no_real_training"]["const"] is True

    def test_schema_no_model_weights_const_true(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        faa = schema["properties"]["forbidden_action_attestation"]["properties"]
        assert faa["no_model_weights"]["const"] is True

    def test_schema_no_real_inference_const_true(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        faa = schema["properties"]["forbidden_action_attestation"]["properties"]
        assert faa["no_real_model_inference"]["const"] is True

    def test_schema_no_provider_calls_const_true(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        faa = schema["properties"]["forbidden_action_attestation"]["properties"]
        assert faa["no_provider_calls"]["const"] is True

    def test_schema_no_store1_writes_const_true(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        faa = schema["properties"]["forbidden_action_attestation"]["properties"]
        assert faa["no_store1_writes"]["const"] is True

    def test_schema_no_deployment_const_true(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        faa = schema["properties"]["forbidden_action_attestation"]["properties"]
        assert faa["no_runtime_deployment"]["const"] is True

    def test_schema_no_model_promotion_const_true(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        faa = schema["properties"]["forbidden_action_attestation"]["properties"]
        assert faa["no_model_promotion"]["const"] is True

    def test_schema_promotion_blocked_const_true(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        pba = schema["properties"]["promotion_blocking_attestation"]["properties"]
        assert pba["promotion_blocked"]["const"] is True

    def test_schema_promotion_decision_emitted_const_false(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        pba = schema["properties"]["promotion_blocking_attestation"]["properties"]
        assert pba["promotion_decision_emitted"]["const"] is False

    def test_schema_readiness_state_enum(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        vals = set(schema["properties"]["readiness_state"]["enum"])
        assert vals == {
            "sealed_metadata_only_training_readiness", "blocked", "needs_more_evidence"
        }

    def test_schema_tr07_authorization_enum(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        vals = set(schema["properties"]["tr07_authorization_status"]["enum"])
        assert "not_authorized" in vals

    def test_schema_invariants_present(self):
        schema = json.loads(SEAL_SCHEMA_PATH.read_text())
        inv = schema.get("x-invariants", {})
        assert "working_tree_must_be_clean" in inv
        assert "no_real_training_const" in inv
        assert "promotion_blocked_const" in inv
        assert "tr07_not_authorized_const" in inv
        assert "sealed_readiness_is_not_promotion" in inv
        assert "no_git_tag" in inv
        assert "no_push" in inv


# ---------------------------------------------------------------------------
# compute_file_sha256
# ---------------------------------------------------------------------------

class TestComputeFileSha256:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        h1 = compute_file_sha256(f)
        h2 = compute_file_sha256(f)
        assert h1 == h2

    def test_changes_with_content(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content A", encoding="utf-8")
        h1 = compute_file_sha256(f)
        f.write_text("content B", encoding="utf-8")
        h2 = compute_file_sha256(f)
        assert h1 != h2

    def test_returns_64_char_hex(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("x", encoding="utf-8")
        h = compute_file_sha256(f)
        assert len(h) == 64
        int(h, 16)  # valid hex


# ---------------------------------------------------------------------------
# collect_training_file_inventory
# ---------------------------------------------------------------------------

class TestCollectTrainingFileInventory:
    def test_finds_schema_files(self):
        inv = collect_training_file_inventory(REPO_ROOT)
        schemas = [e["path"] for e in inv["schema_inventory"]]
        assert any("EVALUATION_DOSSIER.schema.json" in p for p in schemas)
        assert any("EVALUATION_REPORT.schema.json" in p for p in schemas)

    def test_finds_module_files(self):
        inv = collect_training_file_inventory(REPO_ROOT)
        modules = [e["path"] for e in inv["module_inventory"]]
        assert any("evaluation_dossier.py" in p for p in modules)
        assert any("local_eval_adapter_harness.py" in p for p in modules)

    def test_finds_doc_files(self):
        inv = collect_training_file_inventory(REPO_ROOT)
        docs = [e["path"] for e in inv["documentation_inventory"]]
        assert any("TR_06E" in p for p in docs)
        assert any("TR_06D" in p for p in docs)

    def test_finds_test_files(self):
        inv = collect_training_file_inventory(REPO_ROOT)
        tests = [e["path"] for e in inv["test_inventory"]]
        assert any("test_evaluation_dossier.py" in p for p in tests)
        assert any("test_evaluation_harness.py" in p for p in tests)

    def test_tr03_through_tr06e_covered(self):
        inv = collect_training_file_inventory(REPO_ROOT)
        all_paths = " ".join(e["path"] for e in inv["training_file_inventory"])
        for fragment in ["dataset_builder", "dry_run_trainer", "model_registry",
                         "evaluation_harness", "evaluation_dossier", "live_eval_interface"]:
            assert fragment in all_paths, f"Expected {fragment!r} in inventory"

    def test_checksum_manifest_nonempty(self):
        inv = collect_training_file_inventory(REPO_ROOT)
        assert len(inv["checksum_manifest"]) > 0

    def test_each_file_has_64char_hash(self):
        inv = collect_training_file_inventory(REPO_ROOT)
        for entry in inv["training_file_inventory"]:
            assert len(entry["sha256"]) == 64, f"Bad hash for {entry['path']}"


# ---------------------------------------------------------------------------
# scan_for_forbidden_model_artifacts
# ---------------------------------------------------------------------------

class TestScanForForbiddenModelArtifacts:
    def test_current_repo_is_clean(self):
        result = scan_for_forbidden_model_artifacts(REPO_ROOT)
        assert result["clean"], f"Unexpected artifacts: {result['found_artifacts']}"

    def test_flags_safetensors(self, tmp_path):
        (tmp_path / "model.safetensors").write_bytes(b"fake")
        result = scan_for_forbidden_model_artifacts(tmp_path)
        assert not result["clean"]
        assert any("safetensors" in p for p in result["found_artifacts"])

    def test_flags_gguf(self, tmp_path):
        (tmp_path / "model.gguf").write_bytes(b"fake")
        result = scan_for_forbidden_model_artifacts(tmp_path)
        assert not result["clean"]

    def test_flags_pt(self, tmp_path):
        (tmp_path / "weights.pt").write_bytes(b"fake")
        result = scan_for_forbidden_model_artifacts(tmp_path)
        assert not result["clean"]

    def test_flags_ckpt(self, tmp_path):
        (tmp_path / "checkpoint.ckpt").write_bytes(b"fake")
        result = scan_for_forbidden_model_artifacts(tmp_path)
        assert not result["clean"]

    def test_skips_target_directory(self, tmp_path):
        target = tmp_path / "target" / "debug"
        target.mkdir(parents=True)
        (target / "dep-graph.bin").write_bytes(b"rust build artifact")
        result = scan_for_forbidden_model_artifacts(tmp_path)
        assert result["clean"], "Rust build .bin should be excluded"

    def test_skips_git_directory(self, tmp_path):
        gitdir = tmp_path / ".git"
        gitdir.mkdir()
        (gitdir / "pack.bin").write_bytes(b"git pack")
        result = scan_for_forbidden_model_artifacts(tmp_path)
        assert result["clean"]

    def test_skips_pycache_directory(self, tmp_path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "something.bin").write_bytes(b"pyc")
        result = scan_for_forbidden_model_artifacts(tmp_path)
        assert result["clean"]

    def test_found_artifacts_is_empty_list_when_clean(self, tmp_path):
        result = scan_for_forbidden_model_artifacts(tmp_path)
        assert result["found_artifacts"] == []
        assert result["clean"] is True


# ---------------------------------------------------------------------------
# scan_training_for_forbidden_runtime_imports
# ---------------------------------------------------------------------------

class TestScanForForbiddenRuntimeImports:
    def test_current_training_code_is_clean(self):
        result = scan_training_for_forbidden_runtime_imports(REPO_ROOT)
        assert result["clean"], f"Unexpected violations: {result['violations']}"

    def test_flags_openai_import(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        (training / "bad_module.py").write_text(
            "import openai\n\nprint('hello')\n", encoding="utf-8"
        )
        result = scan_training_for_forbidden_runtime_imports(tmp_path)
        assert not result["clean"]
        assert any("openai" in v["match"] for v in result["violations"])

    def test_flags_subprocess_import(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        (training / "bad_module.py").write_text(
            "import subprocess\n\nsubprocess.run(['ls'])\n", encoding="utf-8"
        )
        result = scan_training_for_forbidden_runtime_imports(tmp_path)
        assert not result["clean"]
        assert any("subprocess" in v["match"] for v in result["violations"])

    def test_flags_anthropic_import(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        (training / "bad_module.py").write_text(
            "from anthropic import Anthropic\n", encoding="utf-8"
        )
        result = scan_training_for_forbidden_runtime_imports(tmp_path)
        assert not result["clean"]

    def test_does_not_flag_string_references_in_code(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        (training / "safe_module.py").write_text(
            '# Blocked providers: openai, anthropic\n'
            'BLOCKED = ["openai", "anthropic"]\n'
            'def check(): return "no provider calls"\n',
            encoding="utf-8",
        )
        result = scan_training_for_forbidden_runtime_imports(tmp_path)
        assert result["clean"], f"False positive violations: {result['violations']}"

    def test_does_not_flag_doc_text(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        (training / "doc_module.py").write_text(
            '"""\nDo not use import openai or import anthropic.\n"""\n\ndef fn(): pass\n',
            encoding="utf-8",
        )
        result = scan_training_for_forbidden_runtime_imports(tmp_path)
        assert result["clean"], f"False positive in docstring: {result['violations']}"

    def test_scanned_files_list_is_nonempty(self):
        result = scan_training_for_forbidden_runtime_imports(REPO_ROOT)
        assert len(result["scanned_files"]) > 0


# ---------------------------------------------------------------------------
# build_phase_status_summary
# ---------------------------------------------------------------------------

class TestBuildPhaseStatusSummary:
    def test_includes_all_covered_phases(self):
        summary = build_phase_status_summary()
        required = {"TR-03", "TR-04", "TR-06A", "TR-06B", "TR-06C", "TR-06D", "TR-06E"}
        assert required.issubset(summary.keys())

    def test_all_phases_have_status_sealed(self):
        summary = build_phase_status_summary()
        for phase_id, info in summary.items():
            assert info["status"] == "sealed", f"Phase {phase_id} not sealed"

    def test_covered_phases_list_matches_summary(self):
        summary = build_phase_status_summary()
        assert len(summary) == len(set(summary.keys()))

    def test_tr06e_present(self):
        summary = build_phase_status_summary()
        assert "TR-06E" in summary

    def test_each_phase_has_required_keys(self):
        summary = build_phase_status_summary()
        for phase_id, info in summary.items():
            assert "phase_id" in info
            assert "description" in info
            assert "status" in info


# ---------------------------------------------------------------------------
# build_training_readiness_audit_seal (fixture mode)
# ---------------------------------------------------------------------------

class TestBuildAuditSeal:
    def test_builds_with_fixture(self):
        seal = _make_fixture_seal()
        validate_training_readiness_audit_seal(seal)

    def test_readiness_state_sealed_when_all_clean(self):
        seal = _make_fixture_seal()
        assert seal["readiness_state"] == "sealed_metadata_only_training_readiness"

    def test_tr07_authorization_status_not_authorized(self):
        seal = _make_fixture_seal()
        assert seal["tr07_authorization_status"] == "not_authorized"

    def test_no_real_training_true(self):
        seal = _make_fixture_seal()
        assert seal["forbidden_action_attestation"]["no_real_training"] is True

    def test_no_model_weights_true(self):
        seal = _make_fixture_seal()
        assert seal["forbidden_action_attestation"]["no_model_weights"] is True

    def test_no_real_model_inference_true(self):
        seal = _make_fixture_seal()
        assert seal["forbidden_action_attestation"]["no_real_model_inference"] is True

    def test_no_provider_calls_true(self):
        seal = _make_fixture_seal()
        assert seal["forbidden_action_attestation"]["no_provider_calls"] is True

    def test_no_store1_writes_true(self):
        seal = _make_fixture_seal()
        assert seal["forbidden_action_attestation"]["no_store1_writes"] is True

    def test_no_runtime_deployment_true(self):
        seal = _make_fixture_seal()
        assert seal["forbidden_action_attestation"]["no_runtime_deployment"] is True

    def test_no_model_promotion_true(self):
        seal = _make_fixture_seal()
        assert seal["forbidden_action_attestation"]["no_model_promotion"] is True

    def test_promotion_blocked_true(self):
        seal = _make_fixture_seal()
        assert seal["promotion_blocking_attestation"]["promotion_blocked"] is True

    def test_promotion_decision_emitted_false(self):
        seal = _make_fixture_seal()
        assert seal["promotion_blocking_attestation"]["promotion_decision_emitted"] is False

    def test_seal_id_starts_with_as(self):
        seal = _make_fixture_seal()
        assert seal["audit_seal_id"].startswith("AS-")

    def test_seal_hash_64_chars(self):
        seal = _make_fixture_seal()
        assert len(seal["seal_hash"]) == 64

    def test_has_all_required_fields(self):
        seal = _make_fixture_seal()
        assert REQUIRED_SEAL_FIELDS.issubset(seal.keys())

    def test_sealed_readiness_not_promotion_in_rationale(self):
        seal = _make_fixture_seal()
        rationale = seal.get("readiness_rationale", "").lower()
        assert "not promotion" in rationale or "not authorized" in rationale

    def test_covered_phases_nonempty(self):
        seal = _make_fixture_seal()
        assert len(seal["covered_phases"]) > 0


# ---------------------------------------------------------------------------
# compute_seal_hash
# ---------------------------------------------------------------------------

class TestComputeSealHash:
    def test_deterministic(self):
        seal = _make_fixture_seal()
        h1 = compute_seal_hash(seal)
        h2 = compute_seal_hash(seal)
        assert h1 == h2

    def test_changes_when_notes_change(self):
        s1 = _make_fixture_seal(notes="Note A")
        s2 = _make_fixture_seal(notes="Note B")
        assert compute_seal_hash(s1) != compute_seal_hash(s2)

    def test_stored_hash_matches_recomputed(self):
        seal = _make_fixture_seal()
        assert seal["seal_hash"] == compute_seal_hash(seal)

    def test_hash_excludes_seal_hash_field(self):
        seal = _make_fixture_seal()
        stored = seal["seal_hash"]
        seal["seal_hash"] = "x" * 64
        recomputed = compute_seal_hash(seal)
        assert recomputed == stored


# ---------------------------------------------------------------------------
# validate_training_readiness_audit_seal
# ---------------------------------------------------------------------------

class TestValidateAuditSeal:
    def test_validates_valid_seal(self):
        seal = _make_fixture_seal()
        result = validate_training_readiness_audit_seal(seal)
        assert result["valid"] is True

    def test_rejects_wrong_expected_head(self):
        seal = _make_fixture_seal(expected_head_commit="deadbeef")
        with pytest.raises(AuditSealValidationError, match="expected_head_commit"):
            validate_training_readiness_audit_seal(seal)

    def test_accepts_matching_expected_head(self):
        seal = _make_fixture_seal(expected_head_commit="1bbbb1b")
        result = validate_training_readiness_audit_seal(seal)
        assert result["valid"] is True

    def test_rejects_test_count_below_minimum(self):
        seal = _make_fixture_seal(test_count=100)
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="test_count"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_test_count_none(self):
        seal = _make_fixture_seal(test_count=None)
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="test_count"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_tr07_authorized(self):
        seal = _make_fixture_seal(tr07_authorization_status="pending_operator_decision")
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="tr07"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_no_real_training_false(self):
        seal = _make_fixture_seal()
        seal["forbidden_action_attestation"]["no_real_training"] = False
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="no_real_training"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_no_model_promotion_false(self):
        seal = _make_fixture_seal()
        seal["forbidden_action_attestation"]["no_model_promotion"] = False
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="no_model_promotion"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_promotion_blocked_false(self):
        seal = _make_fixture_seal()
        seal["promotion_blocking_attestation"]["promotion_blocked"] = False
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="promotion_blocked"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_promotion_decision_emitted_true(self):
        seal = _make_fixture_seal()
        seal["promotion_blocking_attestation"]["promotion_decision_emitted"] = True
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="promotion_decision"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_dirty_forbidden_artifact_scan(self):
        seal = _make_fixture_seal()
        seal["forbidden_artifact_scan"] = {
            "scanned_extensions": [".pt"],
            "found_artifacts":    ["model.pt"],
            "clean":              False,
        }
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="forbidden_artifact"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_missing_field(self):
        seal = _make_fixture_seal()
        del seal["branch"]
        with pytest.raises(AuditSealValidationError, match="branch"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_short_seal_hash(self):
        seal = _make_fixture_seal()
        seal["seal_hash"] = "short"
        with pytest.raises(AuditSealValidationError, match="seal_hash"):
            validate_training_readiness_audit_seal(seal)

    def test_rejects_empty_covered_phases(self):
        seal = _make_fixture_seal(covered_phases=[])
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="covered_phases"):
            validate_training_readiness_audit_seal(seal)


# ---------------------------------------------------------------------------
# save / load / summarize
# ---------------------------------------------------------------------------

class TestSaveLoadSeal:
    def test_save_creates_seal_file(self, tmp_path):
        seal = _make_fixture_seal()
        path = save_training_readiness_audit_seal(seal, str(tmp_path))
        assert path.exists()
        assert path.name == "training_readiness_audit_seal.json"

    def test_save_creates_checksums_file(self, tmp_path):
        seal = _make_fixture_seal()
        save_training_readiness_audit_seal(seal, str(tmp_path))
        assert (tmp_path / "checksums.sha256").exists()

    def test_checksums_references_seal_file(self, tmp_path):
        seal = _make_fixture_seal()
        save_training_readiness_audit_seal(seal, str(tmp_path))
        content = (tmp_path / "checksums.sha256").read_text()
        assert "training_readiness_audit_seal.json" in content

    def test_load_round_trips(self, tmp_path):
        seal = _make_fixture_seal()
        path = save_training_readiness_audit_seal(seal, str(tmp_path))
        loaded = load_training_readiness_audit_seal(str(path))
        assert loaded["audit_seal_id"] == seal["audit_seal_id"]
        assert loaded["readiness_state"] == seal["readiness_state"]

    def test_load_rejects_nonexistent_file(self, tmp_path):
        with pytest.raises(AuditSealError):
            load_training_readiness_audit_seal(str(tmp_path / "missing.json"))

    def test_save_rejects_invalid_seal(self, tmp_path):
        seal = _make_fixture_seal()
        seal["promotion_blocking_attestation"]["promotion_blocked"] = False
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError):
            save_training_readiness_audit_seal(seal, str(tmp_path))


class TestSummarizeAuditSeal:
    def test_has_readiness_state(self):
        seal = _make_fixture_seal()
        summary = summarize_training_readiness_audit_seal(seal)
        assert summary["readiness_state"] == "sealed_metadata_only_training_readiness"

    def test_has_tr07_status(self):
        seal = _make_fixture_seal()
        summary = summarize_training_readiness_audit_seal(seal)
        assert summary["tr07_authorization_status"] == "not_authorized"

    def test_has_seal_hash(self):
        seal = _make_fixture_seal()
        summary = summarize_training_readiness_audit_seal(seal)
        assert len(summary["seal_hash"]) == 64

    def test_has_file_counts(self):
        inv = collect_training_file_inventory(REPO_ROOT)
        seal = _make_fixture_seal(
            training_file_inventory=inv["training_file_inventory"],
            schema_inventory=inv["schema_inventory"],
            module_inventory=inv["module_inventory"],
            documentation_inventory=inv["documentation_inventory"],
            test_inventory=inv["test_inventory"],
        )
        seal["seal_hash"] = compute_seal_hash(seal)
        summary = summarize_training_readiness_audit_seal(seal)
        assert summary["schema_count"] > 0
        assert summary["module_count"] > 0
        assert summary["doc_count"] > 0
        assert summary["test_file_count"] > 0

    def test_forbidden_artifact_scan_reflected(self):
        seal = _make_fixture_seal()
        summary = summarize_training_readiness_audit_seal(seal)
        assert summary["forbidden_artifacts_clean"] is True


# ---------------------------------------------------------------------------
# assert_tr07_not_authorized
# ---------------------------------------------------------------------------

class TestAssertTr07NotAuthorized:
    def test_passes_for_not_authorized(self):
        seal = _make_fixture_seal()
        assert_tr07_not_authorized(seal)  # should not raise

    def test_raises_for_pending_operator_decision(self):
        seal = _make_fixture_seal(tr07_authorization_status="pending_operator_decision")
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="TR-07"):
            assert_tr07_not_authorized(seal)

    def test_raises_for_blocked(self):
        seal = _make_fixture_seal(tr07_authorization_status="blocked")
        seal["seal_hash"] = compute_seal_hash(seal)
        with pytest.raises(AuditSealValidationError, match="TR-07"):
            assert_tr07_not_authorized(seal)

    def test_raises_for_any_non_not_authorized_string(self):
        for status in ("authorized", "enabled", "pending", "approved"):
            seal = _make_fixture_seal(tr07_authorization_status=status)
            seal["seal_hash"] = compute_seal_hash(seal)
            with pytest.raises(AuditSealValidationError):
                assert_tr07_not_authorized(seal)


# ---------------------------------------------------------------------------
# Real repo integration (does not require clean working tree)
# ---------------------------------------------------------------------------

class TestRealRepoIntegration:
    def test_inventory_includes_tr06_family(self):
        inv = collect_training_file_inventory(REPO_ROOT)
        docs = [e["path"] for e in inv["documentation_inventory"]]
        for phase in ["TR_06A", "TR_06B", "TR_06C", "TR_06D", "TR_06E"]:
            assert any(phase in p for p in docs), f"Missing doc for {phase}"

    def test_current_repo_artifact_scan_clean(self):
        result = scan_for_forbidden_model_artifacts(REPO_ROOT)
        assert result["clean"]

    def test_current_training_import_scan_clean(self):
        result = scan_training_for_forbidden_runtime_imports(REPO_ROOT)
        assert result["clean"], f"Violations: {result['violations']}"

    def test_real_seal_from_repo_passes_validation(self, tmp_path):
        """Build a seal from real repo state (working tree will be unclean but
        we use a fixture override so we can test the full pipeline end-to-end."""
        inv = collect_training_file_inventory(REPO_ROOT)
        art = scan_for_forbidden_model_artifacts(REPO_ROOT)
        phases = build_phase_status_summary()
        seal = _make_fixture_seal(
            training_file_inventory=inv["training_file_inventory"],
            schema_inventory=inv["schema_inventory"],
            module_inventory=inv["module_inventory"],
            documentation_inventory=inv["documentation_inventory"],
            test_inventory=inv["test_inventory"],
            checksum_manifest=inv["checksum_manifest"],
            forbidden_artifact_scan=art,
            phase_status_summary=phases,
        )
        seal["seal_hash"] = compute_seal_hash(seal)
        result = validate_training_readiness_audit_seal(seal)
        assert result["valid"] is True

    def test_real_seal_save_and_load(self, tmp_path):
        """Build, save, and load a seal using real inventory."""
        inv = collect_training_file_inventory(REPO_ROOT)
        seal = _make_fixture_seal(
            training_file_inventory=inv["training_file_inventory"],
            schema_inventory=inv["schema_inventory"],
            module_inventory=inv["module_inventory"],
            documentation_inventory=inv["documentation_inventory"],
            test_inventory=inv["test_inventory"],
            checksum_manifest=inv["checksum_manifest"],
        )
        seal["seal_hash"] = compute_seal_hash(seal)
        path = save_training_readiness_audit_seal(seal, str(tmp_path))
        loaded = load_training_readiness_audit_seal(str(path))
        assert loaded["seal_hash"] == seal["seal_hash"]


# ---------------------------------------------------------------------------
# Module purity
# ---------------------------------------------------------------------------

class TestModulePurity:
    def test_no_external_provider_imports(self):
        src = Path(__file__).parent.parent / "training_readiness_audit_seal.py"
        # Check only actual import lines (lines starting with 'import ' or 'from '),
        # not string literals that list provider names for the import scanner.
        import_lines = [
            line.strip() for line in src.read_text().splitlines()
            if line.strip().startswith("import ") or line.strip().startswith("from ")
        ]
        actual_imports = "\n".join(import_lines)
        for token in ("openai", "anthropic", "torch", "tensorflow",
                      "transformers", "boto3", "huggingface_hub", "ollama",
                      "groq", "google.generativeai"):
            for imp_line in import_lines:
                assert token not in imp_line, (
                    f"Forbidden import found: {imp_line!r} (matched {token!r})"
                )

    def test_module_compiles(self):
        import importlib.util
        p = Path(__file__).parent.parent / "training_readiness_audit_seal.py"
        spec = importlib.util.spec_from_file_location("training_readiness_audit_seal", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "build_training_readiness_audit_seal")
        assert hasattr(mod, "assert_tr07_not_authorized")
        assert hasattr(mod, "scan_for_forbidden_model_artifacts")
