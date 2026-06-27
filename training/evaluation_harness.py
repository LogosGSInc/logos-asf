"""
TR-06A Metadata-Only Evaluation Harness.

Architecture
============
TR-06A sits between TR-05 (model registry) and TR-06B (future live behavioral evals):

  TR-05 Model Registry
    ↓  (registered dry_run_adapter_candidate, promotion_status=not_promoted)
  TR-06A Evaluation Harness  ← this module
    ↓  (EVALUATION_REPORT per gate, promotion_blocked=True always)
  [operator review]
    ↓  (future)
  TR-06B Live Behavioral Evaluation  ← NOT started here
    ↓  (future)
  TR-07 Shadow/Canary                ← NOT started here

TR-06A evaluates governance metadata, provenance completeness, and structural
invariants. It does not run model inference, load model weights, train a model,
promote any candidate, write to Store 1, or make external calls.

Hard invariants
===============
- promotion_blocked is always True in every report.
- promotion_decision_emitted is always False in every report.
- metadata_only is always True in every report.
- operator_review_required is always True in every report.
- No candidate with promotion_status != "not_promoted" may be evaluated.
- No candidate with model_weights_present=True may be evaluated.
- No candidate with training_allowed=True may be evaluated.
- No candidate containing model_weights_path or adapter_checkpoint_path may be evaluated.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0.0"

EVALUATION_GATES = frozenset({
    "constitutional_fidelity",
    "haap_refusal_behavior",
    "routing_correctness",
    "audit_safe_json_ir_output",
    "store1_govmem_boundary_preservation",
    "dep_keystone_govsec_provenance_completeness",
    "source_registry_clearance_completeness",
    "clearance_ledger_completeness",
    "dry_run_integrity",
    "synthetic_provenance_integrity",
    "promotion_blocking_invariants",
})

VALID_RESULTS = frozenset({"pass", "fail", "block", "not_evaluated"})

REQUIRED_REPORT_FIELDS = frozenset({
    "evaluation_report_id",
    "schema_version",
    "created_at",
    "candidate_artifact_id",
    "candidate_lineage_record_id",
    "evaluation_gate",
    "result",
    "requires_live_inference",
    "metadata_only",
    "evidence",
    "promotion_blocked",
    "promotion_decision_emitted",
    "operator_review_required",
    "evaluated_by",
    "notes",
})

_FORBIDDEN_CANDIDATE_KEYS = frozenset({
    "model_weights_path",
    "adapter_checkpoint_path",
})

_BLOCKED_CANDIDATE_FLAGS = {
    "training_allowed": True,
    "model_weights_present": True,
    "runtime_deployment_allowed": True,
    "store1_write_allowed": True,
    "external_calls_allowed": True,
}


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class EvaluationHarnessError(Exception):
    pass


class EvaluationCandidateError(EvaluationHarnessError):
    pass


class EvaluationGateError(EvaluationHarnessError):
    pass


class EvaluationReportError(EvaluationHarnessError):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _evaluation_report_id(artifact_id: str, gate_name: str, gate_result: dict) -> str:
    payload = {
        "candidate_artifact_id": artifact_id,
        "gate": gate_name,
        "result": gate_result.get("result"),
        "evidence": gate_result.get("evidence", {}),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "ER-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _assert_candidate_safe(candidate: dict) -> None:
    artifact_id = candidate.get("model_artifact_id", "<unknown>")

    if candidate.get("promotion_status") != "not_promoted":
        raise EvaluationCandidateError(
            f"Candidate {artifact_id!r}: promotion_status={candidate.get('promotion_status')!r}. "
            "Only not_promoted candidates may be evaluated. TR-06A cannot evaluate promoted "
            "or promotion-pending candidates."
        )
    for flag, bad_value in _BLOCKED_CANDIDATE_FLAGS.items():
        if candidate.get(flag) == bad_value:
            raise EvaluationCandidateError(
                f"Candidate {artifact_id!r}: {flag}={bad_value!r}. "
                "TR-06A refuses candidates with unsafe governance flags."
            )
    for forbidden_key in _FORBIDDEN_CANDIDATE_KEYS:
        if forbidden_key in candidate:
            raise EvaluationCandidateError(
                f"Candidate {artifact_id!r}: forbidden field {forbidden_key!r} present. "
                "TR-06A does not operate on candidates with model weight or adapter paths."
            )


# ---------------------------------------------------------------------------
# Public API — loading
# ---------------------------------------------------------------------------

def load_registry_candidate(registry_path: str, candidate_artifact_id: str) -> dict:
    """Load and safety-check a single registry entry by model_artifact_id."""
    path = Path(registry_path)
    if not path.exists():
        raise EvaluationHarnessError(f"Registry file not found: {registry_path!r}")
    registry = json.loads(path.read_text(encoding="utf-8"))
    for entry in registry.get("entries", []):
        if entry.get("model_artifact_id") == candidate_artifact_id:
            _assert_candidate_safe(entry)
            return entry
    raise EvaluationCandidateError(
        f"Candidate {candidate_artifact_id!r} not found in registry {registry_path!r}."
    )


def load_lineage_record_from_candidate(candidate: dict) -> dict | None:
    """Return the lineage record embedded in the registry entry, or None."""
    return candidate.get("lineage")


# ---------------------------------------------------------------------------
# Gate stubs
# ---------------------------------------------------------------------------

def _gate_constitutional_fidelity(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    issues = []
    evidence = {}

    dk_refs = lin.get("dep_keystone_ingress_refs") or []
    evidence["dep_keystone_ingress_refs_count"] = len(dk_refs)
    if not dk_refs:
        issues.append("dep_keystone_ingress_refs is empty")

    src_refs = lin.get("source_registry_refs") or []
    evidence["source_registry_refs_count"] = len(src_refs)
    if not src_refs:
        issues.append("source_registry_refs is empty")

    led_refs = lin.get("clearance_ledger_refs") or []
    evidence["clearance_ledger_refs_count"] = len(led_refs)
    if not led_refs:
        issues.append("clearance_ledger_refs is empty")

    gov = lin.get("governance_flags") or {}
    evidence["governance_flags"] = {
        k: gov.get(k) for k in (
            "training_allowed", "model_weights_present",
            "store1_write_allowed", "runtime_deployment_allowed",
        )
    }
    for flag in ("training_allowed", "model_weights_present",
                 "store1_write_allowed", "runtime_deployment_allowed"):
        if gov.get(flag) is not False:
            issues.append(f"governance_flags.{flag} is not false")

    evidence["issues"] = issues
    return {
        "gate": "constitutional_fidelity",
        "result": "pass" if not issues else "fail",
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only check: governance refs and flags. "
            "Does not test live constitutional behavior. "
            + (f"Issues: {issues}" if issues else "All checks passed.")
        ),
    }


def _gate_haap_refusal_behavior(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    prov = candidate.get("provenance") or {}
    issues = []
    evidence = {}

    dk_refs = lin.get("dep_keystone_ingress_refs") or []
    evidence["dep_keystone_ingress_refs_count"] = len(dk_refs)
    if not dk_refs:
        issues.append("dep_keystone_ingress_refs is empty — HAAP/GovSec connection not in lineage")

    govsec_layer = prov.get("govsec_layer")
    evidence["govsec_layer"] = govsec_layer
    if not govsec_layer:
        issues.append("provenance.govsec_layer is missing")

    evidence["issues"] = issues
    return {
        "gate": "haap_refusal_behavior",
        "result": "pass" if not issues else "fail",
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only provenance check: HAAP/GovSec Layer Zero lineage present. "
            "Does NOT claim live refusal behavior has been tested. "
            "Live refusal testing requires TR-06B behavioral evaluation. "
            + (f"Issues: {issues}" if issues else "HAAP provenance chain present.")
        ),
    }


def _gate_routing_correctness(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    prov = candidate.get("provenance") or {}
    issues = []
    evidence = {}

    artifact_type = candidate.get("artifact_type")
    evidence["artifact_type"] = artifact_type
    if artifact_type != "dry_run_adapter_candidate":
        issues.append(
            f"artifact_type={artifact_type!r} is not dry_run_adapter_candidate"
        )

    source_id = prov.get("source_id")
    evidence["source_id"] = source_id
    if not source_id:
        issues.append("provenance.source_id is missing")

    requested_use = prov.get("requested_use")
    evidence["requested_use"] = requested_use
    if not requested_use:
        issues.append("provenance.requested_use is missing")

    dry_refs = lin.get("dry_run_envelope_refs") or []
    evidence["dry_run_envelope_refs_count"] = len(dry_refs)
    if not dry_refs:
        issues.append("lineage.dry_run_envelope_refs is empty")

    ds_refs = lin.get("dataset_manifest_refs") or []
    evidence["dataset_manifest_refs_count"] = len(ds_refs)
    if not ds_refs:
        issues.append("lineage.dataset_manifest_refs is empty")

    evidence["issues"] = issues
    return {
        "gate": "routing_correctness",
        "result": "pass" if not issues else "fail",
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only check: artifact_type, source_id, requested_use, "
            "dry-run and dataset refs are internally consistent. "
            "Does NOT test live routing behavior. "
            + (f"Issues: {issues}" if issues else "Routing metadata consistent.")
        ),
    }


def _gate_audit_safe_json_ir_output(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    issues = []
    evidence = {}

    lineage_record_id = candidate.get("lineage_record_id")
    evidence["lineage_record_id"] = lineage_record_id
    if not lineage_record_id:
        issues.append("lineage_record_id is missing — no audit anchor")

    checksum = candidate.get("checksum_manifest")
    evidence["checksum_manifest_present"] = bool(checksum)
    if not checksum:
        issues.append("checksum_manifest is missing")

    lineage_hash = lin.get("lineage_hash")
    evidence["lineage_hash_present"] = bool(lineage_hash)
    if not lineage_hash:
        issues.append("lineage.lineage_hash is missing")

    notes_text = candidate.get("notes") or ""
    evidence["notes_length"] = len(notes_text)
    if len(notes_text) > 4096:
        issues.append(
            f"notes field length={len(notes_text)} exceeds 4096 chars — "
            "may contain raw prompt/example text"
        )

    evidence["issues"] = issues
    return {
        "gate": "audit_safe_json_ir_output",
        "result": "pass" if not issues else "fail",
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only check: audit anchors (lineage_record_id, checksum_manifest, "
            "lineage_hash) present; notes field within safe size. "
            "Does NOT inspect model output. "
            + (f"Issues: {issues}" if issues else "Audit anchors present.")
        ),
    }


def _gate_store1_govmem_boundary_preservation(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    gov = lin.get("governance_flags") or {}
    violations = []
    evidence = {}

    for flag in ("store1_write_allowed", "external_calls_allowed"):
        top_val = candidate.get(flag)
        gov_val = gov.get(flag)
        evidence[f"candidate.{flag}"] = top_val
        evidence[f"lineage.governance_flags.{flag}"] = gov_val
        if top_val is not False:
            violations.append(f"candidate.{flag}={top_val!r} must be false")
        if gov_val is not False:
            violations.append(f"lineage.governance_flags.{flag}={gov_val!r} must be false")

    evidence["violations"] = violations
    result = "block" if violations else "pass"
    return {
        "gate": "store1_govmem_boundary_preservation",
        "result": result,
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only check: store1_write_allowed=false and external_calls_allowed=false "
            "in both candidate and lineage governance_flags. Violations → block. "
            + (f"Violations: {violations}" if violations else "Store 1 / GovMem boundary preserved.")
        ),
    }


def _gate_dep_keystone_govsec_provenance_completeness(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    issues = []
    evidence = {}

    for field in (
        "dep_keystone_ingress_ref",
        "dep_keystone_evidence_sha256_ref",
        "dep_keystone_verification_report_ref",
    ):
        val = candidate.get(field)
        evidence[f"candidate.{field}"] = val
        if not val:
            issues.append(f"candidate.{field} is missing or empty")

    for arr_field in (
        "dep_keystone_ingress_refs",
        "dep_keystone_evidence_sha256_refs",
        "dep_keystone_verification_report_refs",
    ):
        arr = lin.get(arr_field) or []
        evidence[f"lineage.{arr_field}_count"] = len(arr)
        if not arr:
            issues.append(f"lineage.{arr_field} is empty")

    evidence["issues"] = issues
    return {
        "gate": "dep_keystone_govsec_provenance_completeness",
        "result": "fail" if issues else "pass",
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only check: DEP.KEYSTONE ingress, evidence, and verification-report refs "
            "present in both candidate and lineage. "
            + (f"Issues: {issues}" if issues else "DEP.KEYSTONE provenance complete.")
        ),
    }


def _gate_source_registry_clearance_completeness(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    prov = candidate.get("provenance") or {}
    issues = []
    evidence = {}

    src_refs = lin.get("source_registry_refs") or []
    evidence["lineage.source_registry_refs_count"] = len(src_refs)
    if not src_refs:
        issues.append("lineage.source_registry_refs is empty")

    source_id = prov.get("source_id")
    evidence["provenance.source_id"] = source_id
    if not source_id:
        issues.append("provenance.source_id is missing")

    evidence["issues"] = issues
    return {
        "gate": "source_registry_clearance_completeness",
        "result": "fail" if issues else "pass",
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only check: source_registry_refs in lineage and source_id in provenance. "
            + (f"Issues: {issues}" if issues else "Source registry clearance refs complete.")
        ),
    }


def _gate_clearance_ledger_completeness(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    prov = candidate.get("provenance") or {}
    issues = []
    evidence = {}

    led_refs = lin.get("clearance_ledger_refs") or []
    evidence["lineage.clearance_ledger_refs_count"] = len(led_refs)
    if not led_refs:
        issues.append("lineage.clearance_ledger_refs is empty")

    ledger_entry_id = prov.get("ledger_entry_id")
    evidence["provenance.ledger_entry_id"] = ledger_entry_id
    if not ledger_entry_id:
        issues.append("provenance.ledger_entry_id is missing")

    evidence["issues"] = issues
    return {
        "gate": "clearance_ledger_completeness",
        "result": "fail" if issues else "pass",
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only check: clearance_ledger_refs in lineage and ledger_entry_id in provenance. "
            + (f"Issues: {issues}" if issues else "Clearance ledger refs complete.")
        ),
    }


def _gate_dry_run_integrity(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    gov = lin.get("governance_flags") or {}
    violations = []
    issues = []
    evidence = {}

    dry_refs = lin.get("dry_run_envelope_refs") or []
    evidence["lineage.dry_run_envelope_refs_count"] = len(dry_refs)
    if not dry_refs:
        issues.append("lineage.dry_run_envelope_refs is empty — no dry-run anchor")

    for flag in (
        "training_allowed", "model_weights_present",
        "runtime_deployment_allowed", "store1_write_allowed", "external_calls_allowed",
    ):
        top_val = candidate.get(flag)
        gov_val = gov.get(flag)
        evidence[f"candidate.{flag}"] = top_val
        evidence[f"lineage.governance_flags.{flag}"] = gov_val
        if top_val is not False:
            violations.append(f"candidate.{flag}={top_val!r} must be false")
        if gov_val is not False:
            violations.append(f"lineage.governance_flags.{flag}={gov_val!r} must be false")

    evidence["violations"] = violations
    evidence["issues"] = issues

    if violations:
        result = "block"
    elif issues:
        result = "fail"
    else:
        result = "pass"

    return {
        "gate": "dry_run_integrity",
        "result": result,
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only check: dry_run_envelope_refs present; all governance flags deny-by-default. "
            "Governance flag violations → block. Missing refs → fail. "
            + (f"Violations: {violations}. Issues: {issues}" if violations or issues else "Dry-run integrity confirmed.")
        ),
    }


def _gate_synthetic_provenance_integrity(candidate, lineage_record=None, context=None):
    lin = lineage_record or {}
    evidence = {}

    syn_manifest_refs = lin.get("synthetic_manifest_refs") or []
    syn_bridge_refs = lin.get("synthetic_review_bridge_refs") or []
    evidence["lineage.synthetic_manifest_refs_count"] = len(syn_manifest_refs)
    evidence["lineage.synthetic_review_bridge_refs_count"] = len(syn_bridge_refs)

    has_synthetic = bool(syn_manifest_refs or syn_bridge_refs)
    evidence["has_synthetic_lineage"] = has_synthetic

    if not has_synthetic:
        return {
            "gate": "synthetic_provenance_integrity",
            "result": "not_evaluated",
            "requires_live_inference": False,
            "metadata_only": True,
            "evidence": evidence,
            "notes": (
                "Candidate has no synthetic_manifest_refs or synthetic_review_bridge_refs. "
                "Synthetic provenance integrity check is not applicable."
            ),
        }

    issues = []
    for ref in syn_manifest_refs:
        if not isinstance(ref, str) or not ref.strip():
            issues.append(f"synthetic_manifest_refs contains invalid entry: {ref!r}")
    for ref in syn_bridge_refs:
        if not isinstance(ref, str) or not ref.strip():
            issues.append(f"synthetic_review_bridge_refs contains invalid entry: {ref!r}")

    evidence["issues"] = issues
    return {
        "gate": "synthetic_provenance_integrity",
        "result": "fail" if issues else "pass",
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Metadata-only check: synthetic refs are non-empty strings. "
            "Does not validate synthetic content provenance fields "
            "(synthetic_origin, prompt_hash, generation_agent_id) — "
            "those require TR-06B fixture evaluation. "
            + (f"Issues: {issues}" if issues else "Synthetic ref entries are non-empty strings.")
        ),
    }


def _gate_promotion_blocking_invariants(candidate, lineage_record=None, context=None):
    violations = []
    evidence = {}

    for field, expected in (
        ("promotion_status", "not_promoted"),
        ("training_allowed", False),
        ("model_weights_present", False),
        ("runtime_deployment_allowed", False),
        ("store1_write_allowed", False),
        ("external_calls_allowed", False),
        ("operator_promotion_required", True),
    ):
        val = candidate.get(field)
        evidence[field] = val
        if val != expected:
            violations.append(f"{field}={val!r}, expected {expected!r}")

    for forbidden_key in _FORBIDDEN_CANDIDATE_KEYS:
        if forbidden_key in candidate:
            violations.append(f"forbidden field {forbidden_key!r} present in candidate")

    evidence["violations"] = violations
    result = "block" if violations else "pass"
    return {
        "gate": "promotion_blocking_invariants",
        "result": result,
        "requires_live_inference": False,
        "metadata_only": True,
        "evidence": evidence,
        "notes": (
            "Hard check: all promotion-blocking invariants must hold. "
            "Any violation → block. "
            + (f"Violations: {violations}" if violations else "All promotion-blocking invariants hold.")
        ),
    }


_GATE_STUBS = {
    "constitutional_fidelity":                    _gate_constitutional_fidelity,
    "haap_refusal_behavior":                       _gate_haap_refusal_behavior,
    "routing_correctness":                         _gate_routing_correctness,
    "audit_safe_json_ir_output":                   _gate_audit_safe_json_ir_output,
    "store1_govmem_boundary_preservation":         _gate_store1_govmem_boundary_preservation,
    "dep_keystone_govsec_provenance_completeness": _gate_dep_keystone_govsec_provenance_completeness,
    "source_registry_clearance_completeness":      _gate_source_registry_clearance_completeness,
    "clearance_ledger_completeness":               _gate_clearance_ledger_completeness,
    "dry_run_integrity":                           _gate_dry_run_integrity,
    "synthetic_provenance_integrity":              _gate_synthetic_provenance_integrity,
    "promotion_blocking_invariants":               _gate_promotion_blocking_invariants,
}

assert set(_GATE_STUBS.keys()) == EVALUATION_GATES, (
    "Gate stub registry does not match EVALUATION_GATES constant."
)


# ---------------------------------------------------------------------------
# Public API — evaluation
# ---------------------------------------------------------------------------

def run_evaluation_gate(
    candidate: dict,
    gate_name: str,
    registry=None,
    lineage_record=None,
    context=None,
) -> dict:
    """Run a single named gate stub against a candidate."""
    if gate_name not in EVALUATION_GATES:
        raise EvaluationGateError(
            f"Unknown gate {gate_name!r}. Valid gates: {sorted(EVALUATION_GATES)}"
        )
    lineage = lineage_record or load_lineage_record_from_candidate(candidate)
    gate_fn = _GATE_STUBS[gate_name]
    return gate_fn(candidate, lineage_record=lineage, context=context)


def run_all_metadata_gates(
    candidate: dict,
    registry=None,
    lineage_record=None,
    context=None,
) -> list:
    """Run all defined gate stubs against a candidate. Returns one dict per gate."""
    lineage = lineage_record or load_lineage_record_from_candidate(candidate)
    results = []
    for gate_name in sorted(EVALUATION_GATES):
        gate_fn = _GATE_STUBS[gate_name]
        results.append(gate_fn(candidate, lineage_record=lineage, context=context))
    return results


def build_evaluation_report(
    candidate: dict,
    gate_result: dict,
    evaluated_by: str = "TR06A_METADATA_HARNESS",
) -> dict:
    """Wrap a gate result into a typed EVALUATION_REPORT."""
    artifact_id = candidate.get("model_artifact_id", "")
    gate_name = gate_result.get("gate", "")
    report_id = _evaluation_report_id(artifact_id, gate_name, gate_result)
    return {
        "evaluation_report_id":    report_id,
        "schema_version":          SCHEMA_VERSION,
        "created_at":              _now_utc(),
        "candidate_artifact_id":   artifact_id,
        "candidate_lineage_record_id": candidate.get("lineage_record_id", ""),
        "evaluation_gate":         gate_name,
        "result":                  gate_result.get("result", "not_evaluated"),
        "requires_live_inference": gate_result.get("requires_live_inference", False),
        "metadata_only":           True,
        "evidence":                gate_result.get("evidence", {}),
        "promotion_blocked":       True,
        "promotion_decision_emitted": False,
        "operator_review_required": True,
        "evaluated_by":            evaluated_by,
        "notes":                   gate_result.get("notes", ""),
    }


def validate_evaluation_report(report: dict) -> dict:
    """Validate the structural invariants of an evaluation report. Raises EvaluationReportError."""
    errors = []
    for field in sorted(REQUIRED_REPORT_FIELDS):
        if field not in report:
            errors.append(f"missing required field: {field!r}")
    if errors:
        raise EvaluationReportError(
            f"Evaluation report validation failed ({len(errors)} error(s)):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
    if report.get("promotion_blocked") is not True:
        raise EvaluationReportError("promotion_blocked must be true")
    if report.get("promotion_decision_emitted") is not False:
        raise EvaluationReportError("promotion_decision_emitted must be false")
    if report.get("metadata_only") is not True:
        raise EvaluationReportError("metadata_only must be true")
    if report.get("operator_review_required") is not True:
        raise EvaluationReportError("operator_review_required must be true")
    if report.get("evaluation_gate") not in EVALUATION_GATES:
        raise EvaluationReportError(
            f"invalid evaluation_gate: {report.get('evaluation_gate')!r}"
        )
    if report.get("result") not in VALID_RESULTS:
        raise EvaluationReportError(
            f"invalid result: {report.get('result')!r}"
        )
    return {
        "valid": True,
        "evaluation_report_id": report.get("evaluation_report_id"),
        "evaluation_gate":      report.get("evaluation_gate"),
        "result":               report.get("result"),
    }


def save_evaluation_report(report: dict, out_dir: str) -> Path:
    """Write a single evaluation report to {out_dir}/er_{report_id}.json."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_id = report["evaluation_report_id"]
    path = out / f"er_{report_id}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def summarize_evaluation_reports(reports: list) -> dict:
    """Aggregate a list of evaluation reports into a summary dict."""
    by_gate = {}
    by_result: dict = {}
    any_block = False
    all_pass = True

    for r in reports:
        gate = r.get("evaluation_gate", "unknown")
        result = r.get("result", "unknown")
        by_gate[gate] = result
        by_result[result] = by_result.get(result, 0) + 1
        if result == "block":
            any_block = True
        if result != "pass":
            all_pass = False

    return {
        "total_reports":       len(reports),
        "by_gate":             by_gate,
        "by_result":           by_result,
        "any_block":           any_block,
        "all_pass":            all_pass,
        "promotion_blocked":   True,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_run_gate(args):
    candidate = load_registry_candidate(args.registry, args.candidate_artifact_id)
    lineage = load_lineage_record_from_candidate(candidate)
    gate_result = run_evaluation_gate(
        candidate, args.gate, lineage_record=lineage
    )
    report = build_evaluation_report(candidate, gate_result, evaluated_by=args.evaluated_by)
    validate_evaluation_report(report)
    saved_path = save_evaluation_report(report, args.out_dir)
    print(json.dumps({
        "evaluation_report_id": report["evaluation_report_id"],
        "gate":                 report["evaluation_gate"],
        "result":               report["result"],
        "promotion_blocked":    report["promotion_blocked"],
        "saved_to":             str(saved_path),
    }, indent=2))


def _cli_run_all(args):
    candidate = load_registry_candidate(args.registry, args.candidate_artifact_id)
    lineage = load_lineage_record_from_candidate(candidate)
    gate_results = run_all_metadata_gates(candidate, lineage_record=lineage)
    reports = []
    saved = []
    for gr in gate_results:
        rpt = build_evaluation_report(candidate, gr, evaluated_by=args.evaluated_by)
        validate_evaluation_report(rpt)
        saved_path = save_evaluation_report(rpt, args.out_dir)
        reports.append(rpt)
        saved.append(str(saved_path))
    summary = summarize_evaluation_reports(reports)
    print(json.dumps({
        "summary":   summary,
        "saved":     saved,
    }, indent=2))


def _cli_summarize(args):
    reports_dir = Path(args.reports_dir)
    reports = []
    for p in sorted(reports_dir.glob("er_*.json")):
        reports.append(json.loads(p.read_text(encoding="utf-8")))
    summary = summarize_evaluation_reports(reports)
    print(json.dumps(summary, indent=2))


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="evaluation_harness",
        description="TR-06A metadata-only evaluation harness.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_gate = sub.add_parser("run-gate", help="Run a single evaluation gate.")
    run_gate.add_argument("--registry", required=True)
    run_gate.add_argument("--candidate-artifact-id", required=True, dest="candidate_artifact_id")
    run_gate.add_argument("--gate", required=True)
    run_gate.add_argument("--out-dir", required=True, dest="out_dir")
    run_gate.add_argument("--evaluated-by", default="TR06A_METADATA_HARNESS", dest="evaluated_by")
    run_gate.set_defaults(func=_cli_run_gate)

    run_all = sub.add_parser("run-all", help="Run all metadata evaluation gates.")
    run_all.add_argument("--registry", required=True)
    run_all.add_argument("--candidate-artifact-id", required=True, dest="candidate_artifact_id")
    run_all.add_argument("--out-dir", required=True, dest="out_dir")
    run_all.add_argument("--evaluated-by", default="TR06A_METADATA_HARNESS", dest="evaluated_by")
    run_all.set_defaults(func=_cli_run_all)

    summarize = sub.add_parser("summarize", help="Summarize evaluation reports from a directory.")
    summarize.add_argument("--reports-dir", required=True, dest="reports_dir")
    summarize.set_defaults(func=_cli_summarize)

    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except EvaluationHarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
