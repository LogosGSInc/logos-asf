"""
TR-06E: Evaluation Dossier and Readiness Aggregator.

Collects TR-06A metadata evaluation reports, TR-06C live evaluation plans, and
TR-06D deterministic stub execution reports into one sealed, checksum-addressed
evaluation dossier for a single registered Abigail candidate.

TR-06E classifies readiness_state without emitting a promotion decision.
readiness_state='metadata_ready' is NOT promotion eligibility — it means no
blocking evidence was found. Promotion remains blocked.

Pipeline position:
  TR-06A metadata reports  ─┐
  TR-06C live eval plans   ─┼→  TR-06E Evaluation Dossier
  TR-06D stub exec reports ─┘        ↓ readiness_state (no promotion)
                                [future TR-06Z audit seal]
                                      ↓ operator gate
                               [future TR-07 shadow/canary]

Hard constants — always enforced:
  promotion_blocked              = True
  promotion_decision_emitted     = False
  operator_review_required       = True
  real_model_inference_performed = False
  provider_calls_performed       = False
  model_weights_loaded           = False
  model_training_performed       = False
  runtime_deployment_performed   = False
  store1_writes_performed        = False
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0.0"

REQUIRED_DOSSIER_FIELDS = frozenset({
    "evaluation_dossier_id",
    "schema_version",
    "created_at",
    "candidate_artifact_id",
    "candidate_lineage_record_id",
    "source_model_registry_ref",
    "metadata_evaluation_report_refs",
    "live_evaluation_plan_refs",
    "stub_execution_report_refs",
    "gate_summary",
    "stub_execution_summary",
    "readiness_state",
    "readiness_rationale",
    "promotion_blocked",
    "promotion_decision_emitted",
    "operator_review_required",
    "real_model_inference_performed",
    "provider_calls_performed",
    "model_weights_loaded",
    "model_training_performed",
    "runtime_deployment_performed",
    "store1_writes_performed",
    "blocked_actions",
    "dossier_hash",
    "previous_dossier_hash",
    "notes",
})

_BLOCKED_ACTIONS = [
    "model_inference",
    "provider_call",
    "model_weight_load",
    "model_training",
    "store1_write",
    "runtime_deployment",
    "model_promotion",
    "tr07_shadow",
    "tr07_canary",
]

_VALID_READINESS_STATES = frozenset({
    "metadata_ready", "needs_more_evidence", "blocked", "not_evaluated"
})


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class EvaluationDossierError(Exception):
    pass


class EvaluationDossierInputError(EvaluationDossierError):
    pass


class EvaluationDossierValidationError(EvaluationDossierError):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dossier_id(
    candidate_artifact_id: str,
    all_ref_ids: list,
    readiness_state: str,
) -> str:
    raw = (
        f"tr06e-dossier:{candidate_artifact_id}:"
        f"{':'.join(sorted(all_ref_ids))}:{readiness_state}"
    )
    return "ED-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _canonical_content(dossier: dict) -> str:
    """Return canonical JSON for hashing, excluding dossier_hash itself."""
    d = {k: v for k, v in dossier.items() if k != "dossier_hash"}
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def compute_dossier_hash(dossier: dict) -> str:
    """SHA-256 of canonical dossier content (excluding dossier_hash)."""
    return hashlib.sha256(_canonical_content(dossier).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def _reject_forbidden_keys(obj: dict, source_label: str) -> None:
    for key in ("model_weights_path", "adapter_checkpoint_path"):
        if key in obj:
            raise EvaluationDossierInputError(
                f"{source_label} contains forbidden field {key!r}."
            )


def _check_candidate_id(obj: dict, expected: str, source_label: str) -> None:
    actual = obj.get("candidate_artifact_id")
    if actual and actual != expected:
        raise EvaluationDossierInputError(
            f"{source_label} candidate_artifact_id={actual!r} does not match "
            f"dossier candidate {expected!r}. Mixed candidates are not allowed."
        )


def _check_promotion_invariants(obj: dict, source_label: str) -> None:
    if obj.get("promotion_blocked") is False:
        raise EvaluationDossierInputError(
            f"{source_label} has promotion_blocked=false. "
            "Only promotion-blocked inputs are admissible."
        )
    if obj.get("promotion_decision_emitted") is True:
        raise EvaluationDossierInputError(
            f"{source_label} has promotion_decision_emitted=true. "
            "Inputs that emitted a promotion decision cannot be aggregated."
        )


def _check_stub_report_invariants(report: dict, source_label: str) -> None:
    if report.get("real_model_inference_performed") is True:
        raise EvaluationDossierInputError(
            f"{source_label}: real_model_inference_performed=true is not admissible."
        )
    if report.get("provider_calls_performed") is True:
        raise EvaluationDossierInputError(
            f"{source_label}: provider_calls_performed=true is not admissible."
        )
    if report.get("model_weights_loaded") is True:
        raise EvaluationDossierInputError(
            f"{source_label}: model_weights_loaded=true is not admissible."
        )


# ---------------------------------------------------------------------------
# Summarizers
# ---------------------------------------------------------------------------

def summarize_metadata_reports(metadata_reports: list) -> dict:
    """Aggregate gate results across a list of TR-06A evaluation reports.

    Each TR-06A report covers exactly one gate and carries a single 'result' field.
    """
    counts = {"pass": 0, "fail": 0, "block": 0, "not_evaluated": 0}
    for report in (metadata_reports or []):
        r = report.get("result", "not_evaluated")
        if r in counts:
            counts[r] += 1
        else:
            counts["not_evaluated"] += 1
    total = sum(counts.values())
    return {**counts, "total": total}


def summarize_stub_execution_reports(stub_execution_reports: list) -> dict:
    """Aggregate case results across a list of TR-06D stub execution reports."""
    counts = {
        "stub_pass": 0,
        "stub_fail": 0,
        "stub_block": 0,
        "not_evaluated": 0,
        "blocked": 0,
    }
    for report in (stub_execution_reports or []):
        for cr in report.get("case_results", []):
            r = cr.get("result", "not_evaluated")
            if r in counts:
                counts[r] += 1
            else:
                counts["not_evaluated"] += 1
    total = sum(counts.values())
    return {**counts, "total": total}


# ---------------------------------------------------------------------------
# Readiness classifier
# ---------------------------------------------------------------------------

def classify_readiness(gate_summary: dict, stub_execution_summary: dict) -> tuple:
    """Return (readiness_state, rationale) deterministically.

    Rules (in priority order):
      blocked          → any block/stub_block/blocked result, OR forbidden action
      not_evaluated    → zero total evidence across both summaries
      needs_more_evidence → blocks absent but fail/not_evaluated/stub_fail present,
                            or only stub evidence with no metadata reports
      metadata_ready   → no blocks, no fails, metadata gates present
    """
    g = gate_summary
    s = stub_execution_summary

    has_metadata = g.get("total", 0) > 0
    has_stub = s.get("total", 0) > 0

    if g.get("block", 0) > 0:
        return (
            "blocked",
            f"Metadata gate block result present: {g['block']} block(s) across {g['total']} gate result(s).",
        )
    if s.get("stub_block", 0) > 0:
        return (
            "blocked",
            f"Stub execution block result present: {s['stub_block']} stub_block(s) across {s['total']} case result(s).",
        )
    if s.get("blocked", 0) > 0:
        return (
            "blocked",
            f"Stub execution blocked result present: {s['blocked']} blocked case(s). Adapter was rejected.",
        )

    if not has_metadata and not has_stub:
        return (
            "not_evaluated",
            "No evaluation inputs provided. No metadata reports and no stub execution reports.",
        )

    if g.get("fail", 0) > 0 or g.get("not_evaluated", 0) > 0:
        return (
            "needs_more_evidence",
            (
                f"Metadata gates have {g.get('fail', 0)} fail(s) and "
                f"{g.get('not_evaluated', 0)} not_evaluated result(s). "
                "Further evidence or operator review required."
            ),
        )
    if s.get("stub_fail", 0) > 0:
        return (
            "needs_more_evidence",
            f"Stub execution has {s['stub_fail']} stub_fail(s). Further evidence required.",
        )
    if not has_metadata and has_stub:
        return (
            "needs_more_evidence",
            "Only deterministic stub execution evidence present; no metadata evaluation reports.",
        )

    return (
        "metadata_ready",
        (
            "No block results. No fail results. Required metadata reports present. "
            "Stub execution, if present, is deterministic stub only. "
            "readiness_state='metadata_ready' is NOT promotion eligibility."
        ),
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_evaluation_dossier(
    candidate_artifact_id: str,
    metadata_reports: list = None,
    live_eval_plans: list = None,
    stub_execution_reports: list = None,
    source_model_registry_ref: str = None,
    previous_dossier_hash: str = None,
    notes: str = None,
) -> dict:
    """Build a sealed evaluation dossier for one candidate.

    Validates all inputs, summarises gate and stub results, classifies
    readiness_state, and computes dossier_hash over canonical content.
    """
    metadata_reports = list(metadata_reports or [])
    live_eval_plans = list(live_eval_plans or [])
    stub_execution_reports = list(stub_execution_reports or [])

    for i, r in enumerate(metadata_reports):
        label = f"metadata_report[{i}]"
        _reject_forbidden_keys(r, label)
        _check_candidate_id(r, candidate_artifact_id, label)
        _check_promotion_invariants(r, label)

    for i, p in enumerate(live_eval_plans):
        label = f"live_eval_plan[{i}]"
        _reject_forbidden_keys(p, label)
        _check_candidate_id(p, candidate_artifact_id, label)
        _check_promotion_invariants(p, label)

    for i, xr in enumerate(stub_execution_reports):
        label = f"stub_execution_report[{i}]"
        _reject_forbidden_keys(xr, label)
        _check_candidate_id(xr, candidate_artifact_id, label)
        _check_promotion_invariants(xr, label)
        _check_stub_report_invariants(xr, label)

    gate_summary = summarize_metadata_reports(metadata_reports)
    stub_summary = summarize_stub_execution_reports(stub_execution_reports)
    readiness_state, rationale = classify_readiness(gate_summary, stub_summary)

    meta_refs = [r.get("evaluation_report_id", "") for r in metadata_reports]
    plan_refs = [p.get("live_eval_plan_id", "") for p in live_eval_plans]
    stub_refs = [xr.get("execution_report_id", "") for xr in stub_execution_reports]
    all_refs = meta_refs + plan_refs + stub_refs

    dossier_id = _dossier_id(candidate_artifact_id, all_refs, readiness_state)

    lineage_id = ""
    if metadata_reports:
        lineage_id = metadata_reports[0].get("candidate_lineage_record_id", "")
    if not lineage_id and stub_execution_reports:
        lineage_id = stub_execution_reports[0].get("candidate_lineage_record_id", "")

    dossier: dict = {
        "evaluation_dossier_id":          dossier_id,
        "schema_version":                 SCHEMA_VERSION,
        "created_at":                     _now_utc(),
        "candidate_artifact_id":          candidate_artifact_id,
        "candidate_lineage_record_id":    lineage_id,
        "source_model_registry_ref":      source_model_registry_ref or "",
        "metadata_evaluation_report_refs": meta_refs,
        "live_evaluation_plan_refs":      plan_refs,
        "stub_execution_report_refs":     stub_refs,
        "gate_summary":                   gate_summary,
        "stub_execution_summary":         stub_summary,
        "readiness_state":                readiness_state,
        "readiness_rationale":            rationale,
        "promotion_blocked":              True,
        "promotion_decision_emitted":     False,
        "operator_review_required":       True,
        "real_model_inference_performed": False,
        "provider_calls_performed":       False,
        "model_weights_loaded":           False,
        "model_training_performed":       False,
        "runtime_deployment_performed":   False,
        "store1_writes_performed":        False,
        "blocked_actions":                list(_BLOCKED_ACTIONS),
        "dossier_hash":                   "",  # filled below
        "previous_dossier_hash":          previous_dossier_hash,
        "notes": notes or (
            f"TR-06E evaluation dossier for candidate {candidate_artifact_id!r}. "
            f"readiness_state={readiness_state!r}. "
            "Not a promotion decision. Operator review required."
        ),
    }

    dossier["dossier_hash"] = compute_dossier_hash(dossier)
    return dossier


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_evaluation_dossier(dossier: dict) -> dict:
    """Validate a TR-06E dossier. Raises EvaluationDossierValidationError on violations."""
    errors = []
    for field in sorted(REQUIRED_DOSSIER_FIELDS):
        if field not in dossier:
            errors.append(f"missing required field: {field!r}")
    if errors:
        raise EvaluationDossierValidationError(
            f"Dossier validation failed ({len(errors)} error(s)):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    if dossier.get("promotion_blocked") is not True:
        raise EvaluationDossierValidationError("promotion_blocked must be true.")
    if dossier.get("promotion_decision_emitted") is not False:
        raise EvaluationDossierValidationError("promotion_decision_emitted must be false.")
    if dossier.get("operator_review_required") is not True:
        raise EvaluationDossierValidationError("operator_review_required must be true.")
    if dossier.get("real_model_inference_performed") is not False:
        raise EvaluationDossierValidationError("real_model_inference_performed must be false.")
    if dossier.get("provider_calls_performed") is not False:
        raise EvaluationDossierValidationError("provider_calls_performed must be false.")
    if dossier.get("model_weights_loaded") is not False:
        raise EvaluationDossierValidationError("model_weights_loaded must be false.")
    if dossier.get("model_training_performed") is not False:
        raise EvaluationDossierValidationError("model_training_performed must be false.")
    if dossier.get("runtime_deployment_performed") is not False:
        raise EvaluationDossierValidationError("runtime_deployment_performed must be false.")
    if dossier.get("store1_writes_performed") is not False:
        raise EvaluationDossierValidationError("store1_writes_performed must be false.")
    if dossier.get("readiness_state") not in _VALID_READINESS_STATES:
        raise EvaluationDossierValidationError(
            f"readiness_state must be one of {sorted(_VALID_READINESS_STATES)}, "
            f"got {dossier.get('readiness_state')!r}."
        )
    if not dossier.get("blocked_actions"):
        raise EvaluationDossierValidationError("blocked_actions must be a non-empty list.")
    dh = dossier.get("dossier_hash", "")
    if len(dh) != 64:
        raise EvaluationDossierValidationError(
            f"dossier_hash must be a 64-char hex SHA-256, got len={len(dh)}."
        )

    return {
        "valid": True,
        "evaluation_dossier_id": dossier.get("evaluation_dossier_id"),
        "readiness_state":       dossier.get("readiness_state"),
    }


# ---------------------------------------------------------------------------
# Save / load / summarize
# ---------------------------------------------------------------------------

def save_evaluation_dossier(dossier: dict, out_dir: str) -> Path:
    """Validate, save dossier JSON, and write checksums.sha256."""
    validate_evaluation_dossier(dossier)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    dossier_json = json.dumps(dossier, indent=2)
    dossier_id = dossier["evaluation_dossier_id"]
    dossier_path = out / f"ed_{dossier_id}.json"
    dossier_path.write_text(dossier_json, encoding="utf-8")

    sha256 = hashlib.sha256(dossier_json.encode("utf-8")).hexdigest()
    (out / "checksums.sha256").write_text(
        f"{sha256}  ed_{dossier_id}.json\n", encoding="utf-8"
    )
    return dossier_path


def load_json(path: str) -> dict:
    """Load any JSON file (for loading individual evaluation artifacts)."""
    p = Path(path)
    if not p.exists():
        raise EvaluationDossierError(f"File not found: {path!r}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_evaluation_dossier(path: str) -> dict:
    """Load and validate a saved evaluation dossier JSON."""
    dossier = load_json(path)
    validate_evaluation_dossier(dossier)
    return dossier


def summarize_evaluation_dossier(dossier: dict) -> dict:
    """Return a summary dict for an evaluation dossier."""
    gs = dossier.get("gate_summary", {})
    ss = dossier.get("stub_execution_summary", {})
    return {
        "evaluation_dossier_id":          dossier.get("evaluation_dossier_id"),
        "candidate_artifact_id":          dossier.get("candidate_artifact_id"),
        "readiness_state":                dossier.get("readiness_state"),
        "readiness_rationale":            dossier.get("readiness_rationale"),
        "gate_summary":                   gs,
        "stub_execution_summary":         ss,
        "metadata_report_count":          len(dossier.get("metadata_evaluation_report_refs", [])),
        "live_plan_count":                len(dossier.get("live_evaluation_plan_refs", [])),
        "stub_report_count":              len(dossier.get("stub_execution_report_refs", [])),
        "promotion_blocked":              dossier.get("promotion_blocked"),
        "promotion_decision_emitted":     dossier.get("promotion_decision_emitted"),
        "real_model_inference_performed": dossier.get("real_model_inference_performed"),
        "provider_calls_performed":       dossier.get("provider_calls_performed"),
        "model_weights_loaded":           dossier.get("model_weights_loaded"),
        "model_training_performed":       dossier.get("model_training_performed"),
        "dossier_hash":                   dossier.get("dossier_hash"),
    }


# ---------------------------------------------------------------------------
# Promotion guard
# ---------------------------------------------------------------------------

def assert_dossier_cannot_promote(dossier: dict) -> None:
    """Assert that this dossier cannot promote a candidate. Raises on violation."""
    violations = []
    if dossier.get("promotion_blocked") is not True:
        violations.append("promotion_blocked is not True")
    if dossier.get("promotion_decision_emitted") is not False:
        violations.append("promotion_decision_emitted is not False")
    if dossier.get("readiness_state") == "metadata_ready":
        # metadata_ready is allowed, but we must confirm it doesn't imply promotion
        if not dossier.get("readiness_rationale", "").strip():
            violations.append("metadata_ready dossier has no readiness_rationale")
    if violations:
        raise EvaluationDossierValidationError(
            "Dossier promotion-block assertion failed: " + "; ".join(violations)
        )
