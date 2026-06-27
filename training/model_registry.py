"""
LOGOS ASF — TR-05 Model Registry and Lineage v1.0.0
LOGOS Governance Systems Inc.

Metadata-only model registry and lineage DAG for Abigail training readiness.
Records dry-run model/adaptor candidates, dataset ancestry, synthetic provenance,
DEP.KEYSTONE/GovSec V2 ingress evidence, source-registry clearance,
clearance-ledger approvals, dry-run envelopes, and future promotion eligibility.

Hard invariants (enforced at code and assertion level):
  - No real training.
  - No model loading or inference.
  - No model weights created or accepted.
  - No LoRA or QLoRA artifacts.
  - No adapter checkpoint files.
  - No Store 1 writes.
  - No runtime deployment.
  - No model promotion.
  - promotion_status defaults to not_promoted.
  - TR-06 evaluation gates not started.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from training.dep_keystone_ingress import (
    load_ingress_record,
    assert_training_ingress_allowed,
    KeystoneIngressError,
)

REGISTRY_VERSION = "model_registry:1.0.0"
SCHEMA_VERSION = "1.0.0"
GENESIS_HASH = "0" * 64

_HARD_CONSTANTS = {
    "training_allowed":            False,
    "model_weights_present":       False,
    "runtime_deployment_allowed":  False,
    "store1_write_allowed":        False,
    "external_calls_allowed":      False,
    "operator_promotion_required": True,
}

ARTIFACT_TYPES = frozenset({
    "base_model_reference",
    "dry_run_adapter_candidate",
    "future_adapter_placeholder",
    "evaluation_baseline",
    "rejected_candidate",
})

ARTIFACT_STATUSES = frozenset({
    "draft", "registered", "dry_run_only", "blocked", "archived",
})

PROMOTION_STATUSES = frozenset({
    "not_promoted",
    "promotion_blocked",
    "promotion_pending_operator",
    "eligible_for_future_evaluation",
    "archived",
})


class ModelRegistryError(Exception):
    """Base class for model registry errors."""


class ModelRegistryValidationError(ModelRegistryError):
    """Raised when a registry or entry fails structural validation."""


class ModelRegistryBlockedError(ModelRegistryError):
    """Raised when a registration attempt violates a governance constraint."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _sha256_json(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_artifact_id(dry_run_id: str, dataset_id: str, source_id: str) -> str:
    """Deterministic artifact ID from the three key pipeline inputs."""
    raw = f"dry_run:{dry_run_id}:dataset:{dataset_id}:source:{source_id or ''}"
    return "MA-" + _sha256(raw)[:16]


def _compute_lineage_hash(record: dict) -> str:
    """Hash key provenance arrays of a lineage record (excluding lineage_hash itself)."""
    data = {k: record.get(k) for k in (
        "artifact_id",
        "artifact_type",
        "dep_keystone_ingress_refs",
        "keystone_evidence_refs",
        "keystone_verification_report_refs",
        "source_registry_refs",
        "clearance_ledger_refs",
        "dataset_manifest_refs",
        "dry_run_envelope_refs",
    )}
    return _sha256_json(data)


def create_empty_registry(authority: str = "LOGOS Governance Systems Inc.") -> dict:
    """Create an empty TR-05 model registry dict."""
    return {
        "registry_id":  "LOGOS-MODEL-REGISTRY-001",
        "version":      SCHEMA_VERSION,
        "classification": "LOGOS_INTERNAL_GOVERNANCE",
        "authority":    authority,
        "created_at":   _now_utc(),
        "entries":      [],
        "governance":   dict(_HARD_CONSTANTS),
        "notes": (
            "TR-05 model registry. Metadata only. No model weights. "
            "No real training. TR-06 evaluation gates not started."
        ),
    }


def load_registry(path) -> dict:
    """Load and parse a model registry from a JSON file."""
    p = Path(path)
    if not p.exists():
        raise ModelRegistryValidationError(f"Registry not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelRegistryValidationError(f"Registry is not valid JSON: {exc}") from exc


def save_registry(registry: dict, path) -> None:
    """Persist a model registry to a JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def validate_registry(registry: dict) -> dict:
    """
    Validate a model registry dict.
    Raises ModelRegistryValidationError on failure.
    Returns {"valid": True, "entry_count": N} on success.
    """
    errors = []
    for field in ("registry_id", "version", "entries"):
        if field not in registry:
            errors.append(f"missing required field: {field!r}")
    if not isinstance(registry.get("entries"), list):
        errors.append("entries must be a list")
    if errors:
        raise ModelRegistryValidationError(
            f"Registry validation failed ({len(errors)} error(s)):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
    for i, entry in enumerate(registry.get("entries", [])):
        _validate_entry(entry, index=i)
    return {"valid": True, "entry_count": len(registry.get("entries", []))}


def _validate_entry(entry: dict, index: int = 0) -> None:
    required = (
        "model_artifact_id", "artifact_type", "artifact_status",
        "promotion_status", "training_allowed", "model_weights_present",
        "operator_promotion_required",
    )
    for f in required:
        if f not in entry:
            raise ModelRegistryValidationError(
                f"Registry entry[{index}] missing required field: {f!r}"
            )
    if entry.get("training_allowed") is not False:
        raise ModelRegistryValidationError(
            f"Registry entry[{index}]: training_allowed must be false"
        )
    if entry.get("model_weights_present") is not False:
        raise ModelRegistryValidationError(
            f"Registry entry[{index}]: model_weights_present must be false"
        )
    if entry.get("promotion_status") not in PROMOTION_STATUSES:
        raise ModelRegistryValidationError(
            f"Registry entry[{index}]: invalid promotion_status: "
            f"{entry.get('promotion_status')!r}"
        )


def build_lineage_record(
    artifact_id: str,
    artifact_type: str,
    dep_keystone_ingress_refs: list = None,
    keystone_evidence_refs: list = None,
    keystone_verification_report_refs: list = None,
    source_registry_refs: list = None,
    clearance_ledger_refs: list = None,
    synthetic_manifest_refs: list = None,
    synthetic_review_bridge_refs: list = None,
    dataset_manifest_refs: list = None,
    dry_run_envelope_refs: list = None,
    training_job_contract_refs: list = None,
    evaluation_refs: list = None,
    promotion_decision_refs: list = None,
    previous_lineage_hash: str = None,
    notes: str = "",
) -> dict:
    """Build a model lineage record for an artifact."""
    record = {
        "lineage_record_id":              "",
        "schema_version":                 SCHEMA_VERSION,
        "created_at":                     _now_utc(),
        "artifact_id":                    artifact_id,
        "artifact_type":                  artifact_type,
        "parent_artifacts":               [],
        "dep_keystone_ingress_refs":      list(dep_keystone_ingress_refs or []),
        "keystone_evidence_refs":         list(keystone_evidence_refs or []),
        "keystone_verification_report_refs": list(keystone_verification_report_refs or []),
        "source_registry_refs":           list(source_registry_refs or []),
        "clearance_ledger_refs":          list(clearance_ledger_refs or []),
        "synthetic_manifest_refs":        list(synthetic_manifest_refs or []),
        "synthetic_review_bridge_refs":   list(synthetic_review_bridge_refs or []),
        "dataset_manifest_refs":          list(dataset_manifest_refs or []),
        "dry_run_envelope_refs":          list(dry_run_envelope_refs or []),
        "training_job_contract_refs":     list(training_job_contract_refs or []),
        "evaluation_refs":                list(evaluation_refs or []),
        "promotion_decision_refs":        list(promotion_decision_refs or []),
        "lineage_hash":                   "",
        "previous_lineage_hash":          previous_lineage_hash or GENESIS_HASH,
        "governance_flags":               dict(_HARD_CONSTANTS),
        "notes":                          notes,
    }
    record["lineage_hash"] = _compute_lineage_hash(record)

    # Deterministic lineage_record_id from artifact_id + first DEP.KEYSTONE ref + first dry run ref
    dep_ref = (record["dep_keystone_ingress_refs"] or [""])[0]
    dry_ref = (record["dry_run_envelope_refs"] or [""])[0]
    record["lineage_record_id"] = "LR-" + _sha256(
        f"{artifact_id}:{dep_ref}:{dry_ref}"
    )[:16]

    return record


def validate_lineage_record(record: dict) -> dict:
    """
    Validate a model lineage record dict.
    Raises ModelRegistryValidationError on failure.
    Returns {"valid": True, "lineage_record_id": ...} on success.
    """
    required = (
        "lineage_record_id", "artifact_id", "lineage_hash",
        "governance_flags", "dep_keystone_ingress_refs",
        "dataset_manifest_refs", "dry_run_envelope_refs",
    )
    errors = []
    for f in required:
        if f not in record:
            errors.append(f"missing: {f!r}")
    if errors:
        raise ModelRegistryValidationError(
            f"Lineage record validation failed: {errors}"
        )
    gov = record.get("governance_flags", {})
    if gov.get("training_allowed") is not False:
        raise ModelRegistryValidationError(
            "lineage_record: governance_flags.training_allowed must be false"
        )
    if gov.get("model_weights_present") is not False:
        raise ModelRegistryValidationError(
            "lineage_record: governance_flags.model_weights_present must be false"
        )
    return {
        "valid": True,
        "lineage_record_id": record.get("lineage_record_id"),
    }


def summarize_registry(registry: dict) -> dict:
    """Return a count-based summary of the registry by status and promotion state."""
    entries = registry.get("entries", [])
    by_status: dict = {}
    by_promotion: dict = {}
    for e in entries:
        s = e.get("artifact_status", "unknown")
        p = e.get("promotion_status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        by_promotion[p] = by_promotion.get(p, 0) + 1
    return {
        "registry_id":           registry.get("registry_id"),
        "version":               registry.get("version"),
        "total_entries":         len(entries),
        "by_artifact_status":    by_status,
        "by_promotion_status":   by_promotion,
        "governance":            registry.get("governance", {}),
    }


def find_artifact(registry: dict, model_artifact_id: str) -> dict | None:
    """Return the registry entry for model_artifact_id, or None if not found."""
    for entry in registry.get("entries", []):
        if entry.get("model_artifact_id") == model_artifact_id:
            return entry
    return None


def assert_not_promoted(registry: dict, model_artifact_id: str) -> None:
    """
    Assert that an artifact has not been promoted.
    Raises ModelRegistryBlockedError if the artifact is not in a safe state.
    """
    entry = find_artifact(registry, model_artifact_id)
    if entry is None:
        raise ModelRegistryValidationError(
            f"Artifact {model_artifact_id!r} not found in registry."
        )
    status = entry.get("promotion_status")
    if status not in ("not_promoted", "promotion_blocked"):
        raise ModelRegistryBlockedError(
            f"Artifact {model_artifact_id!r} has promotion_status={status!r}. "
            "Expected not_promoted or promotion_blocked."
        )


def _load_json(path, label: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise ModelRegistryValidationError(f"{label} not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelRegistryValidationError(
            f"{label} is not valid JSON: {exc}"
        ) from exc


def register_dry_run_candidate(
    registry: dict,
    dry_run_envelope_path,
    dataset_manifest_path,
    dep_keystone_ingress_path=None,
    source_registry_path=None,
    clearance_ledger_path=None,
    created_by: str = "TEST_OPERATOR",
    model_weights_path=None,
    adapter_checkpoint_path=None,
) -> dict:
    """
    Register a TR-04B dry-run envelope as a dry_run_adapter_candidate registry entry.

    Returns the updated registry dict.

    Raises ModelRegistryBlockedError if any governance constraint is violated.
    Raises ModelRegistryValidationError if inputs are structurally invalid.

    Hard stops:
      - model_weights_path and adapter_checkpoint_path are never accepted.
      - dry_run_envelope.training_allowed must be false.
      - dry_run_envelope.validation_summary.source_registry_cleared must be true.
      - dry_run_envelope.validation_summary.ledger_cleared must be true.
      - dataset_manifest.training_allowed must be false.
      - dataset_manifest.operator_promotion_required must be true.
      - DEP.KEYSTONE ingress (when supplied) must clear tr05_model_registry.
    """
    # Explicit rejection of weight paths — no exceptions
    if model_weights_path is not None:
        raise ModelRegistryBlockedError(
            "Registration rejected: model_weights_path must not be provided. "
            "TR-05 is metadata-only. No model weights are created or accepted."
        )
    if adapter_checkpoint_path is not None:
        raise ModelRegistryBlockedError(
            "Registration rejected: adapter_checkpoint_path must not be provided. "
            "TR-05 is metadata-only. No adapter checkpoints are created or accepted."
        )

    # Load dry-run envelope
    envelope = _load_json(dry_run_envelope_path, "dry_run_envelope")
    envelope_path = Path(dry_run_envelope_path).resolve()

    # Verify dry-run governance flags
    _assert_field_false(envelope, "training_allowed", "dry_run_envelope")
    if "dry_run_only" in envelope:
        _assert_field_true(envelope, "dry_run_only", "dry_run_envelope")
    if "model_promotion_allowed" in envelope:
        _assert_field_false(envelope, "model_promotion_allowed", "dry_run_envelope")
    _assert_field_false(envelope, "runtime_deployment_allowed", "dry_run_envelope")
    _assert_field_false(envelope, "store1_write_allowed",        "dry_run_envelope")
    _assert_field_false(envelope, "external_calls_allowed",      "dry_run_envelope")

    val = envelope.get("validation_summary", {})
    if val.get("source_registry_cleared") is not True:
        raise ModelRegistryBlockedError(
            "dry_run_envelope.validation_summary.source_registry_cleared must be true."
        )
    if val.get("ledger_cleared") is not True:
        raise ModelRegistryBlockedError(
            "dry_run_envelope.validation_summary.ledger_cleared must be true."
        )

    # Load dataset manifest
    manifest = _load_json(dataset_manifest_path, "dataset_manifest")
    _assert_field_false(manifest, "training_allowed", "dataset_manifest")
    if manifest.get("operator_promotion_required") is not True:
        raise ModelRegistryBlockedError(
            "dataset_manifest.operator_promotion_required must be true."
        )

    # DEP.KEYSTONE ingress gate (optional — verified when supplied)
    dep_ingress_id = None
    dep_evidence_ref = None
    dep_report_ref = None
    dep_govsec_layer = None
    if dep_keystone_ingress_path is not None:
        ingress_rec = load_ingress_record(dep_keystone_ingress_path)
        try:
            assert_training_ingress_allowed(ingress_rec, next_gate="tr05_model_registry")
        except KeystoneIngressError as exc:
            raise ModelRegistryBlockedError(
                f"DEP.KEYSTONE ingress check failed: {exc}"
            ) from exc
        dep_ingress_id  = ingress_rec.get("dep_keystone_ingress_id")
        dep_evidence_ref = ingress_rec.get("keystone_evidence_ref")
        dep_report_ref  = ingress_rec.get("keystone_verification_report_ref")
        dep_govsec_layer = ingress_rec.get("govsec_layer")

    # Extract provenance from envelope and manifest
    job_intent  = envelope.get("job_intent", {})
    source_id   = job_intent.get("source_id", "") or ""
    requested_use = job_intent.get("requested_use", "") or ""
    dry_run_id  = envelope.get("dry_run_id", "") or ""
    dataset_id  = (
        manifest.get("dataset_id", "")
        or envelope.get("source_dataset_manifest_id", "")
        or ""
    )

    # Try to recover ledger_entry_id from audit_record.json in same dir
    ledger_entry_id = None
    audit_path = envelope_path.parent / "audit_record.json"
    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            ledger_entry_id = audit.get("ledger_entry_id")
        except (json.JSONDecodeError, OSError):
            pass

    # Build reference strings
    source_registry_ref = (
        f"source_registry:{source_id}:{Path(source_registry_path).name}"
        if source_registry_path and source_id
        else (f"source_registry:{source_id}" if source_id else None)
    )
    clearance_ledger_ref = (
        f"clearance_ledger:{ledger_entry_id}:{Path(clearance_ledger_path).name}"
        if clearance_ledger_path and ledger_entry_id
        else (
            f"clearance_ledger:{ledger_entry_id}" if ledger_entry_id
            else (f"clearance_ledger:source:{source_id}" if clearance_ledger_path else None)
        )
    )

    # Deterministic artifact ID
    artifact_id = _model_artifact_id(dry_run_id, dataset_id, source_id)
    now = _now_utc()

    # Build and validate lineage record
    lineage = build_lineage_record(
        artifact_id=artifact_id,
        artifact_type="dry_run_adapter_candidate",
        dep_keystone_ingress_refs=[dep_ingress_id] if dep_ingress_id else [],
        keystone_evidence_refs=[dep_evidence_ref] if dep_evidence_ref else [],
        keystone_verification_report_refs=[dep_report_ref] if dep_report_ref else [],
        source_registry_refs=[source_registry_ref] if source_registry_ref else [],
        clearance_ledger_refs=[clearance_ledger_ref] if clearance_ledger_ref else [],
        dataset_manifest_refs=[f"dataset:{dataset_id}"] if dataset_id else [],
        dry_run_envelope_refs=[f"dry_run:{dry_run_id}"] if dry_run_id else [],
        notes=(
            f"source_id={source_id!r}, requested_use={requested_use!r}, "
            f"ledger_entry_id={ledger_entry_id!r}, dataset_id={dataset_id!r}, "
            f"dry_run_id={dry_run_id!r}, dep_keystone_ingress_id={dep_ingress_id!r}, "
            f"govsec_layer={dep_govsec_layer!r}"
        ),
    )
    validate_lineage_record(lineage)

    checksum_manifest = _sha256_json(lineage)

    entry = {
        "model_artifact_id":               artifact_id,
        "artifact_type":                   "dry_run_adapter_candidate",
        "artifact_status":                 "dry_run_only",
        "created_at":                      now,
        "created_by":                      created_by,
        "lineage_record_id":               lineage["lineage_record_id"],
        "base_model_reference":            None,
        "adapter_reference":               None,
        "dep_keystone_ingress_ref":        dep_ingress_id,
        "keystone_evidence_ref":           dep_evidence_ref,
        "keystone_verification_report_ref": dep_report_ref,
        "dataset_manifest_ref":            f"dataset:{dataset_id}" if dataset_id else None,
        "dry_run_envelope_ref":            f"dry_run:{dry_run_id}" if dry_run_id else None,
        "training_job_contract_ref":       None,
        "evaluation_ref":                  None,
        "promotion_status":                "not_promoted",

        # Hard constants — never changeable
        "training_allowed":                False,
        "model_weights_present":           False,
        "runtime_deployment_allowed":      False,
        "store1_write_allowed":            False,
        "external_calls_allowed":          False,
        "operator_promotion_required":     True,

        "checksum_manifest":               checksum_manifest,
        "lineage":                         lineage,
        "provenance": {
            "source_id":       source_id,
            "requested_use":   requested_use,
            "ledger_entry_id": ledger_entry_id,
            "dataset_id":      dataset_id,
            "dry_run_id":      dry_run_id,
            "govsec_layer":    dep_govsec_layer,
        },
        "notes": (
            "TR-05 dry-run adapter candidate. Metadata only. "
            "No model weights. No real training. TR-06 not started."
        ),
    }

    # Belt-and-suspenders invariant checks
    assert entry["training_allowed"] is False,           "INVARIANT: training_allowed"
    assert entry["model_weights_present"] is False,      "INVARIANT: model_weights_present"
    assert entry["runtime_deployment_allowed"] is False, "INVARIANT: runtime_deployment_allowed"
    assert entry["store1_write_allowed"] is False,       "INVARIANT: store1_write_allowed"
    assert entry["external_calls_allowed"] is False,     "INVARIANT: external_calls_allowed"
    assert entry["operator_promotion_required"] is True, "INVARIANT: operator_promotion_required"
    assert entry["promotion_status"] == "not_promoted",  "INVARIANT: promotion_status"

    registry["entries"].append(entry)
    return registry


def _assert_field_false(obj: dict, field: str, label: str) -> None:
    if obj.get(field) is not False:
        raise ModelRegistryBlockedError(f"{label}.{field} must be false.")


def _assert_field_true(obj: dict, field: str, label: str) -> None:
    if obj.get(field) is not True:
        raise ModelRegistryBlockedError(f"{label}.{field} must be true.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="model_registry.py",
        description=(
            "TR-05: LOGOS ASF metadata-only model registry and lineage. "
            "No real training. No model weights. TR-06 not started."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    # init
    init_p = sub.add_parser("init", help="Create an empty model registry.")
    init_p.add_argument("--out", required=True, help="Output path for the new registry JSON.")
    init_p.add_argument("--operator-id", default="REGISTRY_OPERATOR", dest="operator_id")

    # register-dry-run
    reg_p = sub.add_parser(
        "register-dry-run", help="Register a TR-04B dry-run envelope as a candidate."
    )
    reg_p.add_argument("--registry", required=True, help="Path to existing registry JSON.")
    reg_p.add_argument("--dry-run-envelope", required=True, dest="dry_run_envelope",
                       help="Path to TR-04B dry_run_envelope.json.")
    reg_p.add_argument("--dataset-manifest", required=True, dest="dataset_manifest",
                       help="Path to TR-03 manifest.json.")
    reg_p.add_argument("--dep-keystone-ingress", default=None, dest="dep_keystone_ingress",
                       help="Path to DEP.KEYSTONE ingress record JSON (optional).")
    reg_p.add_argument("--out", required=True, help="Output path for updated registry JSON.")
    reg_p.add_argument("--operator-id", default="REGISTRY_OPERATOR", dest="operator_id")

    # summarize
    sum_p = sub.add_parser("summarize", help="Print a summary of a registry.")
    sum_p.add_argument("--registry", required=True, help="Path to registry JSON.")

    return p


def main(argv=None) -> None:
    args = _build_arg_parser().parse_args(argv)

    if args.command == "init":
        registry = create_empty_registry()
        save_registry(registry, args.out)
        print(f"Model Registry {REGISTRY_VERSION}")
        print(f"  Created : {args.out}")
        print(f"  Entries : 0")
        print("  No real training. No model weights. TR-06 not started.")

    elif args.command == "register-dry-run":
        registry = load_registry(args.registry)
        register_dry_run_candidate(
            registry=registry,
            dry_run_envelope_path=args.dry_run_envelope,
            dataset_manifest_path=args.dataset_manifest,
            dep_keystone_ingress_path=args.dep_keystone_ingress,
            created_by=args.operator_id,
        )
        save_registry(registry, args.out)
        summary = summarize_registry(registry)
        print(f"Model Registry {REGISTRY_VERSION}")
        print(f"  Total entries : {summary['total_entries']}")
        print(f"  By status     : {summary['by_artifact_status']}")
        print(f"  By promotion  : {summary['by_promotion_status']}")
        print(f"  Output        : {args.out}")
        print("  No real training. No model weights. TR-06 not started.")

    elif args.command == "summarize":
        registry = load_registry(args.registry)
        summary = summarize_registry(registry)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
