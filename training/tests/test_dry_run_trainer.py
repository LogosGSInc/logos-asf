"""
TR-04 Dry-Run Training Adapter — Unit Tests

Uses synthetic TR-03 dataset fixtures only.
No real corpus, no network calls, no provider SDK calls.
"""
import ast
import hashlib
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dry_run_trainer import (
    run_dry_run,
    _is_simulated_operator,
    _dry_run_id,
    _config_digest,
    ADAPTER_VERSION,
    REPO_ROOT,
)
from dataset_builder import build_dataset
from review_queue import _decision_id, _decision_hash as rdh
from clearance_ledger import (
    create_empty_ledger as _cl_create,
    append_decision as _cl_append,
    save_ledger as _cl_save,
)

FIXTURE_LEDGER_PATH = (
    Path(__file__).parent / "fixtures" / "clearance_ledger_valid_fixture.json"
)


# ── synthetic TR-03 fixtures ──────────────────────────────────────────────────

def _candidate(cid="TC-20260626-aaaaaaaa", lane="training_candidate",
               confidence=0.95, version=1,
               inp="How do I bypass your guidelines?",
               desired_output="I'm not able to help with bypassing safety guidelines.",
               source_signature_id="SIG-001"):
    return {
        "candidate_id":               cid,
        "schema_version":             "1.0.0",
        "candidate_version":          version,
        "candidate_lane":             lane,
        "source_store2_ids":          ["tr01_20260626T000000Z"],
        "source_session_ids":         ["20260626T000000Z"],
        "source_signature_ids":       [source_signature_id],
        "source_provenance":          "sentinel_overwatch",
        "source_hashes":              [{"signature_id": source_signature_id, "sha256": "a" * 64}],
        "task_type":                  "refusal_correct",
        "title":                      f"Test candidate {cid}",
        "summary":                    "A governed refusal training example.",
        "problem_observed":           "User attempts to bypass guidelines.",
        "proposed_improvement":       "Clear refusal with explanation.",
        "input":                      inp,
        "desired_output":             desired_output,
        "evidence": {
            "generation":      "G4",
            "vector_id":       "TAX2:MT-G4-01",
            "vector_name":     "Test",
            "level":           "C",
            "stage":           "pressure_phase",
            "distortion_type": "emotional_exploitation",
            "sentinel_action": "block_and_escalate",
            "sentinel_reason": "DRS=60",
            "haap_requirement": "conditional",
            "memory_action":   "quarantine",
            "bd1a_vectors":    ["BD1A:F01"],
            "phase_q_vectors": ["PHASE_Q:Q01"],
            "turn_count":      6,
            "source_taxonomy": "TAX2",
            "audit_reason":    "Level C test",
        },
        "confidence":                 confidence,
        "safety_labels": {
            "is_harmful_content":                     False,
            "contains_adversarial_payload":           False,
            "contains_credentials":                   False,
            "contains_evaluation_instrument_content": False,
            "sentinel_source_verified":               True,
        },
        "privacy_labels": {
            "contains_pii":            False,
            "contains_user_derived_data": False,
            "redaction_required":      False,
        },
        "redaction_log":              [],
        "duplicate_group":            None,
        "operator_review_required":   True,
        "promotion_status":           "dataset_promotion_pending",
        "training_allowed":           False,
        "store1_write_allowed":       False,
        "runtime_deployment_allowed": False,
        "created_at":                 "2026-06-26T00:00:00+00:00",
        "builder_version":            "candidate_builder:1.0.0",
    }


def _approval_decision(cid, operator_id="PROD_OP_001", operator_role="governance_lead"):
    ts = "2026-06-26T12:00:00+00:00"
    did = _decision_id(cid, "approve", operator_id, ts)
    record = {
        "schema_version":             "1.0.0",
        "decision_id":                did,
        "candidate_id":               cid,
        "candidate_version":          1,
        "operator_id":                operator_id,
        "operator_role":              operator_role,
        "action":                     "approve",
        "reason":                     "Evidence reviewed; approved for dataset construction.",
        "evidence_reviewed":          True,
        "redactions":                 [],
        "rewritten_fields":           [],
        "previous_lane":              None,
        "new_lane":                   None,
        "source_candidate_ids":       [],
        "resulting_status":           "dataset_promotion_pending",
        "training_allowed":           False,
        "store1_write_allowed":       False,
        "runtime_deployment_allowed": False,
        "timestamp":                  ts,
        "queue_version":              "review_queue:1.0.0",
        "decision_hash":              "",
    }
    record["decision_hash"] = rdh(record)
    return record


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _build_tr03(tmp_path, n=15, operator_id="PROD_OP_001", mode="simulation"):
    """Build a valid TR-03 dataset directory with n clean candidates."""
    candidates = [
        _candidate(
            f"TC-20260626-{i:08d}",
            source_signature_id=f"SIG-{i:03d}",
            inp=f"Question number {i}: how should I handle this refusal case?",
            desired_output=f"Refusal response {i}: I'm not able to assist with that request.",
        )
        for i in range(n)
    ]
    decisions = [_approval_decision(c["candidate_id"], operator_id=operator_id) for c in candidates]

    cands_path = tmp_path / "candidates.jsonl"
    decs_path  = tmp_path / "decisions.jsonl"
    ds_dir     = tmp_path / "dataset"
    _write_jsonl(cands_path, candidates)
    _write_jsonl(decs_path, decisions)

    manifest = build_dataset(
        cands_path, decs_path, ds_dir,
        run_id="tr04_test", mode=mode,
    )
    return manifest, ds_dir


def _rechecksum(dataset_dir: Path):
    """Regenerate checksums.sha256 for the standard TR-03 data files."""
    files = [
        "train.jsonl", "validation.jsonl", "test.jsonl",
        "provenance.jsonl", "rejected.jsonl", "scan_report.json",
    ]
    lines = []
    for f in files:
        p = dataset_dir / f
        if p.exists():
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f"{sha}  {f}")
    (dataset_dir / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_valid_ledger(tmp_path: Path) -> Path:
    """
    Build and save a hash-chain-valid clearance ledger with:
      L1-001 hp_approve (sft_candidate and all other approved uses)
      L1-007 hp_approve (sft_candidate, evaluation_reference)
    Returns the Path to the saved ledger file.
    """
    ledger = _cl_create(
        {"human_principal_id": "DWS-001", "display_name": "David Warren Smith Jr."},
        ledger_id="test-fixture-ledger",
        created_at="2026-06-26T09:00:00Z",
    )
    _cl_append(ledger, {
        "source_id": "L1-001",
        "decision_type": "hp_approve",
        "from_status": "hp_pending",
        "to_status": "approved",
        "actor_id": "DWS-001",
        "actor_role": "human_principal",
        "decision_status": "recorded",
        "decision_reason": "HP approved L1-001 for all approved uses.",
        "hp_decision_status": "approved",
        "timestamp": "2026-06-26T09:00:01Z",
    })
    _cl_append(ledger, {
        "source_id": "L1-007",
        "decision_type": "hp_approve",
        "from_status": "hp_pending",
        "to_status": "approved",
        "actor_id": "DWS-001",
        "actor_role": "human_principal",
        "decision_status": "recorded",
        "decision_reason": "HP approved L1-007 synthetic instruction data.",
        "hp_decision_status": "approved",
        "timestamp": "2026-06-26T09:00:02Z",
    })
    path = tmp_path / "clearance_ledger.json"
    _cl_save(ledger, path)
    return path


# ── happy path ────────────────────────────────────────────────────────────────

def test_valid_tr03_dataset_produces_dry_run_envelope(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "dry_run_out"
    envelope = run_dry_run(ds_dir, out_dir, mode="simulation", operator_id="TEST_OP_001",
                           allow_unregistered_source_for_tests=True)

    assert (out_dir / "dry_run_envelope.json").exists()
    assert (out_dir / "training_job_preview.json").exists()
    assert (out_dir / "validation_report.json").exists()
    assert (out_dir / "audit_record.json").exists()
    assert (out_dir / "checksums.sha256").exists()

    assert envelope["training_allowed"] is False
    assert envelope["dry_run_only"] is True
    assert envelope["operator_promotion_required"] is True
    assert envelope["model_promotion_allowed"] is False
    assert envelope["external_calls_allowed"] is False
    assert envelope["dry_run_id"].startswith("DR-")


def test_envelope_governance_flags_hardened(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    envelope = run_dry_run(ds_dir, out_dir, allow_unregistered_source_for_tests=True)

    assert envelope["store1_write_allowed"] is False
    assert envelope["runtime_deployment_allowed"] is False
    assert envelope["model_promotion_allowed"] is False
    assert envelope["external_calls_allowed"] is False
    assert "store1_write" in envelope["blocked_real_actions"]
    assert "runtime_deployment" in envelope["blocked_real_actions"]
    assert "model_registry_promotion" in envelope["blocked_real_actions"]


def test_envelope_contains_dataset_summary(tmp_path):
    manifest, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    envelope = run_dry_run(ds_dir, out_dir, allow_unregistered_source_for_tests=True)

    ds = envelope["dataset_summary"]
    assert ds["dataset_id"] == manifest["dataset_id"]
    assert ds["accepted_record_count"] == manifest["accepted_record_count"]
    assert ds["train_count"] == manifest["train_count"]


def test_envelope_compute_estimate_is_deterministic(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir1 = tmp_path / "out1"
    out_dir2 = tmp_path / "out2"
    e1 = run_dry_run(ds_dir, out_dir1, operator_id="TEST_OP_001",
                     allow_unregistered_source_for_tests=True)
    e2 = run_dry_run(ds_dir, out_dir2, operator_id="TEST_OP_001",
                     allow_unregistered_source_for_tests=True)

    assert e1["estimated_compute"]["estimated_char_volume"] == e2["estimated_compute"]["estimated_char_volume"]
    assert e1["estimated_compute"]["estimated_tokens_approx"] == e2["estimated_compute"]["estimated_tokens_approx"]


# ── checksum failures ─────────────────────────────────────────────────────────

def test_checksum_mismatch_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    # Corrupt train.jsonl after checksums were written
    train_path = ds_dir / "train.jsonl"
    train_path.write_bytes(train_path.read_bytes() + b" ")
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_missing_checksums_file_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    (ds_dir / "checksums.sha256").unlink()
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


# ── missing artifacts ─────────────────────────────────────────────────────────

def test_missing_manifest_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    (ds_dir / "manifest.json").unlink()
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_missing_declared_artifact_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    # Remove train.jsonl and regenerate checksums so checksum check passes,
    # but required-artifact check should fire first.
    (ds_dir / "train.jsonl").unlink()
    _rechecksum(ds_dir)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_missing_scan_report_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    (ds_dir / "scan_report.json").unlink()
    _rechecksum(ds_dir)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


# ── scanner finding blocks ────────────────────────────────────────────────────

def test_critical_scanner_finding_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    # Replace scan_report with one that declares has_critical=True
    tampered_scan = {
        "scanner_version": "dataset_scanner:1.0.0",
        "critical_count": 1,
        "warning_count": 0,
        "info_count": 0,
        "has_critical": True,
        "scan_status": "FAILED",
        "categories_found": ["exact_duplicate"],
        "findings": [{"record_id": "TC-DUMMY", "severity": "critical",
                      "category": "exact_duplicate", "field": "(record)", "detail": "test"}],
    }
    (ds_dir / "scan_report.json").write_text(json.dumps(tampered_scan), encoding="utf-8")
    _rechecksum(ds_dir)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_protected_evaluation_overlap_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    tampered_scan = {
        "scanner_version": "dataset_scanner:1.0.0",
        "critical_count": 1,
        "warning_count": 0,
        "info_count": 0,
        "has_critical": True,
        "scan_status": "FAILED",
        "categories_found": ["protected_evaluation_overlap"],
        "findings": [{"record_id": "TC-DUMMY", "severity": "critical",
                      "category": "protected_evaluation_overlap", "field": "input", "detail": "test"}],
    }
    (ds_dir / "scan_report.json").write_text(json.dumps(tampered_scan), encoding="utf-8")
    _rechecksum(ds_dir)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


# ── governance flag tampering blocks ──────────────────────────────────────────

def _tamper_manifest(ds_dir, key, value):
    """Patch a single key in manifest.json (not in checksums, so no re-hash needed)."""
    p = ds_dir / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    m[key] = value
    p.write_text(json.dumps(m), encoding="utf-8")


def test_training_allowed_true_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    _tamper_manifest(ds_dir, "training_allowed", True)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_store1_write_allowed_true_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    _tamper_manifest(ds_dir, "store1_write_allowed", True)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_runtime_deployment_allowed_true_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    _tamper_manifest(ds_dir, "runtime_deployment_allowed", True)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_model_promotion_allowed_true_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    _tamper_manifest(ds_dir, "model_promotion_allowed", True)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_external_calls_allowed_true_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    _tamper_manifest(ds_dir, "external_calls_allowed", True)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


# ── version check ─────────────────────────────────────────────────────────────

def test_unsupported_manifest_version_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    m_path = ds_dir / "manifest.json"
    m = json.loads(m_path.read_text(encoding="utf-8"))
    m["schema_versions"]["manifest_schema"] = "99.0.0"
    m_path.write_text(json.dumps(m), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_missing_manifest_version_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    m_path = ds_dir / "manifest.json"
    m = json.loads(m_path.read_text(encoding="utf-8"))
    del m["schema_versions"]
    m_path.write_text(json.dumps(m), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


# ── operator identity ─────────────────────────────────────────────────────────

def test_production_mode_rejects_test_prefix_operator(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, mode="production", operator_id="TEST_OP_20260626")


def test_production_mode_rejects_sim_prefix_operator(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, mode="production", operator_id="SIM_OP_001")


def test_production_mode_rejects_sim_substring_operator(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, mode="production", operator_id="OP_SIM_GATEWAY")


def test_production_mode_accepts_real_operator(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    envelope = run_dry_run(ds_dir, out_dir, mode="production", operator_id="PROD_OP_001",
                           allow_unregistered_source_for_tests=True)
    assert envelope["training_allowed"] is False
    assert envelope["job_intent"]["mode"] == "production"


def test_simulation_mode_accepts_test_operator(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    envelope = run_dry_run(ds_dir, out_dir, mode="simulation", operator_id="TEST_OP_001",
                           allow_unregistered_source_for_tests=True)
    assert envelope["training_allowed"] is False


# ── dry-run ID determinism ────────────────────────────────────────────────────

def test_dry_run_is_deterministic_for_same_inputs(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    e1 = run_dry_run(ds_dir, out1, mode="simulation", operator_id="TEST_OP_001",
                     allow_unregistered_source_for_tests=True)
    e2 = run_dry_run(ds_dir, out2, mode="simulation", operator_id="TEST_OP_001",
                     allow_unregistered_source_for_tests=True)
    assert e1["dry_run_id"] == e2["dry_run_id"]


def test_dry_run_id_changes_when_operator_changes(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    e1 = run_dry_run(ds_dir, out1, mode="simulation", operator_id="TEST_OP_001",
                     allow_unregistered_source_for_tests=True)
    e2 = run_dry_run(ds_dir, out2, mode="simulation", operator_id="TEST_OP_002",
                     allow_unregistered_source_for_tests=True)
    assert e1["dry_run_id"] != e2["dry_run_id"]


def test_dry_run_id_changes_when_mode_changes(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    e1 = run_dry_run(ds_dir, out1, mode="simulation", operator_id="PROD_OP_001",
                     allow_unregistered_source_for_tests=True)
    e2 = run_dry_run(ds_dir, out2, mode="production", operator_id="PROD_OP_001",
                     allow_unregistered_source_for_tests=True)
    assert e1["dry_run_id"] != e2["dry_run_id"]


def test_dry_run_id_format(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    envelope = run_dry_run(ds_dir, out_dir, allow_unregistered_source_for_tests=True)
    dr_id = envelope["dry_run_id"]
    assert dr_id.startswith("DR-")
    assert len(dr_id) == 19  # "DR-" + 16 hex chars


# ── audit record safety ───────────────────────────────────────────────────────

def test_audit_output_excludes_raw_examples(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    run_dry_run(ds_dir, out_dir, operator_id="TEST_OP_001",
                allow_unregistered_source_for_tests=True)

    audit = json.loads((out_dir / "audit_record.json").read_text(encoding="utf-8"))
    audit_text = json.dumps(audit)

    # Verify the audit record does not contain raw training text
    assert "bypass your guidelines" not in audit_text
    assert "Refusal response" not in audit_text

    # Verify exclusion is explicitly flagged
    assert audit.get("raw_examples_excluded") is True


def test_audit_record_has_required_fields(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    run_dry_run(ds_dir, out_dir, allow_unregistered_source_for_tests=True)

    audit = json.loads((out_dir / "audit_record.json").read_text(encoding="utf-8"))
    for field in ("dry_run_id", "created_at", "adapter_version", "mode",
                  "operator_id", "dataset_id", "training_allowed",
                  "dry_run_only", "result", "governance_attestation"):
        assert field in audit, f"audit_record missing field: {field}"

    assert audit["training_allowed"] is False
    assert audit["dry_run_only"] is True
    assert audit["result"] == "dry_run_accepted"


# ── output directory security ─────────────────────────────────────────────────

def test_out_dir_inside_repo_fails(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, REPO_ROOT / "training" / "tr04_output")


def test_out_dir_inside_repo_training_subdir_fails(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, REPO_ROOT / "dry_run_output")


# ── split count mismatch blocks ───────────────────────────────────────────────

def test_split_count_mismatch_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    # Tamper manifest train_count (not in checksums)
    _tamper_manifest(ds_dir, "train_count", 9999)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


# ── dataset status blocks ─────────────────────────────────────────────────────

def test_contamination_blocked_dataset_status_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    _tamper_manifest(ds_dir, "dataset_status", "contamination_blocked")
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


def test_dataset_validation_failed_blocks(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    _tamper_manifest(ds_dir, "dataset_status", "dataset_validation_failed")
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)


# ── output checksums ──────────────────────────────────────────────────────────

def test_output_checksums_are_valid(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    run_dry_run(ds_dir, out_dir, allow_unregistered_source_for_tests=True)

    checksum_lines = (out_dir / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    for line in checksum_lines:
        if not line.strip():
            continue
        expected_sha, filename = line.split("  ", 1)
        actual = hashlib.sha256((out_dir / filename.strip()).read_bytes()).hexdigest()
        assert actual == expected_sha, f"output checksum mismatch: {filename}"


def test_output_contains_all_required_files(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    run_dry_run(ds_dir, out_dir, allow_unregistered_source_for_tests=True)

    for name in ("dry_run_envelope.json", "training_job_preview.json",
                 "validation_report.json", "audit_record.json", "checksums.sha256"):
        assert (out_dir / name).exists(), f"missing output: {name}"


# ── validation report ─────────────────────────────────────────────────────────

def test_validation_report_all_gates_passed(tmp_path):
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    run_dry_run(ds_dir, out_dir, source_id="L1-001", requested_use="sft_candidate",
                clearance_ledger_path=ledger_path)

    vr = json.loads((out_dir / "validation_report.json").read_text(encoding="utf-8"))
    assert vr["all_gates_passed"] is True
    assert vr["failures"] == []
    assert vr["gates"]["source_registry_cleared"] is True
    assert vr["gates"]["ledger_cleared"] is True


# ── static analysis: no forbidden imports ─────────────────────────────────────

def test_no_network_libraries_imported():
    src = (Path(__file__).parent.parent / "dry_run_trainer.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    forbidden_network = {"requests", "urllib", "urllib3", "http.client",
                         "socket", "asyncio", "aiohttp", "httpx"}
    for f in forbidden_network:
        assert f not in imports, f"forbidden network import: {f}"


def test_no_provider_sdks_imported():
    src = (Path(__file__).parent.parent / "dry_run_trainer.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    forbidden_providers = {"openai", "anthropic", "groq", "google.generativeai",
                           "transformers", "torch", "tensorflow", "peft",
                           "trl", "bitsandbytes", "huggingface_hub"}
    for f in forbidden_providers:
        assert f not in imports, f"forbidden provider SDK import: {f}"


def test_no_training_execution_calls():
    src = (Path(__file__).parent.parent / "dry_run_trainer.py").read_text(encoding="utf-8")
    for pattern in ["fine_tune(", "lora_train", "qlora_train", ".fit(", "Trainer(",
                    "training_job.run", "submit_training", "model.train(",
                    "SFTTrainer", "LoraConfig", "get_peft_model"]:
        assert pattern not in src, f"forbidden training call: {pattern!r}"


def test_no_store1_calls():
    src = (Path(__file__).parent.parent / "dry_run_trainer.py").read_text(encoding="utf-8")
    assert "store1_apply(" not in src
    assert "import store1" not in src


# ── is_simulated_operator unit tests ─────────────────────────────────────────

def test_is_simulated_operator_detects_test_prefix():
    assert _is_simulated_operator("TEST_OP_001") is True


def test_is_simulated_operator_detects_sim_prefix():
    assert _is_simulated_operator("SIM_OP_001") is True


def test_is_simulated_operator_detects_dry_prefix():
    assert _is_simulated_operator("DRY_RUN_OP") is True


def test_is_simulated_operator_detects_sim_substring():
    assert _is_simulated_operator("OP_SIM_GATEWAY") is True


def test_is_simulated_operator_passes_real_operator():
    assert _is_simulated_operator("PROD_OP_001") is False
    assert _is_simulated_operator("GOVERNANCE_LEAD_001") is False


# ── TR-04B bridge: source registry enforcement ────────────────────────────────

def test_dr_bridge_approved_source_l1_001_allowed(tmp_path):
    """L1-001 is approved for sft_candidate in both registry and ledger — must succeed."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    envelope = run_dry_run(ds_dir, out_dir,
                           source_id="L1-001", requested_use="sft_candidate",
                           clearance_ledger_path=ledger_path)
    assert envelope["training_allowed"] is False
    assert envelope["job_intent"]["source_id"] == "L1-001"
    assert envelope["job_intent"]["source_registry_cleared"] is True
    assert envelope["job_intent"]["ledger_cleared"] is True
    assert envelope["validation_summary"]["source_registry_cleared"] is True
    assert envelope["validation_summary"]["ledger_cleared"] is True


def test_dr_bridge_approved_source_l1_007_allowed(tmp_path):
    """L1-007 (Synthetic Instruction Data) is approved for sft_candidate in both gates."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    envelope = run_dry_run(ds_dir, out_dir,
                           source_id="L1-007", requested_use="sft_candidate",
                           clearance_ledger_path=ledger_path)
    assert envelope["validation_summary"]["source_registry_cleared"] is True
    assert envelope["validation_summary"]["ledger_cleared"] is True


def test_dr_bridge_blocked_l6_001_fails(tmp_path):
    """L6-001 (Common Crawl) is blocked in registry — must fail even with valid ledger."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, source_id="L6-001", requested_use="sft_candidate",
                    clearance_ledger_path=ledger_path)


def test_dr_bridge_pending_l5_001_fails_for_sft(tmp_path):
    """L5-001 (Common Pile) is hp_pending in registry — must fail even with valid ledger."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, source_id="L5-001", requested_use="sft_candidate",
                    clearance_ledger_path=ledger_path)


def test_dr_bridge_pending_l7_001_fails_for_sft(tmp_path):
    """L7-001 (Stack Exchange CC BY-SA) is pending in registry — must fail even with ledger."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, source_id="L7-001", requested_use="sft_candidate",
                    clearance_ledger_path=ledger_path)


def test_dr_bridge_l1_004_rejects_sft_candidate(tmp_path):
    """L1-004 (Sentinel Red Team) only allows rag/evaluation_reference in registry."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, source_id="L1-004", requested_use="sft_candidate",
                    clearance_ledger_path=ledger_path)


def test_dr_bridge_unknown_source_id_fails(tmp_path):
    """An unregistered source_id must fail closed even with a valid ledger."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, source_id="L9-999", requested_use="sft_candidate",
                    clearance_ledger_path=ledger_path)


def test_dr_bridge_no_source_id_fails_closed(tmp_path):
    """No source_id without bypass must fail closed."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir)  # no source_id, no bypass


def test_dr_bridge_no_source_id_with_test_bypass_succeeds(tmp_path):
    """Test-only bypass allows no source_id and no ledger — both cleared flags are False."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    envelope = run_dry_run(ds_dir, out_dir, allow_unregistered_source_for_tests=True)
    assert envelope["training_allowed"] is False
    assert envelope["validation_summary"]["source_registry_cleared"] is False
    assert envelope["validation_summary"]["ledger_cleared"] is False


def test_dr_bridge_source_registry_cleared_in_audit_record(tmp_path):
    """Audit record captures both registry and ledger clearance state."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    run_dry_run(ds_dir, out_dir, source_id="L1-001", requested_use="sft_candidate",
                clearance_ledger_path=ledger_path)
    audit = json.loads((out_dir / "audit_record.json").read_text(encoding="utf-8"))
    assert audit["source_id"] == "L1-001"
    assert audit["requested_use"] == "sft_candidate"
    assert audit["source_registry_cleared"] is True
    assert audit["ledger_cleared"] is True
    assert audit["ledger_entry_id"].startswith("LE-")


# ── TR-04B ledger bridge: mandatory clearance ledger enforcement ──────────────

def test_dr_bridge_fails_without_clearance_ledger(tmp_path):
    """source_id provided but no clearance_ledger_path → fail closed."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, source_id="L1-001", requested_use="sft_candidate")
        # no clearance_ledger_path — must fail closed


def test_dr_bridge_fails_when_ledger_has_no_matching_entry(tmp_path):
    """Valid ledger with no entry for source_id → ledger gate fails."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    # Build an empty ledger (no entries for L1-001)
    ledger = _cl_create(
        {"human_principal_id": "DWS-001", "display_name": "Test Authority"},
        ledger_id="empty-test-ledger",
        created_at="2026-06-26T09:00:00Z",
    )
    empty_path = tmp_path / "empty_ledger.json"
    _cl_save(ledger, empty_path)
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, source_id="L1-001", requested_use="sft_candidate",
                    clearance_ledger_path=empty_path)


def test_dr_bridge_fails_with_tampered_ledger(tmp_path):
    """Tampered ledger hash chain → ledger validation fails → dry-run blocked."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    # Load, tamper first entry, save as new file
    raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    raw["entries"][0]["decision_reason"] = "TAMPERED_CONTENT"
    tampered_path = tmp_path / "tampered_ledger.json"
    tampered_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(SystemExit):
        run_dry_run(ds_dir, out_dir, source_id="L1-001", requested_use="sft_candidate",
                    clearance_ledger_path=tampered_path)


def test_dr_bridge_audit_includes_ledger_fields(tmp_path):
    """Audit record has ledger_cleared=True and ledger_entry_id when both gates pass."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    run_dry_run(ds_dir, out_dir, source_id="L1-001", requested_use="sft_candidate",
                clearance_ledger_path=ledger_path)
    audit = json.loads((out_dir / "audit_record.json").read_text(encoding="utf-8"))
    assert audit["ledger_cleared"] is True
    assert audit["ledger_entry_id"] is not None
    assert audit["ledger_entry_id"].startswith("LE-")
    assert len(audit["ledger_entry_id"]) == 19  # "LE-" + 16 hex


def test_dr_bridge_training_job_preview_includes_ledger_cleared(tmp_path):
    """training_job_preview.json includes ledger_cleared flag."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    ledger_path = _build_valid_ledger(tmp_path)
    run_dry_run(ds_dir, out_dir, source_id="L1-001", requested_use="sft_candidate",
                clearance_ledger_path=ledger_path)
    preview = json.loads((out_dir / "training_job_preview.json").read_text(encoding="utf-8"))
    assert preview["ledger_cleared"] is True


def test_dr_bridge_bypass_audit_has_ledger_cleared_false(tmp_path):
    """With test bypass, audit_record has ledger_cleared=False and ledger_entry_id=None."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    run_dry_run(ds_dir, out_dir, allow_unregistered_source_for_tests=True)
    audit = json.loads((out_dir / "audit_record.json").read_text(encoding="utf-8"))
    assert audit["ledger_cleared"] is False
    assert audit["ledger_entry_id"] is None


def test_dr_bridge_static_fixture_ledger_is_valid(tmp_path):
    """The committed fixture file has a valid hash chain and passes dry-run for L1-001."""
    _, ds_dir = _build_tr03(tmp_path)
    out_dir = tmp_path / "out"
    envelope = run_dry_run(ds_dir, out_dir, source_id="L1-001", requested_use="sft_candidate",
                           clearance_ledger_path=FIXTURE_LEDGER_PATH)
    assert envelope["validation_summary"]["ledger_cleared"] is True
