"""
LOGOS ASF — TR-03 Dataset Builder v1.0.0
LOGOS Governance Systems Inc.

Accepts only operator-approved training_candidate records with
resulting_status=dataset_promotion_pending. Produces immutable versioned
dataset artifacts with provenance, checksums, and scan results.

Never sets training_allowed=true. Never submits a training job.
All output is written outside the repository.

Usage:
  python3 training/dataset_builder.py \\
    --candidates <path/to/candidates.jsonl> \\
    --decisions  <path/to/decisions.jsonl> \\
    --out        <output-dir (outside repo)> \\
    [--run-id    <run_id>] \\
    [--mode      simulation|production]
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dataset_scanner import (
    DatasetScanner,
    ScanReport,
    Finding,
    SEV_CRITICAL,
    SCANNER_VERSION,
)

BUILDER_VERSION = "dataset_builder:1.0.0"
MANIFEST_SCHEMA_VERSION = "1.0.0"
CANDIDATE_SCHEMA_VERSION = "1.0.0"
DECISION_SCHEMA_VERSION  = "1.0.0"

REQUIRED_DECISION_ACTION = "approve"
REQUIRED_RESULTING_STATUS = "dataset_promotion_pending"
REQUIRED_CANDIDATE_LANE   = "training_candidate"
REQUIRED_SOURCE_PROVENANCE = "sentinel_overwatch"

# Operator IDs that are only valid in simulation mode
SIMULATED_OPERATOR_PREFIXES = ("TEST_", "SIM_", "DRY_")
SIMULATED_OPERATOR_SUBSTRINGS = ("_SIM_", "_DRY_", "_TEST_")

DEFAULT_SPLIT = {"train": 0.80, "validation": 0.10, "test": 0.10}
SPLIT_SEED = "logos-asf:tr03:split:v1.0.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

MIN_RECORDS_FOR_THREE_WAY_SPLIT = 10


def _fail(msg: str) -> None:
    print(f"HARD_STOP: {msg}", file=sys.stderr)
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _date_from_ts(ts: str) -> str:
    m = re.search(r"(\d{8})", ts.replace("-", "").replace(":", ""))
    return m.group(1) if m else "00000000"


def _dataset_id(accepted_ids: list, run_id: str) -> str:
    payload = json.dumps(sorted(accepted_ids) + [run_id], separators=(",", ":"))
    sha = _sha256(payload)[:8]
    date = _date_from_ts(_now())
    return f"DS-{date}-{sha}"


def _is_simulated_operator(operator_id: str) -> bool:
    for prefix in SIMULATED_OPERATOR_PREFIXES:
        if operator_id.startswith(prefix):
            return True
    for sub in SIMULATED_OPERATOR_SUBSTRINGS:
        if sub in operator_id:
            return True
    return False


def _decision_hash(record: dict) -> str:
    r = {k: v for k, v in record.items() if k != "decision_hash"}
    return _sha256(json.dumps(r, sort_keys=True, separators=(",", ":")))


# ── loaders ───────────────────────────────────────────────────────────────────

def load_decisions(path: Path) -> dict:
    """Load TR-02 decisions keyed by candidate_id. Verify hashes."""
    if not path.exists():
        _fail(f"decisions file not found: {path}")
    decisions = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError as e:
            _fail(f"malformed decision on line {i}: {e}")
        # Verify hash
        stored = d.get("decision_hash", "")
        expected = _decision_hash(d)
        if stored != expected:
            _fail(f"decision hash mismatch on line {i}: id={d.get('decision_id')} "
                  f"stored={stored[:8]} expected={expected[:8]}")
        cid = d.get("candidate_id")
        if not cid:
            _fail(f"decision on line {i} missing candidate_id")
        decisions.setdefault(cid, []).append(d)
    return decisions


def load_candidates(path: Path) -> dict:
    """Load candidates keyed by candidate_id."""
    if not path.exists():
        _fail(f"candidates file not found: {path}")
    candidates = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            c = json.loads(line)
        except json.JSONDecodeError as e:
            _fail(f"malformed candidate on line {i}: {e}")
        cid = c.get("candidate_id")
        if not cid:
            _fail(f"candidate on line {i} missing candidate_id")
        candidates[cid] = c
    return candidates


# ── eligibility ───────────────────────────────────────────────────────────────

def check_candidate_eligibility(cid: str, candidate: dict, decisions_for_cid: list,
                                 mode: str) -> tuple:
    """
    Return (record, reject_reason) where record is the merged training record
    or None if rejected.
    reject_reason is None if accepted.
    """
    # Must be a training_candidate
    if candidate.get("candidate_lane") != REQUIRED_CANDIDATE_LANE:
        return None, f"wrong_lane:{candidate.get('candidate_lane')}"

    # Must have a valid approval decision
    approvals = [
        d for d in (decisions_for_cid or [])
        if d.get("action") == REQUIRED_DECISION_ACTION
        and d.get("resulting_status") == REQUIRED_RESULTING_STATUS
    ]
    if not approvals:
        return None, "no_valid_approval:no_dataset_promotion_pending_decision"

    # Use the most recent approval
    approval = approvals[-1]

    # Production mode: reject simulated operators
    op_id = approval.get("operator_id", "")
    if mode == "production" and _is_simulated_operator(op_id):
        return None, f"simulated_operator_in_production_mode:{op_id}"

    # Verify invariants in candidate — hard stop, not soft rejection
    if candidate.get("training_allowed") is not False:
        _fail(f"INVARIANT: candidate {cid} has training_allowed != false; source data is corrupted")
    if candidate.get("store1_write_allowed") is not False:
        _fail(f"INVARIANT: candidate {cid} has store1_write_allowed != false; source data is corrupted")
    if candidate.get("runtime_deployment_allowed") is not False:
        _fail(f"INVARIANT: candidate {cid} has runtime_deployment_allowed != false; source data is corrupted")

    # Verify invariants in approval decision — hard stop, not soft rejection
    if approval.get("training_allowed") is not False:
        _fail(f"INVARIANT: decision {approval.get('decision_id')} has training_allowed != false")
    if approval.get("store1_write_allowed") is not False:
        _fail(f"INVARIANT: decision {approval.get('decision_id')} has store1_write_allowed != false")
    if approval.get("runtime_deployment_allowed") is not False:
        _fail(f"INVARIANT: decision {approval.get('decision_id')} has runtime_deployment_allowed != false")

    # Build the training record
    record = {
        "record_id":             cid,
        "candidate_id":          cid,
        "candidate_version":     candidate.get("candidate_version", 1),
        "candidate_lane":        candidate.get("candidate_lane"),
        "task_type":             candidate.get("task_type"),
        "input":                 candidate.get("input", ""),
        "desired_output":        candidate.get("desired_output", ""),
        "source_provenance":     candidate.get("source_provenance"),
        "source_signature_id":   (candidate.get("source_signature_ids") or [""])[0],
        "evidence": {
            "generation":   candidate.get("evidence", {}).get("generation"),
            "vector_id":    candidate.get("evidence", {}).get("vector_id"),
            "level":        candidate.get("evidence", {}).get("level"),
            "distortion_type": candidate.get("evidence", {}).get("distortion_type"),
        },
        "confidence":            candidate.get("confidence"),
        "approval_decision_id":  approval.get("decision_id"),
        "approval_operator_id":  op_id,
        "approval_operator_role": approval.get("operator_role"),
        "approval_timestamp":    approval.get("timestamp"),
        "training_allowed":      False,
        "store1_write_allowed":  False,
        "runtime_deployment_allowed": False,
    }
    return record, None


# ── splitting ─────────────────────────────────────────────────────────────────

def deterministic_split(records: list) -> tuple:
    """
    Group records by source_signature_id. Sort groups deterministically.
    Assign groups to train/validation/test using 80/10/10 policy.
    All examples in a group stay in the same split.
    Returns (train, validation, test, status).
    """
    if not records:
        return [], [], [], "insufficient_dataset_size"

    # Group by source_signature_id
    groups: dict = {}
    for r in records:
        sig = r.get("source_signature_id") or r["record_id"]
        groups.setdefault(sig, []).append(r)

    # Sort groups deterministically by sha256(sig)
    sorted_sigs = sorted(
        groups.keys(),
        key=lambda s: _sha256(s),
    )

    n_groups = len(sorted_sigs)
    if n_groups < 3:
        # Too few groups for meaningful three-way split
        return records, [], [], "insufficient_dataset_size"

    # Determine cutoffs
    train_cut = max(1, round(n_groups * DEFAULT_SPLIT["train"]))
    val_cut   = max(1, round(n_groups * DEFAULT_SPLIT["validation"]))
    test_cut  = n_groups - train_cut - val_cut
    if test_cut < 1:
        # Push one group from train to test
        train_cut -= 1
        test_cut = 1

    train_sigs = sorted_sigs[:train_cut]
    val_sigs   = sorted_sigs[train_cut:train_cut + val_cut]
    test_sigs  = sorted_sigs[train_cut + val_cut:]

    train = [r for s in train_sigs for r in groups[s]]
    val   = [r for s in val_sigs   for r in groups[s]]
    test  = [r for s in test_sigs  for r in groups[s]]

    return train, val, test, "ok"


# ── content hash ──────────────────────────────────────────────────────────────

def _content_hash(train: list, val: list, test: list) -> str:
    combined = "\n".join(
        json.dumps(r, sort_keys=True, separators=(",", ":"))
        for r in train + val + test
    ).encode("utf-8")
    return "sha256:" + _sha256_bytes(combined)


# ── writer ────────────────────────────────────────────────────────────────────

def write_jsonl(path: Path, records: list) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + ("\n" if records else ""),
        encoding="utf-8",
    )


def write_checksums(out_dir: Path, artifact_paths: list) -> Path:
    lines = []
    for p in artifact_paths:
        if p.exists():
            sha = _sha256_bytes(p.read_bytes())
            lines.append(f"{sha}  {p.name}")
    checksum_path = out_dir / "checksums.sha256"
    checksum_path.write_text("\n".join(lines) + "\n")
    return checksum_path


# ── main builder ──────────────────────────────────────────────────────────────

def build_dataset(candidates_path: Path, decisions_path: Path,
                  out_dir: Path, run_id: str, mode: str = "simulation") -> dict:
    # Security: refuse output inside repo
    try:
        out_dir.resolve().relative_to(REPO_ROOT)
        _fail(f"--out must be outside repository root ({REPO_ROOT}): {out_dir}")
    except ValueError:
        pass

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _now()

    # Load inputs
    candidates = load_candidates(candidates_path)
    decisions  = load_decisions(decisions_path)

    # Eligibility filtering
    accepted  = []
    rejected  = []
    candidate_ids  = list(candidates.keys())
    source_hashes  = {}
    source_decision_ids = []

    for cid in candidate_ids:
        candidate = candidates[cid]
        decs = decisions.get(cid, [])
        record, reason = check_candidate_eligibility(cid, candidate, decs, mode)
        if reason:
            rejected.append({"candidate_id": cid, "rejection_reason": reason})
        else:
            accepted.append(record)
            source_hashes[cid] = _sha256(
                json.dumps(candidate, sort_keys=True, separators=(",", ":"))
            )
            # Find the approval decision ID
            for d in decs:
                if d.get("action") == "approve" and d.get("resulting_status") == REQUIRED_RESULTING_STATUS:
                    source_decision_ids.append(d.get("decision_id", ""))
                    break

    # Scanner pass on accepted records
    scanner = DatasetScanner()
    scan_report = scanner.scan(accepted)
    scanner_critical_ids = scan_report.critical_ids()

    # Remove scanner-critical records from accepted
    scanner_rejected = []
    clean_accepted = []
    for r in accepted:
        rid = r["record_id"]
        if rid in scanner_critical_ids:
            all_findings = scan_report.findings_for(rid)
            critical = [f for f in all_findings if f.severity == SEV_CRITICAL]
            reason = critical[0].category if critical else (all_findings[0].category if all_findings else "scanner_critical")
            scanner_rejected.append({"candidate_id": rid, "rejection_reason": f"scanner:{reason}"})
        else:
            clean_accepted.append(r)

    rejected.extend(scanner_rejected)

    # Splitting
    train, val, test, split_status = deterministic_split(clean_accepted)

    # Post-split leakage scan
    leakage_findings = scanner.scan_splits_for_leakage(train, val, test)
    if leakage_findings:
        # Fail closed on any leakage
        _fail(f"CRITICAL: cross-split leakage detected ({len(leakage_findings)} cases). "
              f"Affected records: {[f.record_id for f in leakage_findings]}")

    # Imbalance report (warning only)
    imbalance_findings = scanner.check_imbalance(clean_accepted)
    scan_report.findings.extend(imbalance_findings)

    # Content hash
    ch = _content_hash(train, val, test)

    # Scan statuses (derive from scan_report categories)
    def _status_for_category(cats_found, relevant_cats):
        if any(c in cats_found and c in {"secret_pattern", "credential"} for c in relevant_cats):
            return "FAILED"
        if any(c in cats_found for c in relevant_cats):
            return "PASSED_WITH_WARNINGS"
        return "PASSED"

    cats = set(scan_report.categories_found)
    contamination_status = scan_report.scan_status
    leakage_status = "PASSED" if not leakage_findings else "FAILED"
    pii_status = "PASSED_WITH_WARNINGS" if "pii" in cats else "PASSED"
    secret_status = "FAILED" if "secret_pattern" in cats or "credential" in cats else "PASSED"
    eval_excl_status = "EXCLUSION_FAILED" if "protected_evaluation_overlap" in cats else "CONFIRMED_EXCLUDED"

    # Overall dataset status
    if split_status == "insufficient_dataset_size":
        dataset_status = "insufficient_dataset_size"
    elif scan_report.has_critical or leakage_findings:
        dataset_status = "contamination_blocked"
    elif not clean_accepted:
        dataset_status = "dataset_validation_failed"
    else:
        dataset_status = "dataset_validation_passed"

    # Generate dataset_id
    ds_id = _dataset_id([r["record_id"] for r in clean_accepted], run_id)

    # Write artifacts
    train_path  = out_dir / "train.jsonl"
    val_path    = out_dir / "validation.jsonl"
    test_path   = out_dir / "test.jsonl"
    prov_path   = out_dir / "provenance.jsonl"
    rej_path    = out_dir / "rejected.jsonl"
    scan_path   = out_dir / "scan_report.json"
    manifest_p  = out_dir / "manifest.json"

    write_jsonl(train_path, train)
    write_jsonl(val_path, val)
    write_jsonl(test_path, test)
    write_jsonl(prov_path, [
        {
            "record_id": r["record_id"],
            "candidate_id": r["candidate_id"],
            "approval_decision_id": r.get("approval_decision_id"),
            "source_hash": source_hashes.get(r["record_id"], ""),
            "split": (
                "train" if r in train else
                "validation" if r in val else
                "test"
            ),
            "built_at": ts,
        }
        for r in (train + val + test)
    ])
    write_jsonl(rej_path, rejected)
    scan_path.write_text(json.dumps(scan_report.to_dict(), indent=2))

    # Checksums
    artifact_paths = [train_path, val_path, test_path, prov_path, rej_path, scan_path]
    checksum_path = write_checksums(out_dir, artifact_paths)

    # Manifest — all invariants hard-set
    manifest = {
        "dataset_id":                   ds_id,
        "dataset_version":              "1",
        "dataset_status":               dataset_status,
        "created_at":                   ts,
        "builder_version":              BUILDER_VERSION,
        "build_mode":                   mode,
        "source_candidate_count":       len(candidates),
        "accepted_record_count":        len(clean_accepted),
        "rejected_record_count":        len(rejected),
        "train_count":                  len(train),
        "validation_count":             len(val),
        "test_count":                   len(test),
        "split_policy": {
            "train_fraction":           DEFAULT_SPLIT["train"],
            "validation_fraction":      DEFAULT_SPLIT["validation"],
            "test_fraction":            DEFAULT_SPLIT["test"],
            "deterministic_seed":       SPLIT_SEED,
            "group_by_source_signature": True,
        },
        "source_candidate_ids":         sorted(r["record_id"] for r in clean_accepted),
        "source_decision_ids":          source_decision_ids,
        "source_hashes":                source_hashes,
        "schema_versions": {
            "candidate_schema":  CANDIDATE_SCHEMA_VERSION,
            "decision_schema":   DECISION_SCHEMA_VERSION,
            "manifest_schema":   MANIFEST_SCHEMA_VERSION,
        },
        "contamination_scan_status":    contamination_status,
        "leakage_scan_status":          leakage_status,
        "pii_scan_status":              pii_status,
        "secret_scan_status":           secret_status,
        "evaluation_set_exclusion_status": eval_excl_status,
        "content_hash":                 ch,
        "training_allowed":             False,
        "store1_write_allowed":         False,
        "runtime_deployment_allowed":   False,
        "operator_promotion_required":  True,
    }

    # Hard invariant assertions
    assert manifest["training_allowed"] is False,         "INVARIANT: training_allowed"
    assert manifest["store1_write_allowed"] is False,     "INVARIANT: store1_write_allowed"
    assert manifest["runtime_deployment_allowed"] is False,"INVARIANT: runtime_deployment_allowed"
    assert manifest["operator_promotion_required"] is True,"INVARIANT: operator_promotion_required"

    manifest_p.write_text(json.dumps(manifest, indent=2))

    # Print summary
    print(f"TR-03 Dataset Builder {BUILDER_VERSION} — Run {run_id}")
    print(f"  Mode              : {mode}")
    print(f"  Candidates in     : {len(candidates)}")
    print(f"  Eligibility pass  : {len(accepted)}")
    print(f"  Scanner rejected  : {len(scanner_rejected)}")
    print(f"  Clean accepted    : {len(clean_accepted)}")
    print(f"  Train/Val/Test    : {len(train)}/{len(val)}/{len(test)}")
    print(f"  Dataset ID        : {ds_id}")
    print(f"  Dataset status    : {dataset_status}")
    print(f"  Scan status       : {scan_report.scan_status}")
    print(f"  training_allowed  : {manifest['training_allowed']}")
    print(f"  Output            : {out_dir}/")
    return manifest


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dataset_builder.py",
        description="TR-03 Dataset Builder — governed training dataset construction",
    )
    parser.add_argument("--candidates", required=True,
                        help="Path to approved candidates JSONL")
    parser.add_argument("--decisions",  required=True,
                        help="Path to TR-02 decisions JSONL")
    parser.add_argument("--out", required=True,
                        help="Output directory (must be outside repository)")
    parser.add_argument("--run-id", default=None,
                        help="Run identifier (default: derived from timestamp)")
    parser.add_argument("--mode", choices=["simulation", "production"],
                        default="simulation",
                        help="simulation: accepts TEST_ operators (default). production: rejects them.")
    args = parser.parse_args()

    run_id = args.run_id or f"tr03_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    build_dataset(
        candidates_path=Path(args.candidates),
        decisions_path=Path(args.decisions),
        out_dir=Path(args.out),
        run_id=run_id,
        mode=args.mode,
    )


if __name__ == "__main__":
    main()
