"""
Tests for training/synthetic_review_bridge.py — TR-04C
All tests are local-only. No network calls. No LLM calls. No real training.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clearance_ledger import (
    create_empty_ledger,
    append_decision,
    save_ledger,
)
from synthetic_doctrine import run_synthetic_doctrine
from synthetic_review_bridge import (
    run_bridge,
    BRIDGE_VERSION,
    SCHEMA_VERSION,
    CANDIDATE_LANE,
    _candidate_id,
    _REQUIRED_FILES,
)

FIXTURE_LEDGER_PATH = Path(__file__).resolve().parent / "fixtures" / "clearance_ledger_valid_fixture.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_test_ledger(tmp_path, source_ids=("L1-001",)):
    """Build a minimal valid clearance ledger."""
    ledger = create_empty_ledger("test_authority")
    for sid in source_ids:
        append_decision(ledger, {
            "source_id": sid,
            "decision_type": "hp_approve",
            "from_status": "hp_pending",
            "to_status": "approved",
            "actor_id": "DWS-001",
            "actor_role": "human_principal",
            "decision_status": "recorded",
            "decision_reason": f"Test approval for {sid}.",
            "reg01_status": "not_required",
            "lgl01_status": "not_required",
            "hp_decision_status": "approved",
        })
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "ledger.json"
    save_ledger(ledger, path)
    return path


def _generate_synth_dir(tmp_path, source_id="L1-001", limit=4):
    """Generate a real synthetic output dir using synthetic_doctrine."""
    ledger_path = _build_test_ledger(tmp_path / "ledger")
    synth_dir = tmp_path / "synth_out"
    run_synthetic_doctrine(
        source_id=source_id,
        clearance_ledger_path=ledger_path,
        out_dir=synth_dir,
        limit=limit,
    )
    return synth_dir


def _valid_record(record_id="SR-aaaaaaaaaaaaaaaa", gov_overrides=None, **overrides):
    """Factory for a minimal valid synthetic record."""
    gov = {
        "training_allowed": False,
        "operator_review_required": True,
        "store1_write_allowed": False,
        "runtime_deployment_allowed": False,
        "model_promotion_allowed": False,
        "external_calls_allowed": False,
    }
    if gov_overrides:
        gov.update(gov_overrides)
    rec = {
        "record_id": record_id,
        "schema_version": "1.0.0",
        "created_at": "2026-06-27T00:00:00Z",
        "synthetic_origin": True,
        "source_id": "L1-001",
        "source_registry_version": "1.0.0",
        "clearance_ledger_entry_id": "LE-test1234567890ab",
        "generation_agent_id": "TEST_AGENT",
        "prompt_template_id": "tmpl_test_v1",
        "prompt_hash": "a" * 32,
        "category": "user_request_to_abigail_route_decision",
        "input": "Test input.",
        "desired_output": "Test output.",
        "governance_labels": gov,
        "audit_metadata": {
            "generator_version": "synthetic_doctrine:1.0.0",
            "generation_index": 0,
            "clearance_gate": "registry_and_ledger",
        },
    }
    rec.update(overrides)
    return rec


def _make_synth_dir(tmp_path, records, source_id="L1-001"):
    """Create a synthetic output dir with custom records and valid checksums."""
    synth_dir = Path(tmp_path) / "synth_input"
    synth_dir.mkdir(parents=True, exist_ok=True)

    jsonl_content = "\n".join(json.dumps(r) for r in records) + "\n"
    manifest = {
        "generator_version": "synthetic_doctrine:1.0.0",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-27T00:00:00Z",
        "generation_agent_id": "TEST_AGENT",
        "source_id": source_id,
        "source_registry_version": "1.0.0",
        "clearance_ledger_entry_id": "LE-test1234567890ab",
        "record_count": len(records),
        "limit": len(records),
        "categories": [],
        "governance": {
            "training_allowed": False,
            "operator_review_required": True,
            "store1_write_allowed": False,
            "runtime_deployment_allowed": False,
            "model_promotion_allowed": False,
            "external_calls_allowed": False,
        },
        "notes": "Test synthetic dir.",
    }

    jsonl_path = synth_dir / "synthetic_records.jsonl"
    manifest_path = synth_dir / "synthetic_manifest.json"
    jsonl_path.write_text(jsonl_content, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    checksum_lines = [
        f"{_sha256(jsonl_path.read_bytes())}  synthetic_records.jsonl",
        f"{_sha256(manifest_path.read_bytes())}  synthetic_manifest.json",
    ]
    (synth_dir / "checksums.sha256").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    return synth_dir


# ── integration: real generator output ───────────────────────────────────────

class TestIntegration:
    def test_accepts_valid_synthetic_doctrine_output(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=4)
        result = run_bridge(synth_dir, tmp_path / "bridge_out", operator_id="TEST_OP")
        assert len(result["candidates"]) == 4
        assert result["rejected"] == []

    def test_output_files_created(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=4)
        out_dir = tmp_path / "bridge_out"
        run_bridge(synth_dir, out_dir, operator_id="TEST_OP")
        assert (out_dir / "synthetic_candidates.jsonl").exists()
        assert (out_dir / "bridge_manifest.json").exists()
        assert (out_dir / "audit_record.json").exists()
        assert (out_dir / "checksums.sha256").exists()

    def test_checksums_produced_for_outputs(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=4)
        out_dir = tmp_path / "bridge_out"
        run_bridge(synth_dir, out_dir, operator_id="TEST_OP")
        lines = (out_dir / "checksums.sha256").read_text().strip().splitlines()
        assert len(lines) == 3
        filenames = [ln.split(None, 1)[1].strip() for ln in lines]
        assert "synthetic_candidates.jsonl" in filenames
        assert "bridge_manifest.json" in filenames
        assert "audit_record.json" in filenames

    def test_candidates_jsonl_lines_are_valid_json(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=4)
        out_dir = tmp_path / "bridge_out"
        run_bridge(synth_dir, out_dir)
        lines = (out_dir / "synthetic_candidates.jsonl").read_text().strip().splitlines()
        for line in lines:
            obj = json.loads(line)
            assert obj["candidate_lane"] == "training_candidate"


# ── checksum verification ─────────────────────────────────────────────────────

class TestChecksumVerification:
    def test_checksum_verification_passes_on_intact_output(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=2)
        result = run_bridge(synth_dir, tmp_path / "out")
        assert result["candidates"]

    def test_checksum_mismatch_blocks_after_jsonl_tamper(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=2)
        jsonl_path = synth_dir / "synthetic_records.jsonl"
        content = jsonl_path.read_text()
        jsonl_path.write_text(content + "\n")  # append newline → different bytes
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_checksum_mismatch_blocks_after_manifest_tamper(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=2)
        manifest_path = synth_dir / "synthetic_manifest.json"
        data = json.loads(manifest_path.read_text())
        data["notes"] = "TAMPERED"
        manifest_path.write_text(json.dumps(data))
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")


# ── missing files ─────────────────────────────────────────────────────────────

class TestMissingFiles:
    def test_missing_jsonl_blocks(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=2)
        (synth_dir / "synthetic_records.jsonl").unlink()
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_missing_manifest_blocks(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=2)
        (synth_dir / "synthetic_manifest.json").unlink()
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_missing_checksums_blocks(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path, limit=2)
        (synth_dir / "checksums.sha256").unlink()
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")


# ── record-level validation ───────────────────────────────────────────────────

class TestRecordValidation:
    def test_record_missing_synthetic_origin_blocks(self, tmp_path):
        rec = _valid_record()
        del rec["synthetic_origin"]
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_with_synthetic_origin_false_blocks(self, tmp_path):
        rec = _valid_record(synthetic_origin=False)
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_missing_prompt_hash_blocks(self, tmp_path):
        rec = _valid_record()
        del rec["prompt_hash"]
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_missing_generation_agent_id_blocks(self, tmp_path):
        rec = _valid_record()
        del rec["generation_agent_id"]
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_missing_source_id_blocks(self, tmp_path):
        rec = _valid_record()
        del rec["source_id"]
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_missing_clearance_ledger_entry_id_blocks(self, tmp_path):
        rec = _valid_record()
        del rec["clearance_ledger_entry_id"]
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_with_training_allowed_true_blocks(self, tmp_path):
        rec = _valid_record(gov_overrides={"training_allowed": True})
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_with_store1_write_allowed_true_blocks(self, tmp_path):
        rec = _valid_record(gov_overrides={"store1_write_allowed": True})
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_with_runtime_deployment_allowed_true_blocks(self, tmp_path):
        rec = _valid_record(gov_overrides={"runtime_deployment_allowed": True})
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_with_model_promotion_allowed_true_blocks(self, tmp_path):
        rec = _valid_record(gov_overrides={"model_promotion_allowed": True})
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")

    def test_record_with_external_calls_allowed_true_blocks(self, tmp_path):
        rec = _valid_record(gov_overrides={"external_calls_allowed": True})
        synth_dir = _make_synth_dir(tmp_path, [rec])
        with pytest.raises(SystemExit):
            run_bridge(synth_dir, tmp_path / "out")


# ── candidate structure ───────────────────────────────────────────────────────

class TestCandidateStructure:
    def test_valid_records_become_candidates(self, tmp_path):
        recs = [_valid_record(record_id=f"SR-{'a'*15}{i}") for i in range(3)]
        synth_dir = _make_synth_dir(tmp_path, recs)
        result = run_bridge(synth_dir, tmp_path / "out")
        assert len(result["candidates"]) == 3

    def test_candidate_has_training_candidate_lane(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record()])
        result = run_bridge(synth_dir, tmp_path / "out")
        for c in result["candidates"]:
            assert c["candidate_lane"] == CANDIDATE_LANE == "training_candidate"

    def test_candidate_requires_operator_review(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record()])
        result = run_bridge(synth_dir, tmp_path / "out")
        for c in result["candidates"]:
            assert c["operator_review_required"] is True

    def test_candidate_promotion_status_is_candidate_only(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record()])
        result = run_bridge(synth_dir, tmp_path / "out")
        for c in result["candidates"]:
            assert c["promotion_status"] == "candidate_only"

    def test_candidate_has_synthetic_doctrine_provenance(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record()])
        result = run_bridge(synth_dir, tmp_path / "out")
        for c in result["candidates"]:
            assert c["source_provenance"] == "synthetic_doctrine"

    def test_all_candidates_have_governance_false(self, tmp_path):
        recs = [_valid_record(record_id=f"SR-{'b'*15}{i}") for i in range(4)]
        synth_dir = _make_synth_dir(tmp_path, recs)
        result = run_bridge(synth_dir, tmp_path / "out")
        for c in result["candidates"]:
            assert c["training_allowed"] is False
            assert c["store1_write_allowed"] is False
            assert c["runtime_deployment_allowed"] is False
            assert c["model_promotion_allowed"] is False
            assert c["external_calls_allowed"] is False


# ── provenance preservation ───────────────────────────────────────────────────

class TestProvenancePreservation:
    def test_candidate_preserves_source_id(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record(source_id="L1-003")])
        result = run_bridge(synth_dir, tmp_path / "out")
        assert result["candidates"][0]["source_id"] == "L1-003"

    def test_candidate_preserves_clearance_ledger_entry_id(self, tmp_path):
        rec = _valid_record(clearance_ledger_entry_id="LE-deadbeef12345678")
        synth_dir = _make_synth_dir(tmp_path, [rec])
        result = run_bridge(synth_dir, tmp_path / "out")
        assert result["candidates"][0]["clearance_ledger_entry_id"] == "LE-deadbeef12345678"

    def test_candidate_preserves_prompt_hash(self, tmp_path):
        rec = _valid_record(prompt_hash="cafebabe" * 4)
        synth_dir = _make_synth_dir(tmp_path, [rec])
        result = run_bridge(synth_dir, tmp_path / "out")
        assert result["candidates"][0]["prompt_hash"] == "cafebabe" * 4

    def test_candidate_preserves_generation_agent_id(self, tmp_path):
        rec = _valid_record(generation_agent_id="MY_CUSTOM_AGENT_ID")
        synth_dir = _make_synth_dir(tmp_path, [rec])
        result = run_bridge(synth_dir, tmp_path / "out")
        assert result["candidates"][0]["generation_agent_id"] == "MY_CUSTOM_AGENT_ID"

    def test_candidate_preserves_prompt_template_id(self, tmp_path):
        rec = _valid_record(prompt_template_id="tmpl_haap_refusal_v99")
        synth_dir = _make_synth_dir(tmp_path, [rec])
        result = run_bridge(synth_dir, tmp_path / "out")
        assert result["candidates"][0]["prompt_template_id"] == "tmpl_haap_refusal_v99"

    def test_candidate_preserves_source_registry_version(self, tmp_path):
        rec = _valid_record(source_registry_version="2.0.0")
        synth_dir = _make_synth_dir(tmp_path, [rec])
        result = run_bridge(synth_dir, tmp_path / "out")
        assert result["candidates"][0]["source_registry_version"] == "2.0.0"

    def test_candidate_preserves_category(self, tmp_path):
        rec = _valid_record(category="tool_request_to_approval_gate")
        synth_dir = _make_synth_dir(tmp_path, [rec])
        result = run_bridge(synth_dir, tmp_path / "out")
        assert result["candidates"][0]["category"] == "tool_request_to_approval_gate"

    def test_candidate_synthetic_origin_is_true(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record()])
        result = run_bridge(synth_dir, tmp_path / "out")
        for c in result["candidates"]:
            assert c["synthetic_origin"] is True

    def test_candidate_stores_original_record_id(self, tmp_path):
        rec = _valid_record(record_id="SR-123456789abcdef0")
        synth_dir = _make_synth_dir(tmp_path, [rec])
        result = run_bridge(synth_dir, tmp_path / "out")
        assert result["candidates"][0]["synthetic_record_id"] == "SR-123456789abcdef0"

    def test_all_provenance_fields_present(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record()])
        result = run_bridge(synth_dir, tmp_path / "out")
        required = (
            "source_id", "source_registry_version", "clearance_ledger_entry_id",
            "generation_agent_id", "prompt_template_id", "prompt_hash",
            "category", "synthetic_record_id",
        )
        for c in result["candidates"]:
            for field in required:
                assert field in c, f"Candidate missing provenance field: {field!r}"


# ── determinism ───────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_generation_is_deterministic_same_input(self, tmp_path):
        synth_dir = _generate_synth_dir(tmp_path / "gen", limit=4)
        r1 = run_bridge(synth_dir, tmp_path / "out1", operator_id="OP_DET")
        r2 = run_bridge(synth_dir, tmp_path / "out2", operator_id="OP_DET")
        ids1 = [c["candidate_id"] for c in r1["candidates"]]
        ids2 = [c["candidate_id"] for c in r2["candidates"]]
        assert ids1 == ids2, "candidate_ids should be stable across bridge re-runs"
        hashes1 = [c["prompt_hash"] for c in r1["candidates"]]
        hashes2 = [c["prompt_hash"] for c in r2["candidates"]]
        assert hashes1 == hashes2

    def test_candidate_id_stable_for_same_record(self):
        cid1 = _candidate_id("SR-abcdef1234567890", "2026-06-27T00:00:00Z")
        cid2 = _candidate_id("SR-abcdef1234567890", "2026-06-27T00:00:00Z")
        assert cid1 == cid2

    def test_candidate_id_changes_with_different_record_id(self):
        cid1 = _candidate_id("SR-abcdef1234567890", "2026-06-27T00:00:00Z")
        cid2 = _candidate_id("SR-0000000000000000", "2026-06-27T00:00:00Z")
        assert cid1 != cid2


# ── audit record ──────────────────────────────────────────────────────────────

class TestAuditRecord:
    def test_audit_record_excludes_raw_examples(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record(
            input="SECRET INPUT TEXT",
            desired_output="SECRET OUTPUT TEXT",
        )])
        out_dir = tmp_path / "out"
        run_bridge(synth_dir, out_dir)
        audit = json.loads((out_dir / "audit_record.json").read_text())
        audit_text = json.dumps(audit)
        assert "SECRET INPUT TEXT" not in audit_text
        assert "SECRET OUTPUT TEXT" not in audit_text

    def test_audit_record_raw_examples_excluded_flag(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record()])
        out_dir = tmp_path / "out"
        run_bridge(synth_dir, out_dir)
        audit = json.loads((out_dir / "audit_record.json").read_text())
        assert audit["raw_examples_excluded"] is True

    def test_audit_record_no_real_training_flag(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record()])
        out_dir = tmp_path / "out"
        run_bridge(synth_dir, out_dir)
        audit = json.loads((out_dir / "audit_record.json").read_text())
        assert audit["no_real_training"] is True
        assert audit["tr05_started"] is False

    def test_audit_record_candidate_count_matches(self, tmp_path):
        recs = [_valid_record(record_id=f"SR-{'c'*15}{i}") for i in range(5)]
        synth_dir = _make_synth_dir(tmp_path, recs)
        out_dir = tmp_path / "out"
        run_bridge(synth_dir, out_dir)
        audit = json.loads((out_dir / "audit_record.json").read_text())
        assert audit["candidates_produced"] == 5

    def test_audit_record_governance_flags(self, tmp_path):
        synth_dir = _make_synth_dir(tmp_path, [_valid_record()])
        out_dir = tmp_path / "out"
        run_bridge(synth_dir, out_dir)
        audit = json.loads((out_dir / "audit_record.json").read_text())
        gov = audit["governance"]
        assert gov["training_allowed"] is False
        assert gov["operator_review_required"] is True
        assert gov["store1_write_allowed"] is False


# ── module purity ─────────────────────────────────────────────────────────────

class TestModulePurity:
    def test_module_compiles(self):
        import py_compile
        path = Path(__file__).resolve().parent.parent / "synthetic_review_bridge.py"
        py_compile.compile(str(path), doraise=True)

    def test_no_external_provider_imports(self):
        import ast
        blocked_prefixes = (
            "openai", "anthropic", "google.generativeai", "groq",
            "xai", "huggingface_hub", "boto3", "requests", "httpx",
        )
        src = (Path(__file__).resolve().parent.parent / "synthetic_review_bridge.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in blocked_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"Forbidden import {alias.name!r} in synthetic_review_bridge.py"
                        )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for prefix in blocked_prefixes:
                    assert not mod.startswith(prefix), (
                        f"Forbidden from-import {mod!r} in synthetic_review_bridge.py"
                    )

    def test_required_files_constant_matches_generator_output(self):
        assert "synthetic_records.jsonl" in _REQUIRED_FILES
        assert "synthetic_manifest.json" in _REQUIRED_FILES
        assert "checksums.sha256" in _REQUIRED_FILES

    def test_review_queue_can_load_bridge_candidates(self, tmp_path):
        """Bridge candidates must satisfy review_queue.load_candidates requirements."""
        synth_dir = _make_synth_dir(tmp_path, [
            _valid_record(record_id=f"SR-{'d'*15}{i}") for i in range(3)
        ])
        out_dir = tmp_path / "out"
        result = run_bridge(synth_dir, out_dir)
        for c in result["candidates"]:
            assert c.get("candidate_id"), "candidate_id is required by review_queue"
            assert c.get("training_allowed") is False
            assert c.get("store1_write_allowed") is False
            assert c.get("runtime_deployment_allowed") is False
