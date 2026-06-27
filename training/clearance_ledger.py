"""
LOGOS ASF — TR-04A.4 Source Clearance Ledger v1.0.0
LOGOS Governance Systems Inc.

Append-only, SHA-256 hash-chained ledger that records every clearance
decision (nomination, approval, rejection, block, archive) for training
data sources. Each entry covers all prior entries through a hash chain;
tampering with any entry or reordering entries fails validation.

Ed25519 signature fields are present as interfaces only.
Real signing is TR-04A.5. AWS/S3 Object Lock is future infrastructure.
clearance_ledger.py does NOT call source_registry.py at import time.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_VERSION = "1.0.0"
GENESIS_HASH = "0" * 64
HASH_ALGORITHM = "sha256"
DEFAULT_SIGNATURE_ALGORITHM = "ed25519_placeholder"

VALID_DECISION_TYPES = frozenset({
    "nominate", "reg01_clear", "reg01_reject",
    "lgl01_clear", "lgl01_reject", "ea00_batch",
    "hp_approve", "hp_reject", "block", "archive", "restore",
})
VALID_DECISION_STATUSES  = frozenset({"recorded", "accepted", "rejected", "blocked"})
VALID_SIGNATURE_STATUSES = frozenset({"unsigned_local", "signature_pending", "signed", "invalid"})
VALID_SIGNATURE_ALGORITHMS = frozenset({"ed25519_placeholder", "ed25519"})

REQUIRED_LEDGER_FIELDS = frozenset({
    "ledger_id", "version", "classification", "authority",
    "created_at", "hash_algorithm", "signature_algorithm", "entries",
})
REQUIRED_ENTRY_FIELDS = frozenset({
    "ledger_entry_id", "timestamp", "source_id", "decision_type",
    "from_status", "to_status", "requested_use", "actor_id", "actor_role",
    "decision_status", "decision_reason", "reg01_status", "lgl01_status",
    "hp_decision_status", "source_registry_version", "source_registry_entry_hash",
    "previous_entry_hash", "entry_hash", "signature_status", "signature_algorithm",
    "signature_public_key_id", "signature_value", "notes",
})

# Decision types that grant clearance
CLEARANCE_APPROVALS = frozenset({"hp_approve", "reg01_clear", "lgl01_clear", "ea00_batch"})
# Decision types that revoke clearance
CLEARANCE_BLOCKS = frozenset({"block", "hp_reject", "reg01_reject", "lgl01_reject", "archive"})


# ── exceptions ────────────────────────────────────────────────────────────────

class LedgerError(Exception):
    """Base class for all clearance ledger errors."""

class LedgerValidationError(LedgerError):
    """Raised when the ledger structure or hash chain fails validation."""

class LedgerClearanceError(LedgerError):
    """Raised when a required clearance entry is missing or superseded."""


# ── internal helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── hash chain ─────────────────────────────────────────────────────────────────

def hash_entry(entry: dict) -> str:
    """
    Compute SHA-256 over the canonical JSON representation of an entry,
    excluding entry_hash and signature_value (which depend on the hash itself).

    Key ordering is deterministic (sorted). No whitespace.
    """
    excluded = {"entry_hash", "signature_value"}
    canonical = {k: v for k, v in entry.items() if k not in excluded}
    serialized = json.dumps(canonical, sort_keys=True,
                             separators=(",", ":"), ensure_ascii=True)
    return _sha256_hex(serialized)


# ── ledger creation ────────────────────────────────────────────────────────────

def create_empty_ledger(authority: dict, ledger_id: str = None,
                        created_at: str = None) -> dict:
    """
    Create a new empty clearance ledger dict.

    authority must contain at least human_principal_id and display_name.
    ledger_id and created_at default to sensible values if not provided.
    """
    return {
        "ledger_id":          ledger_id or f"logos-clearance-ledger-{(_now_iso()[:10])}",
        "version":            LEDGER_VERSION,
        "classification":     "INTERNAL — CONSTITUTIONAL",
        "authority":          authority,
        "created_at":         created_at or _now_iso(),
        "hash_algorithm":     HASH_ALGORITHM,
        "signature_algorithm": DEFAULT_SIGNATURE_ALGORITHM,
        "entries":            [],
    }


# ── append decision ────────────────────────────────────────────────────────────

def append_decision(ledger: dict, decision: dict) -> dict:
    """
    Append a clearance decision to the ledger.

    Computes previous_entry_hash (genesis or prior entry_hash), sets
    signature placeholder fields, computes and stores entry_hash.

    Required keys in decision:
      source_id, decision_type, actor_id, actor_role

    Optional keys (with defaults):
      timestamp, from_status, to_status, requested_use,
      decision_status ("recorded"), decision_reason (""),
      reg01_status, lgl01_status, hp_decision_status,
      source_registry_version ("1.0.0"), source_registry_entry_hash (""),
      signature_status ("unsigned_local"),
      signature_algorithm ("ed25519_placeholder"),
      signature_public_key_id (None), signature_value (None), notes ("")

    Returns the completed entry dict.
    """
    entries = ledger.get("entries", [])
    previous_hash = entries[-1]["entry_hash"] if entries else GENESIS_HASH

    timestamp     = decision.get("timestamp") or _now_iso()
    source_id     = decision["source_id"]
    decision_type = decision["decision_type"]

    entry: dict = {
        "ledger_entry_id": _make_entry_id(timestamp, source_id, decision_type),
        "timestamp":           timestamp,
        "source_id":           source_id,
        "decision_type":       decision_type,
        "from_status":         decision.get("from_status"),
        "to_status":           decision.get("to_status"),
        "requested_use":       decision.get("requested_use"),
        "actor_id":            decision["actor_id"],
        "actor_role":          decision["actor_role"],
        "decision_status":     decision.get("decision_status", "recorded"),
        "decision_reason":     decision.get("decision_reason", ""),
        "reg01_status":        decision.get("reg01_status", "not_required"),
        "lgl01_status":        decision.get("lgl01_status", "not_required"),
        "hp_decision_status":  decision.get("hp_decision_status", "not_required"),
        "source_registry_version":    decision.get("source_registry_version", LEDGER_VERSION),
        "source_registry_entry_hash": decision.get("source_registry_entry_hash", ""),
        "previous_entry_hash": previous_hash,
        # Filled in below after hash computation
        "entry_hash":          "",
        "signature_status":    decision.get("signature_status", "unsigned_local"),
        "signature_algorithm": decision.get("signature_algorithm", DEFAULT_SIGNATURE_ALGORITHM),
        "signature_public_key_id": decision.get("signature_public_key_id"),
        "signature_value":         decision.get("signature_value"),
        "notes": decision.get("notes", ""),
    }

    entry["entry_hash"] = hash_entry(entry)

    ledger.setdefault("entries", []).append(entry)
    return entry


def _make_entry_id(timestamp: str, source_id: str, decision_type: str) -> str:
    raw = f"{timestamp}:{source_id}:{decision_type}"
    return "LE-" + _sha256_hex(raw)[:16]


# ── ledger I/O ─────────────────────────────────────────────────────────────────

def load_ledger(path) -> dict:
    """Load a ledger from a JSON file. Does not validate the chain."""
    p = Path(path)
    if not p.exists():
        raise LedgerValidationError(f"Ledger file not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LedgerValidationError(f"Ledger file is not valid JSON: {e}")


def save_ledger(ledger: dict, path) -> None:
    """Write ledger to a JSON file (pretty-printed, 2-space indent)."""
    Path(path).write_text(
        json.dumps(ledger, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


# ── validation ─────────────────────────────────────────────────────────────────

def validate_ledger(ledger: dict) -> dict:
    """
    Validate the structure and SHA-256 hash chain of the entire ledger.

    Checks:
      - Top-level required fields present
      - Each entry has all required fields
      - Controlled enum values are valid
      - previous_entry_hash matches prior entry_hash (or GENESIS_HASH for first)
      - entry_hash matches recomputed hash of entry content

    Stops and raises LedgerValidationError at the first failing entry,
    reporting the entry index, entry ID, and reason.

    Returns {"valid": True, "entry_count": N} on success.
    """
    # Top-level structure
    missing_top = sorted(f for f in REQUIRED_LEDGER_FIELDS if f not in ledger)
    if missing_top:
        raise LedgerValidationError(
            f"Ledger missing top-level fields: {missing_top}"
        )

    entries = ledger.get("entries", [])
    if not isinstance(entries, list):
        raise LedgerValidationError("ledger.entries must be an array")

    expected_prev = GENESIS_HASH

    for i, entry in enumerate(entries):
        eid = entry.get("ledger_entry_id", f"<entry[{i}]>")
        errors: list[str] = []

        # Required fields
        for field in sorted(REQUIRED_ENTRY_FIELDS):
            if field not in entry:
                errors.append(f"missing required field {field!r}")

        # Controlled enums
        dt = entry.get("decision_type")
        if dt is not None and dt not in VALID_DECISION_TYPES:
            errors.append(f"unknown decision_type {dt!r}")

        ds = entry.get("decision_status")
        if ds is not None and ds not in VALID_DECISION_STATUSES:
            errors.append(f"unknown decision_status {ds!r}")

        ss = entry.get("signature_status")
        if ss is not None and ss not in VALID_SIGNATURE_STATUSES:
            errors.append(f"unknown signature_status {ss!r}")

        sa = entry.get("signature_algorithm")
        if sa is not None and sa not in VALID_SIGNATURE_ALGORITHMS:
            errors.append(f"unknown signature_algorithm {sa!r}")

        # Hash chain: previous_entry_hash must equal expected
        actual_prev = entry.get("previous_entry_hash")
        if actual_prev != expected_prev:
            errors.append(
                f"previous_entry_hash mismatch "
                f"(expected {expected_prev[:16]}…, got {str(actual_prev)[:16]}…)"
            )

        # Entry content hash integrity
        stored_hash = entry.get("entry_hash", "")
        recomputed   = hash_entry(entry)
        if stored_hash != recomputed:
            errors.append(
                "entry_hash mismatch — entry content may have been tampered "
                f"(stored={stored_hash[:16]}…, recomputed={recomputed[:16]}…)"
            )

        if errors:
            raise LedgerValidationError(
                f"Ledger chain validation failed at entry {i} ({eid}):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        # Advance expected previous hash using stored_hash (not recomputed),
        # so that a tampered entry also corrupts the subsequent chain check.
        expected_prev = stored_hash

    return {"valid": True, "entry_count": len(entries)}


# ── query API ──────────────────────────────────────────────────────────────────

def find_entries_for_source(ledger: dict, source_id: str) -> list:
    """Return all ledger entries for source_id in chronological order."""
    return [e for e in ledger.get("entries", [])
            if e.get("source_id") == source_id]


def assert_clearance_entry_exists(ledger: dict, source_id: str,
                                   requested_use: str = None) -> dict:
    """
    Assert the ledger contains at least one approval-type decision for source_id
    that has not been subsequently superseded by a block/reject/archive decision.

    Returns the most recent valid approval entry on success.
    Raises LedgerClearanceError if no valid clearance exists.

    requested_use is informational (recorded in error messages); use-level
    scoping is enforced by the source registry, not the ledger.
    """
    source_entries = find_entries_for_source(ledger, source_id)

    if not source_entries:
        raise LedgerClearanceError(
            f"No ledger entries found for source {source_id!r}. "
            "A clearance decision must be recorded before use."
        )

    approvals = [
        e for e in source_entries
        if e.get("decision_type") in CLEARANCE_APPROVALS
        and e.get("decision_status") in {"recorded", "accepted"}
    ]

    if not approvals:
        decision_types_seen = [e.get("decision_type") for e in source_entries]
        raise LedgerClearanceError(
            f"No approval-type decision in ledger for source {source_id!r}. "
            f"Decisions present: {decision_types_seen}"
        )

    last_approval = approvals[-1]
    last_approval_ts = last_approval["timestamp"]

    # Check for a subsequent blocking decision that supersedes the approval
    superseding_block = None
    for e in reversed(source_entries):
        if e.get("decision_type") in CLEARANCE_BLOCKS:
            if e["timestamp"] >= last_approval_ts:
                superseding_block = e
            break

    if superseding_block:
        raise LedgerClearanceError(
            f"Source {source_id!r} approval is superseded by a later "
            f"decision_type={superseding_block['decision_type']!r} "
            f"at {superseding_block['timestamp']}. "
            "Re-clearance requires a new approval decision."
        )

    return last_approval


def summarize_ledger(ledger: dict) -> dict:
    """Return an audit-safe summary. No raw decision_reason or notes content."""
    entries = ledger.get("entries", [])

    by_type:   dict = {}
    by_source: dict = {}

    for e in entries:
        dt  = e.get("decision_type", "unknown")
        sid = e.get("source_id", "unknown")
        by_type[dt] = by_type.get(dt, 0) + 1
        by_source.setdefault(sid, []).append(dt)

    return {
        "ledger_id":    ledger.get("ledger_id"),
        "version":      ledger.get("version"),
        "created_at":   ledger.get("created_at"),
        "total_entries": len(entries),
        "by_decision_type": by_type,
        "sources_with_decisions": sorted(by_source.keys()),
        "source_decision_counts": {
            k: len(v) for k, v in sorted(by_source.items())
        },
    }
