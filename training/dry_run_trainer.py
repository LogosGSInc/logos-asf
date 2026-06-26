"""
LOGOS ASF — TR-04 Dry-Run Training Adapter v1.0.0
LOGOS Governance Systems Inc.

Validates TR-03 dataset artifacts and constructs a governed training-job
envelope describing what would be submitted — without performing real training,
network calls, API calls, provider SDK calls, weight updates, dataset upload,
Store1 mutation, runtime deployment, or model promotion.

All governance flags remain deny-by-default.
Operator approval is required before any real training may proceed.

Usage:
  python3 training/dry_run_trainer.py \\
    --dataset-dir <path-to-tr03-artifact-dir> \\
    --out-dir     <output-dir (must be outside repository)> \\
    --mode        simulation|production \\
    [--operator-id <operator_id>]   # required for production mode
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ADAPTER_VERSION = "dry_run_trainer:1.0.0"
SUPPORTED_MANIFEST_SCHEMA_VERSIONS = frozenset({"1.0.0"})

SIMULATED_OPERATOR_PREFIXES    = ("TEST_", "SIM_", "DRY_")
SIMULATED_OPERATOR_SUBSTRINGS  = ("_SIM_", "_DRY_", "_TEST_")

# Files that must be present in every TR-03 artifact directory
REQUIRED_ARTIFACTS = [
    "train.jsonl",
    "validation.jsonl",
    "test.jsonl",
    "provenance.jsonl",
    "rejected.jsonl",
    "scan_report.json",
    "checksums.sha256",
]

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── helpers ───────────────────────────────────────────────────────────────────

def _fail(msg: str) -> None:
    print(f"HARD_STOP: {msg}", file=sys.stderr)
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_simulated_operator(op_id: str) -> bool:
    for prefix in SIMULATED_OPERATOR_PREFIXES:
        if op_id.startswith(prefix):
            return True
    for sub in SIMULATED_OPERATOR_SUBSTRINGS:
        if sub in op_id:
            return True
    return False


def _count_jsonl_lines(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _estimate_char_volume(dataset_dir: Path) -> int:
    total = 0
    for name in ("train.jsonl", "validation.jsonl"):
        p = dataset_dir / name
        if p.exists():
            total += len(p.read_bytes())
    return total


def _config_digest(mode: str, operator_id: str) -> str:
    config = {
        "adapter": ADAPTER_VERSION,
        "mode": mode,
        "operator_id": operator_id,
    }
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _dry_run_id(manifest: dict, mode: str, operator_id: str) -> str:
    content_hash = manifest.get("content_hash", "").replace("sha256:", "")
    cdg = _config_digest(mode, operator_id)
    h = hashlib.sha256(f"{content_hash}:{cdg}".encode("utf-8")).hexdigest()[:16]
    return f"DR-{h}"


# ── checksum verification ─────────────────────────────────────────────────────

def _verify_checksums(dataset_dir: Path) -> tuple:
    """
    Parse checksums.sha256 and verify each listed file.
    Returns (all_ok: bool, mismatches: list of (filename, expected, actual)).
    """
    checksum_file = dataset_dir / "checksums.sha256"
    if not checksum_file.exists():
        return False, [("checksums.sha256", "exists", "missing")]

    mismatches = []
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            continue
        expected_sha, filename = parts[0].strip(), parts[1].strip()
        target = dataset_dir / filename
        if not target.exists():
            mismatches.append((filename, expected_sha[:12], "FILE_MISSING"))
            continue
        actual_sha = _sha256_bytes(target.read_bytes())
        if actual_sha != expected_sha:
            mismatches.append((filename, expected_sha[:12], actual_sha[:12]))

    return len(mismatches) == 0, mismatches


# ── output writers ────────────────────────────────────────────────────────────

def write_output_checksums(out_dir: Path, artifact_paths: list) -> Path:
    lines = []
    for p in artifact_paths:
        if p.exists():
            sha = _sha256_bytes(p.read_bytes())
            lines.append(f"{sha}  {p.name}")
    path = out_dir / "checksums.sha256"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── main entry point ──────────────────────────────────────────────────────────

def run_dry_run(dataset_dir: Path, out_dir: Path,
                mode: str = "simulation",
                operator_id: str = "TEST_SIMULATION") -> dict:
    """
    Validate a TR-03 dataset artifact directory and produce a dry-run
    training envelope. All governance flags remain false/deny-by-default.
    No real training is performed.
    """

    # ── 0. Security: refuse output inside repo ─────────────────────────────
    try:
        out_dir.resolve().relative_to(REPO_ROOT)
        _fail(
            f"SECURITY: --out-dir must be outside repository root "
            f"({REPO_ROOT}): {out_dir}"
        )
    except ValueError:
        pass

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _now()

    # ── 1. manifest.json must exist ────────────────────────────────────────
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.exists():
        _fail(f"MISSING_MANIFEST: no manifest.json found in: {dataset_dir}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(f"INVALID_MANIFEST: manifest.json is not valid JSON: {e}")

    # ── 2. Supported manifest schema version ───────────────────────────────
    manifest_schema_ver = manifest.get("schema_versions", {}).get("manifest_schema", "")
    if manifest_schema_ver not in SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        _fail(
            f"UNSUPPORTED_VERSION: manifest schema_versions.manifest_schema="
            f"{manifest_schema_ver!r} is not supported. "
            f"Supported: {sorted(SUPPORTED_MANIFEST_SCHEMA_VERSIONS)}"
        )

    # ── 3. Required artifacts must be present ──────────────────────────────
    for name in REQUIRED_ARTIFACTS:
        if not (dataset_dir / name).exists():
            _fail(f"MISSING_ARTIFACT: required file not found in dataset dir: {name}")

    # ── 4. Checksum verification ───────────────────────────────────────────
    checksums_ok, mismatches = _verify_checksums(dataset_dir)
    if not checksums_ok:
        details = "; ".join(
            f"{f} expected={e} actual={a}" for f, e, a in mismatches
        )
        _fail(f"CHECKSUM_FAILURE: {details}")

    # ── 5. Governance flags in manifest ───────────────────────────────────
    if manifest.get("training_allowed") is not False:
        _fail(
            "GOVERNANCE_BLOCK: manifest.training_allowed must be false. "
            "This manifest does not authorize training."
        )
    if manifest.get("operator_promotion_required") is not True:
        _fail(
            "GOVERNANCE_BLOCK: manifest.operator_promotion_required must be true."
        )
    if manifest.get("store1_write_allowed") is not False:
        _fail("GOVERNANCE_BLOCK: manifest.store1_write_allowed must be false.")
    if manifest.get("runtime_deployment_allowed") is not False:
        _fail("GOVERNANCE_BLOCK: manifest.runtime_deployment_allowed must be false.")
    if manifest.get("model_promotion_allowed") is True:
        _fail("GOVERNANCE_BLOCK: manifest.model_promotion_allowed must not be true.")
    if manifest.get("external_calls_allowed") is True:
        _fail("GOVERNANCE_BLOCK: manifest.external_calls_allowed must not be true.")

    # ── 6. Scan report: no critical findings, no protected eval overlap ────
    scan_path = dataset_dir / "scan_report.json"
    try:
        scan_report = json.loads(scan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(f"INVALID_SCAN_REPORT: scan_report.json is not valid JSON: {e}")

    if scan_report.get("has_critical") is True:
        _fail(
            "CONTAMINATION_BLOCK: scan_report.has_critical=true. "
            "Critical scanner findings must be resolved before proceeding."
        )
    if "protected_evaluation_overlap" in scan_report.get("categories_found", []):
        _fail(
            "CONTAMINATION_BLOCK: scan_report contains protected_evaluation_overlap. "
            "Protected evaluation assets must not appear in the training corpus."
        )

    # ── 7. Dataset status ──────────────────────────────────────────────────
    dataset_status = manifest.get("dataset_status", "")
    if dataset_status in ("contamination_blocked", "dataset_validation_failed"):
        _fail(
            f"DATASET_BLOCKED: manifest.dataset_status={dataset_status!r}. "
            "Cannot run dry-run against a blocked or failed dataset."
        )

    # ── 8. Split count verification ────────────────────────────────────────
    for split_key, manifest_key, filename in [
        ("train",      "train_count",      "train.jsonl"),
        ("validation", "validation_count", "validation.jsonl"),
        ("test",       "test_count",       "test.jsonl"),
    ]:
        p = dataset_dir / filename
        actual   = _count_jsonl_lines(p)
        expected = manifest.get(manifest_key, -1)
        if actual != expected:
            _fail(
                f"SPLIT_MISMATCH: {filename} contains {actual} records but "
                f"manifest declares {manifest_key}={expected}"
            )

    # ── 9. Operator identity ───────────────────────────────────────────────
    if mode == "production" and _is_simulated_operator(operator_id):
        _fail(
            f"OPERATOR_BLOCKED: production mode rejects simulated operator "
            f"ID: {operator_id!r}"
        )

    # ── 10. Build deterministic dry-run ID ─────────────────────────────────
    dr_id = _dry_run_id(manifest, mode, operator_id)

    # ── 11. Estimate compute (deterministic, no real measurement) ──────────
    char_volume      = _estimate_char_volume(dataset_dir)
    estimated_tokens = char_volume // 4
    train_count      = manifest.get("train_count", 0)
    validation_count = manifest.get("validation_count", 0)
    test_count       = manifest.get("test_count", 0)
    accepted_count   = manifest.get("accepted_record_count", 0)

    # ── 12. Assemble outputs (no raw examples included) ────────────────────

    BLOCKED_REAL_ACTIONS = [
        "real_model_training",
        "model_weight_update",
        "lora_adapter_creation",
        "qlora_adapter_creation",
        "dataset_upload",
        "store1_write",
        "runtime_deployment",
        "model_registry_promotion",
        "external_api_calls",
        "provider_sdk_calls",
        "network_egress",
    ]

    envelope = {
        "schema":                    "logos-asf:training:dry-run-envelope:v1.0.0",
        "dry_run_id":                dr_id,
        "created_at":                ts,
        "adapter_version":           ADAPTER_VERSION,
        "source_dataset_manifest_id": manifest.get("dataset_id"),
        "source_dataset_checksum":   manifest.get("content_hash"),
        "training_allowed":          False,
        "dry_run_only":              True,
        "operator_promotion_required": True,
        "store1_write_allowed":      False,
        "runtime_deployment_allowed": False,
        "model_promotion_allowed":   False,
        "external_calls_allowed":    False,
        "job_intent": {
            "description": (
                "Validate TR-03 dataset artifact for governed training pipeline. "
                "No training performed. Operator must separately sign a "
                "training-job contract before any real training may proceed."
            ),
            "mode":        mode,
            "operator_id": operator_id,
        },
        "dataset_summary": {
            "dataset_id":                    manifest.get("dataset_id"),
            "dataset_status":                dataset_status,
            "build_mode":                    manifest.get("build_mode"),
            "accepted_record_count":         accepted_count,
            "train_count":                   train_count,
            "validation_count":              validation_count,
            "test_count":                    test_count,
            "contamination_scan_status":     manifest.get("contamination_scan_status"),
            "evaluation_set_exclusion_status": manifest.get("evaluation_set_exclusion_status"),
        },
        "validation_summary": {
            "checksum_verified":          True,
            "governance_flags_valid":     True,
            "scan_report_clean":          True,
            "split_counts_match":         True,
            "operator_identity_valid":    True,
            "manifest_version_supported": True,
        },
        "estimated_compute": {
            "estimated_char_volume":   char_volume,
            "estimated_tokens_approx": estimated_tokens,
            "train_record_count":      train_count,
            "validation_record_count": validation_count,
            "notes": (
                "Estimates are approximate. Actual compute depends on base "
                "model and training method, which are not determined at "
                "dry-run stage."
            ),
        },
        "blocked_real_actions": BLOCKED_REAL_ACTIONS,
        "next_required_gate": (
            "TR-05 model registry and lineage (not implemented). "
            "Operator must separately sign a TRAINING_JOB_CONTRACT before "
            "any real training may proceed."
        ),
    }

    training_job_preview = {
        "dry_run_id":    dr_id,
        "created_at":    ts,
        "preview_only":  True,
        "training_allowed": False,
        "job_description": (
            "Preview of what a governed training job would look like. "
            "No job has been submitted and no training has been performed."
        ),
        "required_inputs": {
            "dataset_id":                         manifest.get("dataset_id"),
            "manifest_path":                      str(manifest_path),
            "operator_signed_training_job_contract": "REQUIRED — not yet provided",
        },
        "proposed_training_config": {
            "adapter_type": "dry_run_training (future: local_lora or local_qlora)",
            "method":       "dry_run (future: lora or qlora)",
            "isolation":    "runs_in_isolated_container=true required",
        },
        "gates_required_before_promotion": [
            "held_out_eval",
            "tax2_76_suite",
            "bd1a_baseline",
            "g4_variance",
            "refusal_correctness",
            "tacit_prepass",
            "shadow_deployment",
            "operator_signed_promotion_decision",
        ],
        "blocked_actions": BLOCKED_REAL_ACTIONS,
        "note": (
            "LoRA and QLoRA training remain future work. "
            "TR-05 model registry and lineage not started."
        ),
    }

    validation_report = {
        "dry_run_id": dr_id,
        "created_at": ts,
        "mode":        mode,
        "operator_id": operator_id,
        "all_gates_passed": True,
        "failures":  [],
        "warnings":  [] if dataset_status == "dataset_validation_passed" else [
            f"dataset_status_non_ideal: {dataset_status!r}"
        ],
        "gates": {
            "manifest_exists":                   True,
            "manifest_version_supported":        True,
            "required_artifacts_present":        True,
            "checksums_valid":                   True,
            "training_allowed_false":            True,
            "operator_promotion_required_true":  True,
            "store1_write_allowed_false":        True,
            "runtime_deployment_allowed_false":  True,
            "model_promotion_allowed_not_true":  True,
            "external_calls_allowed_not_true":   True,
            "scan_report_no_critical":           True,
            "scan_report_no_protected_eval":     True,
            "dataset_status_valid":              dataset_status == "dataset_validation_passed",
            "split_counts_match":                True,
            "operator_identity_valid":           True,
        },
    }

    # Audit record — raw prompt and example text explicitly excluded
    audit_record = {
        "dry_run_id":      dr_id,
        "created_at":      ts,
        "adapter_version": ADAPTER_VERSION,
        "mode":            mode,
        "operator_id":     operator_id,
        "dataset_id":      manifest.get("dataset_id"),
        "dataset_status":  dataset_status,
        "manifest_content_hash": manifest.get("content_hash"),
        "training_allowed":      False,
        "dry_run_only":          True,
        "blocked_actions_confirmed": BLOCKED_REAL_ACTIONS,
        "result": "dry_run_accepted",
        "raw_examples_excluded": True,
        "note": (
            "Raw prompt text and example content are excluded from this "
            "audit record to prevent re-exposure of training material."
        ),
        "governance_attestation": (
            "This dry-run produced no model weights, no store1 writes, "
            "no runtime deployment, no model promotion, and no external "
            "calls. Operator promotion is required before any real "
            "training may proceed."
        ),
    }

    # ── 13. Write output artifacts ─────────────────────────────────────────
    env_path     = out_dir / "dry_run_envelope.json"
    preview_path = out_dir / "training_job_preview.json"
    val_path     = out_dir / "validation_report.json"
    audit_path   = out_dir / "audit_record.json"

    env_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    preview_path.write_text(json.dumps(training_job_preview, indent=2), encoding="utf-8")
    val_path.write_text(json.dumps(validation_report, indent=2), encoding="utf-8")
    audit_path.write_text(json.dumps(audit_record, indent=2), encoding="utf-8")

    write_output_checksums(out_dir, [env_path, preview_path, val_path, audit_path])

    # Hard invariant assertions — belt-and-suspenders
    assert envelope["training_allowed"] is False,          "INVARIANT: training_allowed"
    assert envelope["dry_run_only"] is True,               "INVARIANT: dry_run_only"
    assert envelope["operator_promotion_required"] is True,"INVARIANT: operator_promotion_required"
    assert envelope["store1_write_allowed"] is False,      "INVARIANT: store1_write_allowed"
    assert envelope["runtime_deployment_allowed"] is False,"INVARIANT: runtime_deployment_allowed"
    assert envelope["model_promotion_allowed"] is False,   "INVARIANT: model_promotion_allowed"
    assert envelope["external_calls_allowed"] is False,    "INVARIANT: external_calls_allowed"

    # Summary
    print(f"TR-04 Dry-Run Training Adapter {ADAPTER_VERSION}")
    print(f"  Mode              : {mode}")
    print(f"  Operator ID       : {operator_id}")
    print(f"  Dataset ID        : {manifest.get('dataset_id')}")
    print(f"  Dry-Run ID        : {dr_id}")
    print(f"  Dataset status    : {dataset_status}")
    print(f"  Checksums verified: OK")
    print(f"  training_allowed  : False")
    print(f"  Result            : DRY_RUN_ACCEPTED")
    print(f"  Envelope          : {env_path}")
    print(f"  Validation report : {val_path}")

    return envelope


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dry_run_trainer.py",
        description=(
            "TR-04 Dry-Run Training Adapter — validate a TR-03 dataset artifact "
            "and produce a governed training-job envelope. No real training performed."
        ),
    )
    parser.add_argument(
        "--dataset-dir", required=True,
        help="Path to a TR-03 dataset artifact directory containing manifest.json",
    )
    parser.add_argument(
        "--out-dir", required=True,
        help="Output directory for dry-run artifacts (must be outside repository)",
    )
    parser.add_argument(
        "--mode", choices=["simulation", "production"], default="simulation",
        help="simulation: accepts TEST_ operator IDs (default). production: rejects them.",
    )
    parser.add_argument(
        "--operator-id", default="TEST_SIMULATION",
        help="Operator ID for this dry-run. Required to be non-simulated in production mode.",
    )
    args = parser.parse_args()

    run_dry_run(
        dataset_dir=Path(args.dataset_dir),
        out_dir=Path(args.out_dir),
        mode=args.mode,
        operator_id=args.operator_id,
    )


if __name__ == "__main__":
    main()
