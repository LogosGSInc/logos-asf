"""
TR-04A.4 Source Clearance Ledger — Unit Tests
"""
import copy
import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clearance_ledger import (
    GENESIS_HASH,
    CLEARANCE_APPROVALS,
    CLEARANCE_BLOCKS,
    LedgerClearanceError,
    LedgerValidationError,
    append_decision,
    assert_clearance_entry_exists,
    create_empty_ledger,
    find_entries_for_source,
    hash_entry,
    load_ledger,
    save_ledger,
    summarize_ledger,
    validate_ledger,
)
from source_registry import (
    SourceNotAllowedError,
    assert_source_allowed_with_ledger,
)

SEED_PATH = Path(__file__).parent.parent / "source_registry_seed.json"

# Standard test authority
_AUTHORITY = {
    "human_principal_id": "DWS-001",
    "display_name": "David Warren Smith Jr.",
    "short_code": "DJ",
    "signature_mark": "/D.W.Smith/",
}

# Fixed timestamps so determinism is guaranteed in tests
_TS1 = "2026-06-26T10:00:00Z"
_TS2 = "2026-06-26T11:00:00Z"
_TS3 = "2026-06-26T12:00:00Z"


# ── helpers ───────────────────────────────────────────────────────────────────

def _new_ledger():
    return create_empty_ledger(_AUTHORITY, ledger_id="test-ledger-001",
                               created_at=_TS1)


def _hp_approve(source_id="L1-001", timestamp=_TS1, **kw):
    return {
        "source_id":     source_id,
        "decision_type": "hp_approve",
        "from_status":   "hp_pending",
        "to_status":     "approved",
        "actor_id":      "DWS-001",
        "actor_role":    "human_principal",
        "decision_status": "recorded",
        "decision_reason": "HP approved for sft_candidate use.",
        "hp_decision_status": "approved",
        "timestamp": timestamp,
        **kw,
    }


def _nominate(source_id="L1-001", timestamp=_TS1, **kw):
    return {
        "source_id":     source_id,
        "decision_type": "nominate",
        "from_status":   None,
        "to_status":     "draft",
        "actor_id":      "REG-01",
        "actor_role":    "registry_operator",
        "decision_status": "recorded",
        "decision_reason": "Nomination submitted.",
        "timestamp": timestamp,
        **kw,
    }


def _block(source_id="L1-001", timestamp=_TS2, **kw):
    return {
        "source_id":     source_id,
        "decision_type": "block",
        "from_status":   "approved",
        "to_status":     "blocked",
        "actor_id":      "DWS-001",
        "actor_role":    "human_principal",
        "decision_status": "blocked",
        "decision_reason": "Source blocked due to new legal requirement.",
        "timestamp": timestamp,
        **kw,
    }


# ── create_empty_ledger ───────────────────────────────────────────────────────

def test_create_empty_ledger_structure():
    ledger = _new_ledger()
    assert ledger["version"] == "1.0.0"
    assert ledger["ledger_id"] == "test-ledger-001"
    assert ledger["hash_algorithm"] == "sha256"
    assert ledger["entries"] == []
    assert ledger["authority"]["human_principal_id"] == "DWS-001"


def test_create_empty_ledger_default_id():
    ledger = create_empty_ledger(_AUTHORITY)
    assert ledger["ledger_id"].startswith("logos-clearance-ledger-")


# ── validate_ledger — empty ───────────────────────────────────────────────────

def test_validate_empty_ledger_passes():
    ledger = _new_ledger()
    result = validate_ledger(ledger)
    assert result["valid"] is True
    assert result["entry_count"] == 0


def test_validate_ledger_missing_top_level_field():
    ledger = _new_ledger()
    del ledger["hash_algorithm"]
    with pytest.raises(LedgerValidationError, match="hash_algorithm"):
        validate_ledger(ledger)


# ── append_decision ───────────────────────────────────────────────────────────

def test_append_first_decision_genesis_hash():
    ledger = _new_ledger()
    entry = append_decision(ledger, _hp_approve())
    assert entry["previous_entry_hash"] == GENESIS_HASH
    assert len(ledger["entries"]) == 1


def test_append_first_decision_entry_hash_is_hex64():
    ledger = _new_ledger()
    entry = append_decision(ledger, _hp_approve())
    h = entry["entry_hash"]
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_append_multiple_decisions_chain():
    ledger = _new_ledger()
    e1 = append_decision(ledger, _nominate(timestamp=_TS1))
    e2 = append_decision(ledger, _hp_approve(timestamp=_TS2))
    assert e2["previous_entry_hash"] == e1["entry_hash"]
    assert len(ledger["entries"]) == 2


def test_append_three_decisions_full_chain():
    ledger = _new_ledger()
    e1 = append_decision(ledger, _nominate(timestamp=_TS1))
    e2 = append_decision(ledger, _hp_approve(timestamp=_TS2))
    e3 = append_decision(ledger, _block(timestamp=_TS3))
    assert e2["previous_entry_hash"] == e1["entry_hash"]
    assert e3["previous_entry_hash"] == e2["entry_hash"]


def test_append_decision_entry_id_format():
    ledger = _new_ledger()
    entry = append_decision(ledger, _hp_approve())
    eid = entry["ledger_entry_id"]
    assert eid.startswith("LE-")
    assert len(eid) == 19  # "LE-" + 16 hex


def test_append_decision_default_signature_fields():
    ledger = _new_ledger()
    entry = append_decision(ledger, _hp_approve())
    assert entry["signature_status"] == "unsigned_local"
    assert entry["signature_algorithm"] == "ed25519_placeholder"
    assert entry["signature_public_key_id"] is None
    assert entry["signature_value"] is None


# ── validate_ledger — valid chain ─────────────────────────────────────────────

def test_validate_single_entry_passes():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(timestamp=_TS1))
    result = validate_ledger(ledger)
    assert result["valid"] is True
    assert result["entry_count"] == 1


def test_validate_multi_entry_chain_passes():
    ledger = _new_ledger()
    append_decision(ledger, _nominate(timestamp=_TS1))
    append_decision(ledger, _hp_approve(timestamp=_TS2))
    append_decision(ledger, _block(timestamp=_TS3))
    result = validate_ledger(ledger)
    assert result["valid"] is True
    assert result["entry_count"] == 3


# ── tamper detection ──────────────────────────────────────────────────────────

def test_tamper_decision_reason_fails_validation():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(timestamp=_TS1))
    # Mutate decision_reason after the fact
    ledger["entries"][0]["decision_reason"] = "TAMPERED"
    with pytest.raises(LedgerValidationError, match="entry_hash mismatch"):
        validate_ledger(ledger)


def test_tamper_actor_id_fails_validation():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(timestamp=_TS1))
    ledger["entries"][0]["actor_id"] = "ATTACKER"
    with pytest.raises(LedgerValidationError, match="entry_hash mismatch"):
        validate_ledger(ledger)


def test_tamper_previous_entry_hash_fails_validation():
    ledger = _new_ledger()
    append_decision(ledger, _nominate(timestamp=_TS1))
    append_decision(ledger, _hp_approve(timestamp=_TS2))
    # Replace second entry's previous_entry_hash with garbage
    ledger["entries"][1]["previous_entry_hash"] = "a" * 64
    # previous_entry_hash is covered by entry_hash computation, so both checks fire
    with pytest.raises(LedgerValidationError):
        validate_ledger(ledger)


def test_tamper_from_status_on_first_entry_fails():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(timestamp=_TS1))
    ledger["entries"][0]["from_status"] = "INJECTED"
    with pytest.raises(LedgerValidationError, match="entry_hash mismatch"):
        validate_ledger(ledger)


def test_reorder_entries_fails_validation():
    ledger = _new_ledger()
    append_decision(ledger, _nominate(source_id="L1-001", timestamp=_TS1))
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS2))
    append_decision(ledger, _block(source_id="L1-001", timestamp=_TS3))
    # Swap second and third entries
    entries = ledger["entries"]
    entries[1], entries[2] = entries[2], entries[1]
    with pytest.raises(LedgerValidationError):
        validate_ledger(ledger)


def test_missing_required_field_fails_validation():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(timestamp=_TS1))
    # Remove a required field from the stored entry
    del ledger["entries"][0]["actor_role"]
    # entry_hash now won't match (field was included in hash) AND field is missing
    with pytest.raises(LedgerValidationError):
        validate_ledger(ledger)


# ── enum validation ───────────────────────────────────────────────────────────

def test_unknown_decision_type_fails_validation():
    ledger = _new_ledger()
    entry = append_decision(ledger, _hp_approve(timestamp=_TS1))
    # Patch in-place: also update entry_hash so structural check passes,
    # but enum check fires first
    ledger["entries"][0]["decision_type"] = "fabricated_approval"
    # We must recompute entry_hash for it to pass hash check but fail enum check
    ledger["entries"][0]["entry_hash"] = hash_entry(ledger["entries"][0])
    with pytest.raises(LedgerValidationError, match="decision_type"):
        validate_ledger(ledger)


def test_unknown_signature_status_fails_validation():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(timestamp=_TS1))
    # Patch and recompute hash so only enum check fires
    ledger["entries"][0]["signature_status"] = "super_signed"
    ledger["entries"][0]["entry_hash"] = hash_entry(ledger["entries"][0])
    with pytest.raises(LedgerValidationError, match="signature_status"):
        validate_ledger(ledger)


def test_unsigned_local_entries_are_valid():
    ledger = _new_ledger()
    d = _hp_approve(timestamp=_TS1)
    d["signature_status"] = "unsigned_local"
    d["signature_algorithm"] = "ed25519_placeholder"
    append_decision(ledger, d)
    result = validate_ledger(ledger)
    assert result["valid"] is True


# ── hash_entry ────────────────────────────────────────────────────────────────

def test_hash_entry_excludes_entry_hash_field():
    ledger = _new_ledger()
    entry = append_decision(ledger, _hp_approve(timestamp=_TS1))
    # Changing entry_hash in the stored copy should not affect re-hash result
    modified = dict(entry)
    modified["entry_hash"] = "0" * 64
    assert hash_entry(modified) == hash_entry(entry)


def test_hash_entry_excludes_signature_value():
    ledger = _new_ledger()
    entry = append_decision(ledger, _hp_approve(timestamp=_TS1))
    modified = dict(entry)
    modified["signature_value"] = "fake_sig_base64"
    assert hash_entry(modified) == hash_entry(entry)


def test_hash_entry_is_deterministic():
    ledger = _new_ledger()
    entry = append_decision(ledger, _hp_approve(timestamp=_TS1))
    h1 = hash_entry(entry)
    h2 = hash_entry(dict(entry))
    assert h1 == h2


def test_hash_entry_changes_with_any_field():
    ledger = _new_ledger()
    entry = append_decision(ledger, _hp_approve(timestamp=_TS1))
    orig_hash = hash_entry(entry)
    modified = dict(entry)
    modified["notes"] = "DIFFERENT"
    assert hash_entry(modified) != orig_hash


# ── load / save ───────────────────────────────────────────────────────────────

def test_save_and_load_roundtrip(tmp_path):
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(timestamp=_TS1))
    path = tmp_path / "ledger.json"
    save_ledger(ledger, path)
    loaded = load_ledger(path)
    assert loaded["ledger_id"] == ledger["ledger_id"]
    assert len(loaded["entries"]) == 1


def test_load_validates_chain_after_roundtrip(tmp_path):
    ledger = _new_ledger()
    append_decision(ledger, _nominate(timestamp=_TS1))
    append_decision(ledger, _hp_approve(timestamp=_TS2))
    path = tmp_path / "ledger.json"
    save_ledger(ledger, path)
    loaded = load_ledger(path)
    result = validate_ledger(loaded)
    assert result["valid"] is True


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(LedgerValidationError, match="not found"):
        load_ledger(tmp_path / "nonexistent.json")


def test_load_invalid_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json }", encoding="utf-8")
    with pytest.raises(LedgerValidationError, match="not valid JSON"):
        load_ledger(p)


# ── find_entries_for_source ───────────────────────────────────────────────────

def test_find_entries_for_source_returns_matching():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS1))
    append_decision(ledger, _hp_approve(source_id="L2-001", timestamp=_TS2))
    append_decision(ledger, _block(source_id="L1-001", timestamp=_TS3))
    entries = find_entries_for_source(ledger, "L1-001")
    assert len(entries) == 2
    assert all(e["source_id"] == "L1-001" for e in entries)


def test_find_entries_for_source_empty_when_none():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS1))
    assert find_entries_for_source(ledger, "L9-999") == []


# ── assert_clearance_entry_exists ─────────────────────────────────────────────

def test_assert_clearance_exists_for_approved_source():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS1))
    entry = assert_clearance_entry_exists(ledger, "L1-001")
    assert entry["decision_type"] == "hp_approve"
    assert entry["source_id"] == "L1-001"


def test_assert_clearance_missing_raises():
    ledger = _new_ledger()
    with pytest.raises(LedgerClearanceError, match="No ledger entries"):
        assert_clearance_entry_exists(ledger, "L1-001")


def test_assert_clearance_nominate_only_raises():
    ledger = _new_ledger()
    append_decision(ledger, _nominate(source_id="L1-001", timestamp=_TS1))
    with pytest.raises(LedgerClearanceError, match="No approval-type decision"):
        assert_clearance_entry_exists(ledger, "L1-001")


def test_block_after_approval_supersedes():
    """Block decision recorded after approval denies clearance."""
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS1))
    append_decision(ledger, _block(source_id="L1-001", timestamp=_TS2))
    with pytest.raises(LedgerClearanceError, match="superseded"):
        assert_clearance_entry_exists(ledger, "L1-001")


def test_block_before_approval_does_not_supersede():
    """Block at T1, new approval at T2 — approval wins."""
    ledger = _new_ledger()
    append_decision(ledger, _block(source_id="L1-001", timestamp=_TS1))
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS2))
    entry = assert_clearance_entry_exists(ledger, "L1-001")
    assert entry["decision_type"] == "hp_approve"


def test_block_recorded_does_not_authorize_use():
    """A block entry alone never satisfies clearance check."""
    ledger = _new_ledger()
    append_decision(ledger, _block(source_id="L6-001", timestamp=_TS1,
                                   decision_status="blocked"))
    with pytest.raises(LedgerClearanceError):
        assert_clearance_entry_exists(ledger, "L6-001")


def test_assert_clearance_with_requested_use_in_error_message():
    ledger = _new_ledger()
    with pytest.raises(LedgerClearanceError):
        assert_clearance_entry_exists(ledger, "L1-001", "sft_candidate")


# ── summarize_ledger ──────────────────────────────────────────────────────────

def test_summarize_ledger_correct_counts():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS1))
    append_decision(ledger, _hp_approve(source_id="L1-002", timestamp=_TS2))
    append_decision(ledger, _block(source_id="L1-001", timestamp=_TS3))
    summary = summarize_ledger(ledger)
    assert summary["total_entries"] == 3
    assert summary["by_decision_type"]["hp_approve"] == 2
    assert summary["by_decision_type"]["block"] == 1
    assert sorted(summary["sources_with_decisions"]) == ["L1-001", "L1-002"]


def test_summarize_ledger_excludes_raw_content():
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(
        decision_reason="Top secret internal rationale", timestamp=_TS1
    ))
    summary_text = json.dumps(summarize_ledger(ledger))
    assert "Top secret internal rationale" not in summary_text
    assert "decision_reason" not in summary_text


# ── source_registry bridge ────────────────────────────────────────────────────

def test_registry_with_ledger_no_ledger_path_uses_registry_only():
    """Without ledger_path, assert_source_allowed_with_ledger == assert_source_allowed."""
    result = assert_source_allowed_with_ledger(
        "L1-001", "sft_candidate", SEED_PATH, ledger_path=None
    )
    assert result["cleared"] is True
    assert "ledger_cleared" not in result


def test_registry_with_ledger_succeeds_when_ledger_has_approval(tmp_path):
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS1))
    path = tmp_path / "ledger.json"
    save_ledger(ledger, path)

    result = assert_source_allowed_with_ledger(
        "L1-001", "sft_candidate", SEED_PATH, ledger_path=path
    )
    assert result["cleared"] is True
    assert result["ledger_cleared"] is True
    assert result["ledger_entry_id"].startswith("LE-")


def test_registry_with_ledger_fails_when_no_ledger_entry(tmp_path):
    """Ledger exists but has no entry for L1-001 → SourceNotAllowedError."""
    ledger = _new_ledger()
    # Add entry for a DIFFERENT source so ledger is non-empty
    append_decision(ledger, _hp_approve(source_id="L1-002", timestamp=_TS1))
    path = tmp_path / "ledger.json"
    save_ledger(ledger, path)

    with pytest.raises(SourceNotAllowedError, match="Ledger clearance check failed"):
        assert_source_allowed_with_ledger(
            "L1-001", "sft_candidate", SEED_PATH, ledger_path=path
        )


def test_registry_with_ledger_fails_when_ledger_entry_is_block(tmp_path):
    """hp_approve followed by block → ledger gate fails."""
    ledger = _new_ledger()
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS1))
    append_decision(ledger, _block(source_id="L1-001", timestamp=_TS2))
    path = tmp_path / "ledger.json"
    save_ledger(ledger, path)

    with pytest.raises(SourceNotAllowedError, match="Ledger clearance check failed"):
        assert_source_allowed_with_ledger(
            "L1-001", "sft_candidate", SEED_PATH, ledger_path=path
        )


def test_registry_gate_still_blocks_even_with_valid_ledger(tmp_path):
    """Registry-blocked L6-001 fails at registry gate regardless of ledger."""
    ledger = _new_ledger()
    # Give L6-001 an hp_approve in the ledger (hypothetically)
    append_decision(ledger, _hp_approve(source_id="L6-001", timestamp=_TS1))
    path = tmp_path / "ledger.json"
    save_ledger(ledger, path)

    # Registry gate fires first — L6-001 is blocked in the registry
    from source_registry import SourceBlockedError
    with pytest.raises(SourceBlockedError):
        assert_source_allowed_with_ledger(
            "L6-001", "sft_candidate", SEED_PATH, ledger_path=path
        )


def test_registry_with_tampered_ledger_fails(tmp_path):
    """A tampered ledger (invalid chain) raises SourceNotAllowedError via ledger gate."""
    ledger = _new_ledger()
    append_decision(ledger, _nominate(source_id="L1-001", timestamp=_TS1))
    append_decision(ledger, _hp_approve(source_id="L1-001", timestamp=_TS2))
    # Tamper the first entry
    ledger["entries"][0]["decision_reason"] = "TAMPERED"
    path = tmp_path / "ledger.json"
    save_ledger(ledger, path)

    with pytest.raises(SourceNotAllowedError, match="Ledger clearance check failed"):
        assert_source_allowed_with_ledger(
            "L1-001", "sft_candidate", SEED_PATH, ledger_path=path
        )
