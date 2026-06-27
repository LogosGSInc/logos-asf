"""
LOGOS ASF — TR-04C Synthetic Output Review Bridge v1.0.0
LOGOS Governance Systems Inc.

Converts synthetic_doctrine.py output (synthetic_records.jsonl + manifest +
checksums) into operator-reviewable training candidates compatible with the
TR-02 review queue and the TR-03/TR-04 dataset pipeline.

Synthetic records are NOT training data. They become review candidates only.
Every candidate requires explicit operator approval before any dataset inclusion.

Hard invariants:
  - Verifies SHA-256 checksums before reading any record.
  - Rejects any record missing synthetic_origin=true.
  - Rejects any record missing prompt_hash, generation_agent_id,
    source_id, or clearance_ledger_entry_id.
  - Fails closed if governance_labels.training_allowed=true (security violation).
  - Fails closed if any record fails validation — no partial output.
  - Every candidate carries training_allowed=False and operator_review_required=True.
  - Audit record excludes raw input/desired_output text.
  - No real training. No model weights. No Store 1 writes. TR-05 not started.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BRIDGE_VERSION = "synthetic_review_bridge:1.0.0"
SCHEMA_VERSION = "1.0.0"
CANDIDATE_LANE = "training_candidate"

_REPO_ROOT = Path(__file__).resolve().parent.parent

_REQUIRED_FILES = ("synthetic_records.jsonl", "synthetic_manifest.json", "checksums.sha256")

# Governance flags that must be False in every record's governance_labels.
# Any True value is a security violation → immediate hard stop.
_MUST_BE_FALSE_FLAGS = (
    "training_allowed",
    "store1_write_allowed",
    "runtime_deployment_allowed",
    "model_promotion_allowed",
    "external_calls_allowed",
)

# Provenance fields that must be non-empty in every record.
_REQUIRED_PROVENANCE = (
    "prompt_hash",
    "generation_agent_id",
    "source_id",
    "clearance_ledger_entry_id",
)

_GOVERNANCE_LABELS = {
    "training_allowed": False,
    "operator_review_required": True,
    "store1_write_allowed": False,
    "runtime_deployment_allowed": False,
    "model_promotion_allowed": False,
    "external_calls_allowed": False,
}


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fail(msg: str) -> None:
    print(f"BRIDGE_HARD_STOP: {msg}", file=sys.stderr)
    sys.exit(1)


def _candidate_id(record_id: str, created_at: str) -> str:
    """
    Deterministic candidate ID derived from the record's own record_id.
    Uses the record's created_at for the date prefix.
    Stable across bridge re-runs on the same synthetic JSONL.
    """
    sha = hashlib.sha256(f"synthetic:{record_id}".encode()).hexdigest()[:8]
    m = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", created_at or "")
    date = (m.group(1) + m.group(2) + m.group(3)) if m else "00000000"
    return f"TC-{date}-{sha}"


def _verify_checksums(synthetic_dir: Path) -> None:
    """Verify SHA-256 checksums. Fails hard on any mismatch or missing file."""
    checksums_path = synthetic_dir / "checksums.sha256"
    for line in checksums_path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            _fail(f"Malformed checksums.sha256 entry: {line!r}")
        expected_sha, filename = parts[0], parts[1].strip()
        file_path = synthetic_dir / filename
        if not file_path.exists():
            _fail(f"File listed in checksums.sha256 not found: {filename!r}")
        actual_sha = _sha256_hex(file_path.read_bytes())
        if actual_sha != expected_sha:
            _fail(
                f"Checksum mismatch for {filename!r}: "
                f"expected {expected_sha[:16]}…, got {actual_sha[:16]}…"
            )


def _validate_record(rec: dict, index: int) -> str | None:
    """
    Validate a single synthetic record.

    Returns None if valid.
    Returns a rejection_reason string for structural failures.
    Calls _fail (sys.exit) immediately for security violations.
    """
    gov = rec.get("governance_labels")
    if not isinstance(gov, dict):
        return "missing_governance_labels"

    # Security violations: any True flag → immediate hard stop
    for flag in _MUST_BE_FALSE_FLAGS:
        if gov.get(flag) is True:
            _fail(
                f"SECURITY_VIOLATION in record[{index}] "
                f"(id={rec.get('record_id', '?')}): "
                f"governance_labels.{flag}=true"
            )

    # Structural requirements
    if rec.get("synthetic_origin") is not True:
        return "synthetic_origin_missing_or_false"
    for field in _REQUIRED_PROVENANCE:
        if not rec.get(field):
            return f"missing_{field}"

    return None


def _to_candidate(rec: dict, operator_id: str, bridge_run_at: str) -> dict:
    """Convert a validated synthetic record to a review candidate."""
    record_sha = _sha256_hex(
        json.dumps(rec, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    )
    return {
        "candidate_id":   _candidate_id(rec["record_id"], rec.get("created_at", "")),
        "schema_version": SCHEMA_VERSION,
        "candidate_lane": CANDIDATE_LANE,
        "source_provenance": "synthetic_doctrine",

        # Synthetic provenance — fully preserved, never dropped
        "synthetic_origin":             True,
        "synthetic_record_id":          rec["record_id"],
        "source_id":                    rec["source_id"],
        "source_registry_version":      rec.get("source_registry_version", ""),
        "clearance_ledger_entry_id":    rec["clearance_ledger_entry_id"],
        "generation_agent_id":          rec["generation_agent_id"],
        "prompt_template_id":           rec.get("prompt_template_id", ""),
        "prompt_hash":                  rec["prompt_hash"],
        "category":                     rec.get("category", ""),

        # Candidate content
        "task_type":       "synthetic_doctrine_example",
        "title":           f"Synthetic doctrine candidate: {rec.get('category', 'unknown')}",
        "summary": (
            f"Synthetic instruction example from approved doctrine source "
            f"{rec.get('source_id', '?')} via template "
            f"{rec.get('prompt_template_id', '?')}. "
            f"Operator review required before any dataset inclusion."
        ),
        "input":          rec.get("input", ""),
        "desired_output": rec.get("desired_output", ""),
        "source_hashes": [{
            "synthetic_record_id": rec["record_id"],
            "sha256":              record_sha,
        }],

        # Hard invariants — deny-by-default, enforced at code and audit level
        "operator_review_required":    True,
        "promotion_status":            "candidate_only",
        "training_allowed":            False,
        "store1_write_allowed":        False,
        "runtime_deployment_allowed":  False,
        "model_promotion_allowed":     False,
        "external_calls_allowed":      False,

        "created_at":     bridge_run_at,
        "bridge_version": BRIDGE_VERSION,
        "operator_id":    operator_id,
    }


def run_bridge(
    synthetic_dir,
    out_dir,
    operator_id: str = "BRIDGE_OPERATOR",
) -> dict:
    """
    Convert synthetic_doctrine.py output into operator-review candidates.

    Returns {"candidates": [...], "manifest": {...}, "rejected": [...]}.

    Exits with status 1 on:
      - out_dir inside the repository root
      - missing required files (synthetic_records.jsonl, synthetic_manifest.json,
        checksums.sha256)
      - checksum mismatch
      - any record failing validation
      - any governance security violation
      - empty input (no records produced)
    """
    synthetic_dir = Path(synthetic_dir)
    out_dir = Path(out_dir)

    # Gate 1: out_dir must be outside repo
    try:
        out_dir.resolve().relative_to(_REPO_ROOT)
        _fail(
            f"BRIDGE_SECURITY_BLOCK: out_dir must be outside repository root "
            f"({_REPO_ROOT}): {out_dir}"
        )
    except ValueError:
        pass

    # Gate 2: all required source files must exist
    for fname in _REQUIRED_FILES:
        if not (synthetic_dir / fname).exists():
            _fail(f"Required file missing in --synthetic-dir: {fname!r}")

    # Gate 3: checksum integrity (fails hard on any mismatch)
    _verify_checksums(synthetic_dir)

    # Gate 4: load and parse manifest
    manifest_path = synthetic_dir / "synthetic_manifest.json"
    try:
        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"synthetic_manifest.json is not valid JSON: {exc}")

    # Gate 5: load, validate, and convert records
    jsonl_path = synthetic_dir / "synthetic_records.jsonl"
    raw_lines = [
        ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    bridge_run_at = _now_utc()
    candidates: list = []
    rejected: list = []

    for i, line in enumerate(raw_lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            _fail(f"synthetic_records.jsonl line {i + 1} is not valid JSON: {exc}")

        reason = _validate_record(rec, i)
        if reason:
            rejected.append({
                "line": i + 1,
                "rejection_reason": reason,
                "record_id": rec.get("record_id", ""),
            })
        else:
            candidates.append(_to_candidate(rec, operator_id, bridge_run_at))

    # Fail closed if any record failed validation
    if rejected:
        reasons = sorted({r["rejection_reason"] for r in rejected})
        _fail(
            f"Bridge rejected {len(rejected)} of {len(raw_lines)} record(s). "
            f"Rejection reasons: {reasons}. "
            "Fix all records and re-run. No output was written."
        )

    if not candidates:
        _fail("No records found in synthetic_records.jsonl. Input may be empty.")

    # Invariant audit — belt-and-suspenders
    for c in candidates:
        assert c["training_allowed"] is False,           "INVARIANT: training_allowed must be false"
        assert c["store1_write_allowed"] is False,       "INVARIANT: store1_write_allowed must be false"
        assert c["runtime_deployment_allowed"] is False, "INVARIANT: runtime_deployment_allowed must be false"
        assert c["model_promotion_allowed"] is False,    "INVARIANT: model_promotion_allowed must be false"
        assert c["external_calls_allowed"] is False,     "INVARIANT: external_calls_allowed must be false"
        assert c["operator_review_required"] is True,   "INVARIANT: operator_review_required must be true"
        assert c["synthetic_origin"] is True,            "INVARIANT: synthetic_origin must be true"
        assert c["promotion_status"] == "candidate_only","INVARIANT: promotion_status wrong"

    # Write outputs (only after ALL validation passes)
    out_dir.mkdir(parents=True, exist_ok=True)

    bridge_manifest = {
        "bridge_version":                  BRIDGE_VERSION,
        "schema_version":                  SCHEMA_VERSION,
        "bridge_run_at":                   bridge_run_at,
        "operator_id":                     operator_id,
        "source_synthetic_dir":            str(synthetic_dir.resolve()),
        "source_generator_version":        source_manifest.get("generator_version", ""),
        "source_generation_agent_id":      source_manifest.get("generation_agent_id", ""),
        "source_source_id":                source_manifest.get("source_id", ""),
        "source_clearance_ledger_entry_id": source_manifest.get("clearance_ledger_entry_id", ""),
        "records_read":                    len(raw_lines),
        "records_accepted":                len(candidates),
        "records_rejected":                0,
        "candidates_produced":             len(candidates),
        "candidate_lane":                  CANDIDATE_LANE,
        "governance":                      dict(_GOVERNANCE_LABELS),
        "notes": (
            "Synthetic candidates require operator review before any SFT or dataset use. "
            "No real training occurred. TR-05 was not started."
        ),
    }

    audit_record = {
        "bridge_version":                    BRIDGE_VERSION,
        "bridge_run_at":                     bridge_run_at,
        "operator_id":                       operator_id,
        "source_generator_version":          source_manifest.get("generator_version", ""),
        "source_generation_agent_id":        source_manifest.get("generation_agent_id", ""),
        "source_source_id":                  source_manifest.get("source_id", ""),
        "source_clearance_ledger_entry_id":  source_manifest.get("clearance_ledger_entry_id", ""),
        "source_record_count_from_manifest": source_manifest.get("record_count", 0),
        "records_processed":                 len(raw_lines),
        "candidates_produced":               len(candidates),
        "rejected_record_count":             0,
        "all_candidates_inactive":           True,
        "raw_examples_excluded":             True,
        "no_real_training":                  True,
        "tr05_started":                      False,
        "governance":                        dict(_GOVERNANCE_LABELS),
    }

    candidates_path = out_dir / "synthetic_candidates.jsonl"
    manifest_out    = out_dir / "bridge_manifest.json"
    audit_out       = out_dir / "audit_record.json"
    checksums_out   = out_dir / "checksums.sha256"

    candidates_path.write_text(
        "\n".join(json.dumps(c, separators=(",", ":")) for c in candidates) + "\n",
        encoding="utf-8",
    )
    manifest_out.write_text(json.dumps(bridge_manifest, indent=2), encoding="utf-8")
    audit_out.write_text(json.dumps(audit_record, indent=2), encoding="utf-8")

    checksum_lines = [
        f"{_sha256_hex(candidates_path.read_bytes())}  {candidates_path.name}",
        f"{_sha256_hex(manifest_out.read_bytes())}  {manifest_out.name}",
        f"{_sha256_hex(audit_out.read_bytes())}  {audit_out.name}",
    ]
    checksums_out.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print(f"Synthetic Review Bridge {BRIDGE_VERSION}")
    print(f"  Operator ID              : {operator_id}")
    print(f"  Source dir               : {synthetic_dir}")
    print(f"  Records processed        : {len(raw_lines)}")
    print(f"  Candidates produced      : {len(candidates)}")
    print(f"  training_allowed         : False (all)")
    print(f"  operator_review_required : True (all)")
    print(f"  Candidates JSONL         : {candidates_path}")
    print(f"  Bridge manifest          : {manifest_out}")
    print(f"  Audit record             : {audit_out}")
    print(f"  Checksums                : {checksums_out}")

    return {"candidates": candidates, "manifest": bridge_manifest, "rejected": rejected}


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="synthetic_review_bridge.py",
        description=(
            "TR-04C: Convert synthetic_doctrine.py output into operator-review "
            "candidates. Verifies checksums. No real training. No direct SFT bypass."
        ),
    )
    p.add_argument(
        "--synthetic-dir", required=True, dest="synthetic_dir",
        help="Directory produced by synthetic_doctrine.py (contains synthetic_records.jsonl, "
             "synthetic_manifest.json, checksums.sha256).",
    )
    p.add_argument(
        "--out-dir", required=True, dest="out_dir",
        help="Output directory (must be outside the repository root).",
    )
    p.add_argument(
        "--operator-id", default="BRIDGE_OPERATOR", dest="operator_id",
        help="Operator identifier recorded in every candidate and the audit record.",
    )
    return p


def main(argv=None) -> None:
    args = _build_arg_parser().parse_args(argv)
    run_bridge(
        synthetic_dir=args.synthetic_dir,
        out_dir=args.out_dir,
        operator_id=args.operator_id,
    )


if __name__ == "__main__":
    main()
