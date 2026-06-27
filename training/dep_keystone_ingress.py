"""
LOGOS ASF — TR-04D DEP.KEYSTONE / GovSec V2 Training Ingress Gate v1.0.0
LOGOS Governance Systems Inc.

Provides the DEP.KEYSTONE / GovSec V2 / Layer Zero admissibility gate for
training-source ingress. No source may enter TR-04A, TR-03, TR-04B, or TR-05
without passing this gate.

Recon result (2026-06-27): No pre-existing DEP.KEYSTONE / GovSec training-ingress
gate was found in the LOGOS ASF codebase. A grep of training/, abigail/,
governance-spine/, agents/, and docs/ for DEP, KEYSTONE, Keystone, GovSec,
Layer Zero, Perceptual, admissibility, ingress, trust certificate, sbom, and
related field names returned no matches for a callable training-ingress gate.
DEPT- occurrences were department identifiers only. This module implements the
missing gate.

No real training occurs here. No model weights. No Store 1 writes. TR-05 was
not started.
"""
import json
from pathlib import Path

INGRESS_VERSION = "dep_keystone_ingress:1.0.0"
SCHEMA_VERSION = "1.0.0"

VALID_ADMISSIBILITY_STATUSES = frozenset({
    "draft", "pending", "approved", "rejected", "blocked", "archived",
})
VALID_ADMISSIBILITY_DECISIONS = frozenset({
    "accepted_for_clearance",
    "rejected_at_ingress",
    "blocked_at_ingress",
    "requires_more_evidence",
})
VALID_GOVSEC_LAYERS = frozenset({
    "layer_zero_reality_formation",
    "dep_keystone_supply_chain",
    "training_readiness_ingress",
})
VALID_NEXT_GATES = frozenset({
    "tr04a_source_registry",
    "tr04a_clearance_ledger",
    "synthetic_doctrine",
    "synthetic_review_bridge",
    "tr03_dataset_builder",
    "tr04b_dry_run",
    "tr05_model_registry",
})

_BLOCKED_STATUSES = frozenset({"blocked", "rejected", "archived"})
_PENDING_STATUSES = frozenset({"draft", "pending"})

REQUIRED_FIELDS = frozenset({
    "dep_keystone_ingress_id",
    "schema_version",
    "created_at",
    "source_id",
    "source_name",
    "source_type",
    "classification",
    "admissibility_status",
    "admissibility_decision",
    "keystone_evidence_ref",
    "keystone_verification_report_ref",
    "keystone_sbom_ref",
    "evidence_sha256",
    "artifact_sha256",
    "govsec_layer",
    "reality_formation_input",
    "ingress_actor_id",
    "ingress_actor_role",
    "operator_review_required",
    "training_pipeline_allowed",
    "allowed_next_gates",
    "notes",
})


class KeystoneIngressError(Exception):
    """Base class for DEP.KEYSTONE ingress gate errors."""


class KeystoneIngressValidationError(KeystoneIngressError):
    """Raised when an ingress record is structurally invalid."""


class KeystoneIngressBlockedError(KeystoneIngressError):
    """Raised when an ingress record is in a terminal blocked/rejected/archived state."""


class KeystoneIngressNotAllowedError(KeystoneIngressError):
    """Raised when an ingress record is not cleared for training pipeline entry."""


def load_ingress_record(path) -> dict:
    """Load and parse a DEP.KEYSTONE ingress record from a JSON file."""
    p = Path(path)
    if not p.exists():
        raise KeystoneIngressValidationError(
            f"DEP.KEYSTONE ingress record not found: {p}"
        )
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KeystoneIngressValidationError(
            f"DEP.KEYSTONE ingress record is not valid JSON: {exc}"
        ) from exc


def validate_ingress_record(record: dict) -> dict:
    """
    Structural validation of a DEP.KEYSTONE ingress record.

    Returns {"valid": True, ...} on success.
    Raises KeystoneIngressValidationError on failure.
    """
    errors = []
    for field in sorted(REQUIRED_FIELDS):
        if field not in record:
            errors.append(f"missing required field: {field!r}")
    if errors:
        raise KeystoneIngressValidationError(
            f"DEP.KEYSTONE ingress validation failed ({len(errors)} error(s)):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    status = record.get("admissibility_status")
    if status not in VALID_ADMISSIBILITY_STATUSES:
        raise KeystoneIngressValidationError(
            f"Invalid admissibility_status: {status!r}. "
            f"Valid: {sorted(VALID_ADMISSIBILITY_STATUSES)}"
        )

    decision = record.get("admissibility_decision")
    if decision not in VALID_ADMISSIBILITY_DECISIONS:
        raise KeystoneIngressValidationError(
            f"Invalid admissibility_decision: {decision!r}. "
            f"Valid: {sorted(VALID_ADMISSIBILITY_DECISIONS)}"
        )

    layer = record.get("govsec_layer")
    if layer not in VALID_GOVSEC_LAYERS:
        raise KeystoneIngressValidationError(
            f"Invalid govsec_layer: {layer!r}. Valid: {sorted(VALID_GOVSEC_LAYERS)}"
        )

    for gate in record.get("allowed_next_gates", []):
        if gate not in VALID_NEXT_GATES:
            raise KeystoneIngressValidationError(
                f"Invalid entry in allowed_next_gates: {gate!r}. "
                f"Valid: {sorted(VALID_NEXT_GATES)}"
            )

    return {
        "valid": True,
        "dep_keystone_ingress_id": record.get("dep_keystone_ingress_id"),
        "source_id": record.get("source_id"),
        "admissibility_status": status,
        "admissibility_decision": decision,
    }


def assert_training_ingress_allowed(
    record: dict,
    source_id: str = None,
    next_gate: str = None,
) -> dict:
    """
    Assert that this DEP.KEYSTONE ingress record clears the training pipeline gate.

    Raises KeystoneIngressBlockedError for terminal blocked/rejected/archived states.
    Raises KeystoneIngressNotAllowedError for all other clearance failures.
    Returns a clearance result dict on success.

    Args:
        record:    A DEP.KEYSTONE ingress record dict.
        source_id: If provided, assert the record's source_id matches this value.
        next_gate: If provided, assert it appears in allowed_next_gates.
    """
    ingress_id = record.get("dep_keystone_ingress_id", "<unknown>")
    status = record.get("admissibility_status", "")
    rec_source = record.get("source_id", "")

    if status in _BLOCKED_STATUSES:
        raise KeystoneIngressBlockedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: admissibility_status={status!r}. "
            "Training pipeline entry is permanently blocked."
        )

    if status in _PENDING_STATUSES:
        raise KeystoneIngressNotAllowedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: admissibility_status={status!r}. "
            "Clearance is not complete."
        )

    if status != "approved":
        raise KeystoneIngressNotAllowedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: admissibility_status={status!r}. "
            "Only approved ingress records may enter the training pipeline."
        )

    decision = record.get("admissibility_decision", "")
    if decision != "accepted_for_clearance":
        raise KeystoneIngressNotAllowedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: admissibility_decision={decision!r}. "
            "Must be accepted_for_clearance."
        )

    if not record.get("evidence_sha256", ""):
        raise KeystoneIngressNotAllowedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: evidence_sha256 is missing or empty."
        )

    if not record.get("artifact_sha256", ""):
        raise KeystoneIngressNotAllowedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: artifact_sha256 is missing or empty."
        )

    if not record.get("keystone_evidence_ref", ""):
        raise KeystoneIngressNotAllowedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: keystone_evidence_ref is missing or empty."
        )

    if not record.get("keystone_verification_report_ref", ""):
        raise KeystoneIngressNotAllowedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: keystone_verification_report_ref "
            "is missing or empty."
        )

    if record.get("training_pipeline_allowed") is not True:
        raise KeystoneIngressNotAllowedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: training_pipeline_allowed is not true."
        )

    if source_id is not None and rec_source != source_id:
        raise KeystoneIngressNotAllowedError(
            f"DEP.KEYSTONE ingress {ingress_id!r}: source_id mismatch — "
            f"record has {rec_source!r}, requested {source_id!r}."
        )

    if next_gate is not None:
        allowed = record.get("allowed_next_gates", [])
        if next_gate not in allowed:
            raise KeystoneIngressNotAllowedError(
                f"DEP.KEYSTONE ingress {ingress_id!r}: next_gate={next_gate!r} is not in "
                f"allowed_next_gates={allowed!r}."
            )

    return {
        "cleared": True,
        "dep_keystone_ingress_id": ingress_id,
        "source_id": rec_source,
        "admissibility_status": status,
        "admissibility_decision": decision,
        "next_gate": next_gate,
        "govsec_layer": record.get("govsec_layer"),
        "reality_formation_input": record.get("reality_formation_input"),
    }


def summarize_ingress(record: dict) -> dict:
    """Return an audit-safe summary of an ingress record (no raw evidence content)."""
    return {
        "dep_keystone_ingress_id": record.get("dep_keystone_ingress_id"),
        "source_id": record.get("source_id"),
        "source_name": record.get("source_name"),
        "admissibility_status": record.get("admissibility_status"),
        "admissibility_decision": record.get("admissibility_decision"),
        "govsec_layer": record.get("govsec_layer"),
        "reality_formation_input": record.get("reality_formation_input"),
        "training_pipeline_allowed": record.get("training_pipeline_allowed"),
        "allowed_next_gates": record.get("allowed_next_gates", []),
        "ingress_actor_id": record.get("ingress_actor_id"),
        "ingress_actor_role": record.get("ingress_actor_role"),
        "operator_review_required": record.get("operator_review_required"),
    }
