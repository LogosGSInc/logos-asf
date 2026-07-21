"""
TR-04A.3 Training Source Registry Validator — Unit Tests
"""
import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from source_registry import (
    SourceRegistry,
    SourceNotFoundError,
    SourceNotAllowedError,
    SourceBlockedError,
    RegistryValidationError,
    validate_registry,
    get_source,
    list_sources,
    assert_source_allowed,
    build_registry_summary,
    VALID_ALLOWED_USES,
    PENDING_STATUSES,
)

SEED_PATH = Path(__file__).parent.parent / "source_registry_seed.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def _registry(path=None):
    return SourceRegistry(path or SEED_PATH).load()


def _seed():
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _patched_registry(tmp_path, override_entries=None, patch_entry=None,
                      patch_key=None, patch_value=None):
    """
    Write a modified seed to tmp_path and return a SourceRegistry pointing to it.
    override_entries replaces all entries.
    patch_entry + patch_key + patch_value modifies a single entry field.
    """
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if override_entries is not None:
        data["entries"] = override_entries
    if patch_entry is not None and patch_key is not None:
        for e in data["entries"]:
            if e["source_id"] == patch_entry:
                e[patch_key] = patch_value
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return SourceRegistry(p).load()


# ── seed loading ──────────────────────────────────────────────────────────────

def test_registry_seed_loads_successfully():
    reg = _registry()
    assert reg._data is not None


def test_registry_has_exactly_13_entries():
    reg = _registry()
    assert len(reg._entries) == 13


def test_source_ids_are_unique():
    seed = _seed()
    ids = [e["source_id"] for e in seed["entries"]]
    assert len(ids) == len(set(ids))


def test_approved_count_is_7():
    reg = _registry()
    approved = reg.list_sources(status="approved")
    assert len(approved) == 7


def test_pending_count_is_5():
    reg = _registry()
    pending = [e for e in reg._entries.values()
               if e.get("registry_status") in PENDING_STATUSES]
    assert len(pending) == 5


def test_blocked_count_is_1():
    reg = _registry()
    blocked = reg.list_sources(status="blocked")
    assert len(blocked) == 1


def test_l6_001_is_blocked():
    reg = _registry()
    e = reg.get_source("L6-001")
    assert e["registry_status"] == "blocked"


def test_l6_001_has_empty_allowed_uses():
    reg = _registry()
    e = reg.get_source("L6-001")
    assert e["allowed_uses"] == []


def test_l1_007_has_synthetic_origin_true():
    reg = _registry()
    e = reg.get_source("L1-007")
    assert e.get("synthetic_origin") is True


def test_lane_prefix_and_lane_number_match():
    reg = _registry()
    for sid, entry in reg._entries.items():
        lane = entry["lane"]
        assert sid.startswith(f"L{lane}-"), (
            f"{sid} does not match lane {lane}"
        )


# ── validate_registry ─────────────────────────────────────────────────────────

def test_validate_registry_passes_on_seed():
    result = validate_registry(SEED_PATH)
    assert result["valid"] is True
    assert result["entry_count"] == 13


def test_validate_registry_detects_duplicate_source_id(tmp_path):
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    # Duplicate the first entry
    seed["entries"].append(dict(seed["entries"][0]))
    p = tmp_path / "dup.json"
    p.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="duplicate"):
        validate_registry(p)


def test_validate_registry_detects_lane_prefix_mismatch(tmp_path):
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    # Make L1-001 claim lane=2 (mismatch)
    for e in seed["entries"]:
        if e["source_id"] == "L1-001":
            e["lane"] = 2
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="prefix"):
        validate_registry(p)


def test_validate_registry_detects_blocked_with_nonempty_uses(tmp_path):
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for e in seed["entries"]:
        if e["source_id"] == "L6-001":
            e["allowed_uses"] = ["rag"]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="allowed_uses"):
        validate_registry(p)


def test_validate_registry_detects_synthetic_without_flag(tmp_path):
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for e in seed["entries"]:
        if e["source_id"] == "L1-007":
            e["synthetic_origin"] = False
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="synthetic_origin"):
        validate_registry(p)


def test_validate_registry_detects_missing_top_level_field(tmp_path):
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    del seed["constitutional_constraint"]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="constitutional_constraint"):
        validate_registry(p)


def test_validate_registry_fails_on_approved_with_pending_clearance(tmp_path):
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for e in seed["entries"]:
        if e["source_id"] == "L1-001":
            e["lgl01_status"] = "pending"  # breaks clearance invariant
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="lgl01_status"):
        validate_registry(p)


# ── get_source ────────────────────────────────────────────────────────────────

def test_get_source_returns_entry():
    reg = _registry()
    e = reg.get_source("L1-001")
    assert e["source_id"] == "L1-001"
    assert e["source_name"] == "Buildspec Volumes I, II, III"


def test_get_source_raises_for_unknown_id():
    reg = _registry()
    with pytest.raises(SourceNotFoundError):
        reg.get_source("UNKNOWN-999")


# ── list_sources ──────────────────────────────────────────────────────────────

def test_list_sources_no_filter_returns_all():
    reg = _registry()
    assert len(reg.list_sources()) == 13


def test_list_sources_filter_by_status():
    reg = _registry()
    approved = reg.list_sources(status="approved")
    assert all(e["registry_status"] == "approved" for e in approved)


def test_list_sources_filter_by_lane():
    reg = _registry()
    lane1 = reg.list_sources(lane=1)
    assert all(e["lane"] == 1 for e in lane1)
    assert len(lane1) == 7  # L1-001 through L1-007


def test_list_sources_combined_filter():
    reg = _registry()
    lane1_approved = reg.list_sources(status="approved", lane=1)
    assert len(lane1_approved) == 7


# ── assert_source_allowed — approved paths ─────────────────────────────────────

def test_approved_l1_001_permits_sft_candidate():
    result = assert_source_allowed("L1-001", "sft_candidate", SEED_PATH)
    assert result["cleared"] is True
    assert result["source_id"] == "L1-001"
    assert result["requested_use"] == "sft_candidate"


def test_approved_l1_001_permits_rag():
    result = assert_source_allowed("L1-001", "rag", SEED_PATH)
    assert result["cleared"] is True


def test_approved_l1_001_permits_pretraining_candidate():
    result = assert_source_allowed("L1-001", "pretraining_candidate", SEED_PATH)
    assert result["cleared"] is True


def test_approved_l1_007_permits_sft_candidate():
    result = assert_source_allowed("L1-007", "sft_candidate", SEED_PATH)
    assert result["cleared"] is True


# ── assert_source_allowed — blocked paths ─────────────────────────────────────

def test_approved_l1_004_rejects_sft_candidate():
    # L1-004 only allows rag and evaluation_reference
    with pytest.raises(SourceNotAllowedError, match="sft_candidate"):
        assert_source_allowed("L1-004", "sft_candidate", SEED_PATH)


def test_blocked_l6_001_rejects_all_uses():
    for use in VALID_ALLOWED_USES:
        with pytest.raises(SourceBlockedError, match="BLOCKED"):
            assert_source_allowed("L6-001", use, SEED_PATH)


def test_pending_l5_001_rejects_sft_candidate():
    with pytest.raises(SourceNotAllowedError, match="registry_status"):
        assert_source_allowed("L5-001", "sft_candidate", SEED_PATH)


def test_pending_l7_001_rejects_sft_candidate():
    with pytest.raises(SourceNotAllowedError, match="registry_status"):
        assert_source_allowed("L7-001", "sft_candidate", SEED_PATH)


def test_pending_l2_001_rejects_sft_candidate():
    with pytest.raises(SourceNotAllowedError):
        assert_source_allowed("L2-001", "sft_candidate", SEED_PATH)


def test_unknown_source_id_rejects():
    with pytest.raises(SourceNotFoundError):
        assert_source_allowed("L9-999", "sft_candidate", SEED_PATH)


def test_undefined_requested_use_rejects():
    with pytest.raises(SourceNotAllowedError, match="not a recognized use"):
        assert_source_allowed("L1-001", "undefined_use", SEED_PATH)


def test_empty_sha256_manifest_rejects(tmp_path):
    reg = _patched_registry(tmp_path, patch_entry="L1-001",
                             patch_key="sha256_manifest", patch_value="")
    with pytest.raises(SourceNotAllowedError, match="sha256_manifest"):
        reg.assert_source_allowed("L1-001", "sft_candidate")


def test_approved_source_with_missing_hp_timestamp_rejects(tmp_path):
    # hp_decision_status=approved but hp_decision_timestamp=null
    reg = _patched_registry(tmp_path, patch_entry="L1-001",
                             patch_key="hp_decision_timestamp", patch_value=None)
    with pytest.raises(SourceNotAllowedError, match="hp_decision_timestamp"):
        reg.assert_source_allowed("L1-001", "sft_candidate")


def test_approved_source_with_non_approved_hp_status_rejects(tmp_path):
    reg = _patched_registry(tmp_path, patch_entry="L1-001",
                             patch_key="hp_decision_status", patch_value="pending")
    with pytest.raises(SourceNotAllowedError, match="hp_decision_status"):
        reg.assert_source_allowed("L1-001", "sft_candidate")


def test_rejected_status_rejects():
    reg = _registry()
    # Synthesize a fake entry with rejected status in memory
    entry = dict(reg.get_source("L1-001"))
    entry["registry_status"] = "rejected"
    reg._entries["L1-001-REJECTED"] = entry
    entry["source_id"] = "L1-001-REJECTED"
    with pytest.raises(SourceBlockedError):
        reg.assert_source_allowed("L1-001-REJECTED", "sft_candidate")


def test_archived_status_rejects():
    reg = _registry()
    entry = dict(reg.get_source("L1-001"))
    entry["registry_status"] = "archived"
    entry["source_id"] = "L1-001-ARCHIVED"
    reg._entries["L1-001-ARCHIVED"] = entry
    with pytest.raises(SourceBlockedError):
        reg.assert_source_allowed("L1-001-ARCHIVED", "sft_candidate")


# ── build_registry_summary ────────────────────────────────────────────────────

def test_build_registry_summary_returns_correct_counts():
    summary = build_registry_summary(SEED_PATH)
    assert summary["total_entries"] == 13
    assert summary["approved_count"] == 7
    assert summary["pending_count"] == 5
    assert summary["blocked_count"] == 1


def test_build_registry_summary_has_no_raw_source_content():
    summary = build_registry_summary(SEED_PATH)
    summary_text = json.dumps(summary)
    assert "license_evidence_uri" not in summary_text
    assert "govmem_namespace" not in summary_text
    assert "PENDING_SOURCE_MANIFEST" not in summary_text


# ── registry not found ────────────────────────────────────────────────────────

def test_missing_registry_file_raises(tmp_path):
    with pytest.raises(RegistryValidationError, match="not found"):
        SourceRegistry(tmp_path / "nonexistent.json").load()


def test_invalid_json_registry_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not valid json }", encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="not valid JSON"):
        SourceRegistry(p).load()
