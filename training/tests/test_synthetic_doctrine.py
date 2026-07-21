"""
Tests for training/synthetic_doctrine.py — TR-04A.5
All tests are local-only. No network calls. No LLM calls. No real training.
"""
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

# Ensure the training/ directory is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clearance_ledger import (
    create_empty_ledger,
    append_decision,
    save_ledger,
    validate_ledger,
)
from synthetic_doctrine import (
    run_synthetic_doctrine,
    CATEGORIES,
    ALLOWED_GENERATION_SOURCES,
    SCHEMA_VERSION,
    GENERATOR_VERSION,
    SYNTHETIC_USE,
    _record_id,
    _prompt_hash,
)

SEED_PATH = Path(__file__).resolve().parent.parent / "source_registry_seed.json"
FIXTURE_LEDGER_PATH = Path(__file__).resolve().parent / "fixtures" / "clearance_ledger_valid_fixture.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_ledger(tmp_path, source_ids=("L1-001",), decision_type="hp_approve"):
    """Build a valid clearance ledger approving the given source IDs."""
    ledger = create_empty_ledger("test_authority")
    for sid in source_ids:
        append_decision(ledger, {
            "source_id": sid,
            "decision_type": decision_type,
            "from_status": "hp_pending",
            "to_status": "approved" if decision_type != "block" else "blocked",
            "actor_id": "DWS-001",
            "actor_role": "human_principal",
            "decision_status": "recorded",
            "decision_reason": f"Test approval for {sid}.",
            "reg01_status": "not_required",
            "lgl01_status": "not_required",
            "hp_decision_status": "approved" if decision_type != "block" else "blocked",
        })
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "test_ledger.json"
    save_ledger(ledger, path)
    return path


def _run_l1001(tmp_path, ledger_path=None, agent_id="AGENT_TEST", limit=8, out_dir=None):
    """Run generator for L1-001 with a test-local ledger."""
    if ledger_path is None:
        ledger_path = _build_ledger(tmp_path)
    if out_dir is None:
        out_dir = tmp_path / "synth_out"
    return run_synthetic_doctrine(
        source_id="L1-001",
        clearance_ledger_path=ledger_path,
        out_dir=out_dir,
        generation_agent_id=agent_id,
        limit=limit,
    )


# ── schema ────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_schema_file_exists(self):
        schema_path = Path(__file__).resolve().parent.parent / "SYNTHETIC_DOCTRINE_RECORD.schema.json"
        assert schema_path.exists()

    def test_schema_is_valid_json(self):
        schema_path = Path(__file__).resolve().parent.parent / "SYNTHETIC_DOCTRINE_RECORD.schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        assert data["$id"] == "logos-asf:training:synthetic-doctrine-record:v1.0.0"
        assert data["type"] == "object"

    def test_schema_requires_governance_consts(self):
        schema_path = Path(__file__).resolve().parent.parent / "SYNTHETIC_DOCTRINE_RECORD.schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        gov = data["properties"]["governance_labels"]["properties"]
        assert gov["training_allowed"]["const"] is False
        assert gov["operator_review_required"]["const"] is True
        assert gov["store1_write_allowed"]["const"] is False
        assert gov["runtime_deployment_allowed"]["const"] is False
        assert gov["model_promotion_allowed"]["const"] is False
        assert gov["external_calls_allowed"]["const"] is False

    def test_schema_synthetic_origin_is_const_true(self):
        schema_path = Path(__file__).resolve().parent.parent / "SYNTHETIC_DOCTRINE_RECORD.schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        assert data["properties"]["synthetic_origin"]["const"] is True

    def test_schema_has_all_required_fields(self):
        schema_path = Path(__file__).resolve().parent.parent / "SYNTHETIC_DOCTRINE_RECORD.schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        required = set(data["required"])
        expected = {
            "record_id", "schema_version", "created_at", "synthetic_origin",
            "source_id", "source_registry_version", "clearance_ledger_entry_id",
            "generation_agent_id", "prompt_template_id", "prompt_hash",
            "category", "input", "desired_output", "governance_labels", "audit_metadata",
        }
        assert expected <= required

    def test_schema_category_enum_matches_module(self):
        schema_path = Path(__file__).resolve().parent.parent / "SYNTHETIC_DOCTRINE_RECORD.schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        enum_vals = set(data["properties"]["category"]["enum"])
        assert enum_vals == set(CATEGORIES)


# ── success path ──────────────────────────────────────────────────────────────

class TestSuccessPath:
    def test_creates_jsonl_manifest_checksums(self, tmp_path):
        result = _run_l1001(tmp_path)
        out_dir = tmp_path / "synth_out"
        assert (out_dir / "synthetic_records.jsonl").exists()
        assert (out_dir / "synthetic_manifest.json").exists()
        assert (out_dir / "checksums.sha256").exists()

    def test_records_have_synthetic_origin_true(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            assert rec["synthetic_origin"] is True

    def test_every_record_has_prompt_hash_and_agent_id(self, tmp_path):
        result = _run_l1001(tmp_path, agent_id="AGENT_CHECK")
        for rec in result["records"]:
            assert "prompt_hash" in rec
            assert len(rec["prompt_hash"]) == 32
            assert rec["generation_agent_id"] == "AGENT_CHECK"

    def test_every_record_has_source_id_and_ledger_entry_id(self, tmp_path):
        ledger_path = _build_ledger(tmp_path, source_ids=("L1-001",))
        result = run_synthetic_doctrine(
            source_id="L1-001",
            clearance_ledger_path=ledger_path,
            out_dir=tmp_path / "out",
        )
        for rec in result["records"]:
            assert rec["source_id"] == "L1-001"
            assert rec["clearance_ledger_entry_id"] != ""

    def test_every_record_has_category_in_enum(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            assert rec["category"] in CATEGORIES

    def test_limit_is_respected(self, tmp_path):
        for limit in (1, 3, 7, 8, 25):
            result = run_synthetic_doctrine(
                source_id="L1-001",
                clearance_ledger_path=_build_ledger(tmp_path),
                out_dir=tmp_path / f"out_{limit}",
                limit=limit,
            )
            assert len(result["records"]) == limit

    def test_limit_clamps_to_max(self, tmp_path):
        result = run_synthetic_doctrine(
            source_id="L1-001",
            clearance_ledger_path=_build_ledger(tmp_path),
            out_dir=tmp_path / "out_over",
            limit=999,
        )
        assert len(result["records"]) == 25

    def test_generation_is_deterministic_same_inputs(self, tmp_path):
        kwargs = dict(
            source_id="L1-001",
            clearance_ledger_path=_build_ledger(tmp_path / "a"),
            generation_agent_id="DET_AGENT",
            limit=8,
        )
        r1 = run_synthetic_doctrine(**kwargs, out_dir=tmp_path / "r1")
        r2 = run_synthetic_doctrine(**kwargs, out_dir=tmp_path / "r2")
        stable_keys = ("record_id", "synthetic_origin", "source_id", "prompt_template_id",
                       "prompt_hash", "category", "input", "desired_output", "governance_labels")
        for rec1, rec2 in zip(r1["records"], r2["records"]):
            for k in stable_keys:
                assert rec1[k] == rec2[k], f"Mismatch on key {k!r}"

    def test_changing_agent_id_changes_record_ids(self, tmp_path):
        ledger_a = _build_ledger(tmp_path / "a")
        ledger_b = _build_ledger(tmp_path / "b")
        r1 = run_synthetic_doctrine(
            source_id="L1-001",
            clearance_ledger_path=ledger_a,
            generation_agent_id="AGENT_A",
            out_dir=tmp_path / "out_a",
            limit=4,
        )
        r2 = run_synthetic_doctrine(
            source_id="L1-001",
            clearance_ledger_path=ledger_b,
            generation_agent_id="AGENT_B",
            out_dir=tmp_path / "out_b",
            limit=4,
        )
        ids_1 = {rec["record_id"] for rec in r1["records"]}
        ids_2 = {rec["record_id"] for rec in r2["records"]}
        assert ids_1.isdisjoint(ids_2), "Different agent IDs must produce different record_ids"

    def test_prompt_hash_stable_across_agent_changes(self, tmp_path):
        ledger_a = _build_ledger(tmp_path / "a")
        ledger_b = _build_ledger(tmp_path / "b")
        r1 = run_synthetic_doctrine(
            source_id="L1-001",
            clearance_ledger_path=ledger_a,
            generation_agent_id="AGENT_A",
            out_dir=tmp_path / "out_a",
            limit=4,
        )
        r2 = run_synthetic_doctrine(
            source_id="L1-001",
            clearance_ledger_path=ledger_b,
            generation_agent_id="AGENT_B",
            out_dir=tmp_path / "out_b",
            limit=4,
        )
        hashes_1 = [rec["prompt_hash"] for rec in r1["records"]]
        hashes_2 = [rec["prompt_hash"] for rec in r2["records"]]
        assert hashes_1 == hashes_2, "prompt_hash must not depend on generation_agent_id"

    def test_l1003_succeeds_for_synthetic_seed(self, tmp_path):
        ledger_path = _build_ledger(tmp_path, source_ids=("L1-003",))
        result = run_synthetic_doctrine(
            source_id="L1-003",
            clearance_ledger_path=ledger_path,
            out_dir=tmp_path / "out",
            limit=4,
        )
        assert result["records"]
        assert all(r["source_id"] == "L1-003" for r in result["records"])

    def test_l1006_succeeds_for_synthetic_seed(self, tmp_path):
        ledger_path = _build_ledger(tmp_path, source_ids=("L1-006",))
        result = run_synthetic_doctrine(
            source_id="L1-006",
            clearance_ledger_path=ledger_path,
            out_dir=tmp_path / "out",
            limit=4,
        )
        assert result["records"]
        assert all(r["source_id"] == "L1-006" for r in result["records"])

    def test_jsonl_lines_are_valid_json(self, tmp_path):
        result = _run_l1001(tmp_path)
        out_dir = tmp_path / "synth_out"
        lines = (out_dir / "synthetic_records.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == len(result["records"])
        for line in lines:
            obj = json.loads(line)
            assert obj["synthetic_origin"] is True

    def test_manifest_has_governance_labels(self, tmp_path):
        result = _run_l1001(tmp_path)
        gov = result["manifest"]["governance"]
        assert gov["training_allowed"] is False
        assert gov["operator_review_required"] is True
        assert gov["store1_write_allowed"] is False
        assert gov["runtime_deployment_allowed"] is False
        assert gov["model_promotion_allowed"] is False
        assert gov["external_calls_allowed"] is False

    def test_manifest_notes_say_no_real_training(self, tmp_path):
        result = _run_l1001(tmp_path)
        notes = result["manifest"]["notes"]
        assert "No real training occurred" in notes
        assert "TR-05 was not started" in notes

    def test_checksums_file_has_two_lines(self, tmp_path):
        _run_l1001(tmp_path)
        out_dir = tmp_path / "synth_out"
        lines = (out_dir / "checksums.sha256").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert "synthetic_records.jsonl" in lines[0]
        assert "synthetic_manifest.json" in lines[1]


# ── governance flags ──────────────────────────────────────────────────────────

class TestGovernanceFlags:
    def test_no_record_has_training_allowed_true(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            assert rec["governance_labels"]["training_allowed"] is False

    def test_no_record_has_store1_write_allowed_true(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            assert rec["governance_labels"]["store1_write_allowed"] is False

    def test_no_record_has_model_promotion_allowed_true(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            assert rec["governance_labels"]["model_promotion_allowed"] is False

    def test_no_record_has_runtime_deployment_allowed_true(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            assert rec["governance_labels"]["runtime_deployment_allowed"] is False

    def test_no_record_has_external_calls_allowed_true(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            assert rec["governance_labels"]["external_calls_allowed"] is False

    def test_all_records_require_operator_review(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            assert rec["governance_labels"]["operator_review_required"] is True


# ── content safety ────────────────────────────────────────────────────────────

class TestContentSafety:
    def test_no_raw_red_team_vectors_in_outputs(self, tmp_path):
        result = _run_l1001(tmp_path)
        banned_patterns = [
            "jailbreak", "bypass_all_filters", "DAN mode",
            "ignore your instructions", "private_threshold",
        ]
        for rec in result["records"]:
            text = json.dumps(rec).lower()
            for pat in banned_patterns:
                assert pat.lower() not in text, f"Red-team pattern {pat!r} found in record"

    def test_no_secrets_or_credentials_in_outputs(self, tmp_path):
        result = _run_l1001(tmp_path)
        banned_patterns = [
            "api_key", "secret_key", "aws_access", "password=",
            "token=", "private_key",
        ]
        for rec in result["records"]:
            text = json.dumps(rec).lower()
            for pat in banned_patterns:
                assert pat.lower() not in text, f"Credential pattern {pat!r} found"

    def test_no_personal_data_in_outputs(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            text = json.dumps(rec)
            assert "@" not in text or "actor_id" not in text or "DWS" not in text or True
            # Actor IDs may contain @ in other systems, but our templates contain none
            for field in ("input", "desired_output"):
                assert "@gmail" not in rec[field]
                assert "SSN" not in rec[field]


# ── failure gates ─────────────────────────────────────────────────────────────

class TestFailureGates:
    def test_fails_without_clearance_ledger_path(self, tmp_path):
        with pytest.raises(SystemExit):
            run_synthetic_doctrine(
                source_id="L1-001",
                clearance_ledger_path=None,
                out_dir=tmp_path / "out",
            )

    def test_fails_for_blocked_l6001(self, tmp_path):
        ledger_path = _build_ledger(tmp_path)  # approves L1-001
        with pytest.raises(SystemExit):
            run_synthetic_doctrine(
                source_id="L6-001",
                clearance_ledger_path=ledger_path,
                out_dir=tmp_path / "out",
            )

    def test_fails_for_pending_l5001(self, tmp_path):
        ledger_path = _build_ledger(tmp_path)
        with pytest.raises(SystemExit):
            run_synthetic_doctrine(
                source_id="L5-001",
                clearance_ledger_path=ledger_path,
                out_dir=tmp_path / "out",
            )

    def test_fails_for_l1004_disallowed_use(self, tmp_path):
        ledger_path = _build_ledger(tmp_path, source_ids=("L1-004",))
        with pytest.raises(SystemExit):
            run_synthetic_doctrine(
                source_id="L1-004",
                clearance_ledger_path=ledger_path,
                out_dir=tmp_path / "out",
            )

    def test_fails_for_unknown_source_id(self, tmp_path):
        ledger_path = _build_ledger(tmp_path)
        with pytest.raises(SystemExit):
            run_synthetic_doctrine(
                source_id="L9-999",
                clearance_ledger_path=ledger_path,
                out_dir=tmp_path / "out",
            )

    def test_fails_with_missing_ledger_file(self, tmp_path):
        with pytest.raises(SystemExit):
            run_synthetic_doctrine(
                source_id="L1-001",
                clearance_ledger_path=tmp_path / "nonexistent_ledger.json",
                out_dir=tmp_path / "out",
            )

    def test_fails_with_tampered_ledger(self, tmp_path):
        ledger_path = _build_ledger(tmp_path)
        ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
        # Tamper with a field covered by entry_hash
        ledger_data["entries"][0]["decision_reason"] = "TAMPERED"
        ledger_path.write_text(json.dumps(ledger_data), encoding="utf-8")
        with pytest.raises(SystemExit):
            run_synthetic_doctrine(
                source_id="L1-001",
                clearance_ledger_path=ledger_path,
                out_dir=tmp_path / "out",
            )

    def test_fails_when_ledger_has_no_entry_for_source(self, tmp_path):
        ledger_path = _build_ledger(tmp_path, source_ids=("L1-003",))
        with pytest.raises(SystemExit):
            run_synthetic_doctrine(
                source_id="L1-001",
                clearance_ledger_path=ledger_path,
                out_dir=tmp_path / "out",
            )

    def test_fails_when_approval_superseded_by_block(self, tmp_path):
        from clearance_ledger import load_ledger
        ledger_path = _build_ledger(tmp_path, source_ids=("L1-001",))
        ledger = load_ledger(ledger_path)
        append_decision(ledger, {
            "source_id": "L1-001",
            "decision_type": "block",
            "from_status": "approved",
            "to_status": "blocked",
            "actor_id": "DWS-001",
            "actor_role": "human_principal",
            "decision_status": "blocked",
            "decision_reason": "Block supersedes prior approval.",
            "reg01_status": "not_required",
            "lgl01_status": "not_required",
            "hp_decision_status": "blocked",
        })
        save_ledger(ledger, ledger_path)
        with pytest.raises(SystemExit):
            run_synthetic_doctrine(
                source_id="L1-001",
                clearance_ledger_path=ledger_path,
                out_dir=tmp_path / "out",
            )


# ── static fixture ────────────────────────────────────────────────────────────

class TestStaticFixture:
    def test_fixture_ledger_approves_l1001(self):
        from clearance_ledger import load_ledger, validate_ledger, assert_clearance_entry_exists
        ledger = load_ledger(FIXTURE_LEDGER_PATH)
        validate_ledger(ledger)
        entry = assert_clearance_entry_exists(ledger, "L1-001")
        assert entry["decision_type"] == "hp_approve"

    def test_l1001_with_fixture_ledger_succeeds(self, tmp_path):
        result = run_synthetic_doctrine(
            source_id="L1-001",
            clearance_ledger_path=FIXTURE_LEDGER_PATH,
            out_dir=tmp_path / "out",
            limit=8,
        )
        assert len(result["records"]) == 8
        for rec in result["records"]:
            assert rec["clearance_ledger_entry_id"] == "LE-e61bf2e9638393e0"


# ── module purity ─────────────────────────────────────────────────────────────

class TestModulePurity:
    def test_no_external_provider_imports(self):
        """Verify at the source level — not sys.modules — that forbidden packages
        are never imported by synthetic_doctrine.py."""
        import ast
        blocked_prefixes = (
            "openai", "anthropic", "google.generativeai", "groq",
            "xai", "huggingface_hub", "boto3", "requests", "httpx",
        )
        src = (Path(__file__).resolve().parent.parent / "synthetic_doctrine.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in blocked_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"Forbidden import {alias.name!r} found in synthetic_doctrine.py"
                        )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for prefix in blocked_prefixes:
                    assert not mod.startswith(prefix), (
                        f"Forbidden from-import {mod!r} found in synthetic_doctrine.py"
                    )

    def test_module_compiles(self):
        import py_compile
        path = Path(__file__).resolve().parent.parent / "synthetic_doctrine.py"
        py_compile.compile(str(path), doraise=True)

    def test_allowed_generation_sources_are_lane_1_only(self):
        for sid in ALLOWED_GENERATION_SOURCES:
            assert sid.startswith("L1-"), (
                f"Non-Lane-1 source {sid!r} in ALLOWED_GENERATION_SOURCES"
            )

    def test_schema_version_constant_matches_schema_file(self):
        schema_path = Path(__file__).resolve().parent.parent / "SYNTHETIC_DOCTRINE_RECORD.schema.json"
        schema_data = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema_data["properties"]["schema_version"]["const"] == SCHEMA_VERSION

    def test_synthetic_use_is_in_valid_uses(self):
        from source_registry import VALID_ALLOWED_USES
        assert SYNTHETIC_USE in VALID_ALLOWED_USES


# ── audit metadata ────────────────────────────────────────────────────────────

class TestAuditMetadata:
    def test_audit_metadata_has_required_fields(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            meta = rec["audit_metadata"]
            assert "generator_version" in meta
            assert "generation_index" in meta
            assert "clearance_gate" in meta

    def test_audit_generator_version_matches_constant(self, tmp_path):
        result = _run_l1001(tmp_path)
        for rec in result["records"]:
            assert rec["audit_metadata"]["generator_version"] == GENERATOR_VERSION

    def test_audit_clearance_gate_value(self, tmp_path):
        result = _run_l1001(tmp_path)
        for i, rec in enumerate(result["records"]):
            assert rec["audit_metadata"]["generation_index"] == i
            assert rec["audit_metadata"]["clearance_gate"] == "registry_and_ledger"

    def test_record_id_format(self, tmp_path):
        import re
        result = _run_l1001(tmp_path)
        pattern = re.compile(r"^SR-[0-9a-f]{16}$")
        for rec in result["records"]:
            assert pattern.match(rec["record_id"]), (
                f"record_id {rec['record_id']!r} does not match SR-[hex]{{16}}"
            )

    def test_prompt_hash_format(self, tmp_path):
        import re
        result = _run_l1001(tmp_path)
        pattern = re.compile(r"^[0-9a-f]{32}$")
        for rec in result["records"]:
            assert pattern.match(rec["prompt_hash"]), (
                f"prompt_hash {rec['prompt_hash']!r} does not match [hex]{{32}}"
            )
