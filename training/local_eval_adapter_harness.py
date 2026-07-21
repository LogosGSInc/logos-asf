"""
TR-06D: Local-Only Evaluation Adapter Harness.

Provides execution plumbing for TR-06C live evaluation plans using deterministic
local stub adapters only. No real model inference, provider calls, local model
runtime execution, or model weight loading occurs here.

Architecture:
  TR-06C plan → validate_plan_for_stub_execution → execute_plan_with_stub_adapter
                                                  → build_execution_report
                                                  → save_execution_report

The stub adapter returns deterministic, reproducible synthetic responses keyed
on (live_eval_case_id, case_category). All responses carry the disclaimer:
  DETERMINISTIC_STUB_OUTPUT_NOT_MODEL_BEHAVIOR

Blocked provider/runtime adapters:
  openai, anthropic, gemini, groq, xai, huggingface, ollama, vllm, llama.cpp,
  http endpoints, cloud services, subprocess model execution.

Relationship to TR-06C:
  TR-06C defines the interface (plans, cases, disabled executor).
  TR-06D provides stub execution plumbing and a typed result layer.
  Future real local model execution requires a separate operator-approved phase.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Public re-exports from live_eval_interface (no circular deps)
# ---------------------------------------------------------------------------

from training.live_eval_interface import (
    LiveEvalInterfaceError,
    LiveEvalValidationError,
    load_live_eval_plan,
    validate_live_eval_plan,
)

SCHEMA_VERSION = "1.0.0"

STUB_ADAPTER_ID = "TR06D_STUB_ADAPTER_001"
STUB_DISCLAIMER = "DETERMINISTIC_STUB_OUTPUT_NOT_MODEL_BEHAVIOR"

REQUIRED_REPORT_FIELDS = frozenset({
    "execution_report_id",
    "schema_version",
    "created_at",
    "live_eval_plan_id",
    "candidate_artifact_id",
    "adapter_id",
    "adapter_type",
    "adapter_mode",
    "execution_status",
    "cases_executed",
    "case_results",
    "requires_live_inference",
    "real_model_inference_performed",
    "provider_calls_performed",
    "model_weights_loaded",
    "promotion_blocked",
    "promotion_decision_emitted",
    "operator_review_required",
    "blocked_actions",
    "notes",
})

_BLOCKED_ADAPTER_KEYWORDS = frozenset({
    "openai", "anthropic", "gemini", "groq", "xai", "huggingface",
    "ollama", "vllm", "llama_cpp", "llama.cpp", "together", "mistral",
    "cohere", "replicate", "bedrock", "azure_openai", "gpt", "claude",
    "http://", "https://", "localhost:", "127.0.0.1", "0.0.0.0",
    "subprocess",
})

_BLOCKED_ACTIONS = [
    "model_inference",
    "provider_call",
    "model_weight_load",
    "store1_write",
    "runtime_deployment",
    "model_promotion",
    "tr07_shadow",
    "tr07_canary",
    "subprocess_model_exec",
    "http_provider_call",
]

# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class LocalEvalHarnessError(Exception):
    pass


class LocalEvalPlanRejectedError(LocalEvalHarnessError):
    pass


class LocalEvalAdapterBlockedError(LocalEvalHarnessError):
    pass


class LocalEvalReportValidationError(LocalEvalHarnessError):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _execution_report_id(plan_id: str, case_result_hashes: list) -> str:
    raw = f"tr06d-report:{plan_id}:{':'.join(sorted(case_result_hashes))}"
    return "XR-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _stub_response_hash(case_id: str, case_category: str, response_text: str) -> str:
    raw = f"stub:{case_id}:{case_category}:{response_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Adapter definition and creation
# ---------------------------------------------------------------------------

def build_deterministic_stub_adapter(adapter_id: str = STUB_ADAPTER_ID) -> dict:
    """Build a stub adapter config descriptor. No model is loaded or referenced."""
    return {
        "adapter_id":   adapter_id,
        "adapter_type": "deterministic_stub",
        "adapter_mode": "local_stub_only",
        "description":  (
            "Deterministic local stub adapter for TR-06D evaluation plumbing. "
            "Produces fixed synthetic responses keyed on case_id and case_category. "
            f"{STUB_DISCLAIMER}"
        ),
        "execution_allowed":          True,
        "real_model_inference":       False,
        "provider_calls":             False,
        "model_weights_loaded":       False,
        "runtime":                    "none",
    }


def assert_real_adapter_blocked(adapter_config: dict) -> None:
    """Raise LocalEvalAdapterBlockedError if adapter_config references a real provider or runtime."""
    config_str = json.dumps(adapter_config, separators=(",", ":")).lower()
    triggered = [kw for kw in _BLOCKED_ADAPTER_KEYWORDS if kw in config_str]
    if triggered:
        raise LocalEvalAdapterBlockedError(
            f"Adapter config references blocked provider or runtime: {triggered!r}. "
            "TR-06D only allows deterministic_stub adapters. "
            "No inference engine, provider API, or local model runtime is permitted."
        )
    adapter_type = adapter_config.get("adapter_type", "")
    if adapter_type != "deterministic_stub":
        raise LocalEvalAdapterBlockedError(
            f"adapter_type={adapter_type!r} is not allowed in TR-06D. "
            "Only 'deterministic_stub' is permitted."
        )


# ---------------------------------------------------------------------------
# Plan validation
# ---------------------------------------------------------------------------

def validate_plan_for_stub_execution(plan: dict) -> dict:
    """Validate a TR-06C plan before stub execution. Stricter than validate_live_eval_plan."""
    try:
        validate_live_eval_plan(plan)
    except LiveEvalValidationError as exc:
        raise LocalEvalPlanRejectedError(
            f"Plan failed TR-06C validation: {exc}"
        ) from exc

    if plan.get("promotion_blocked") is not True:
        raise LocalEvalPlanRejectedError("promotion_blocked must be true.")
    if plan.get("promotion_decision_emitted") is not False:
        raise LocalEvalPlanRejectedError("promotion_decision_emitted must be false.")

    for case in plan.get("cases", []):
        if "model_weights_path" in case:
            raise LocalEvalPlanRejectedError(
                f"Case {case.get('live_eval_case_id')!r} has forbidden field 'model_weights_path'."
            )
        if "adapter_checkpoint_path" in case:
            raise LocalEvalPlanRejectedError(
                f"Case {case.get('live_eval_case_id')!r} has forbidden field 'adapter_checkpoint_path'."
            )

    return {"valid_for_stub_execution": True, "live_eval_plan_id": plan.get("live_eval_plan_id")}


# ---------------------------------------------------------------------------
# Stub execution logic
# ---------------------------------------------------------------------------

def _stub_execute_case(case: dict) -> dict:
    """Return a deterministic stub result for one live eval case. No inference occurs."""
    case_id = case["live_eval_case_id"]
    category = case.get("case_category", "unknown")

    category_responses = {
        "constitutional_fidelity": (
            "STUB: Candidate declined bypass request. Constitutional rails confirmed active. "
            "No harmful content produced. Governance authority cited."
        ),
        "haap_refusal_behavior": (
            "STUB: Candidate refused false authority escalation. "
            "No internal config disclosed. HAAP-pattern refusal confirmed."
        ),
        "routing_correctness": (
            "STUB: Candidate identified billing/enterprise intent. "
            "Route label: billing_and_accounts_team. No capability inflation observed."
        ),
        "audit_safe_json_ir_output": (
            '{"stub_audit_record": {"action_summary": "session_summarized", '
            '"protected_content_leaked": false, "format": "json_ir_stub"}}'
        ),
        "store1_govmem_boundary_preservation": (
            "STUB: Candidate declined unauthorized memory write. "
            "Store 1 boundary preserved. No write confirmed."
        ),
        "promotion_blocking_invariants": (
            "STUB: Candidate did not confirm production promotion. "
            "Governance review process cited. No promotion claim made."
        ),
    }

    is_promotion_case = (
        category == "promotion_blocking_invariants"
        and "promotion" in case.get("input_prompt", "").lower()
    )
    result = "stub_block" if is_promotion_case else category_responses.get(category)

    if result is None:
        stub_text = f"STUB: case_category={category!r} has no defined stub behavior."
        stub_hash = _stub_response_hash(case_id, category, stub_text)
        return {
            "live_eval_case_id":  case_id,
            "case_category":      category,
            "result":             "not_evaluated",
            "stub_response_hash": stub_hash,
            "rubric_reference":   "not_applicable",
            "disclaimer":         STUB_DISCLAIMER,
            "notes":              stub_text,
        }

    if result == "stub_block":
        stub_text = (
            "STUB: Candidate blocked — promotion claim detected. "
            "Promotion-blocking invariant triggered."
        )
        rubric_ref = "block_criteria"
    else:
        stub_text = result
        rubric_ref = "pass_criteria"
        result = "stub_pass"

    stub_hash = _stub_response_hash(case_id, category, stub_text)
    return {
        "live_eval_case_id":  case_id,
        "case_category":      category,
        "result":             result,
        "stub_response_hash": stub_hash,
        "rubric_reference":   rubric_ref,
        "disclaimer":         STUB_DISCLAIMER,
        "notes":              (
            f"Deterministic stub response for {category!r}. "
            "Not derived from real model inference."
        ),
    }


# ---------------------------------------------------------------------------
# Report building and validation
# ---------------------------------------------------------------------------

def build_execution_report(
    plan: dict,
    adapter_id: str,
    case_results: list,
) -> dict:
    """Build a typed execution report from stub execution results."""
    result_hashes = [r.get("stub_response_hash", "") for r in case_results]
    report_id = _execution_report_id(plan["live_eval_plan_id"], result_hashes)

    return {
        "execution_report_id":          report_id,
        "schema_version":               SCHEMA_VERSION,
        "created_at":                   _now_utc(),
        "live_eval_plan_id":            plan["live_eval_plan_id"],
        "candidate_artifact_id":        plan["candidate_artifact_id"],
        "adapter_id":                   adapter_id,
        "adapter_type":                 "deterministic_stub",
        "adapter_mode":                 "local_stub_only",
        "execution_status":             "completed_stub_execution",
        "cases_executed":               len(case_results),
        "case_results":                 case_results,
        "requires_live_inference":      True,
        "real_model_inference_performed": False,
        "provider_calls_performed":     False,
        "model_weights_loaded":         False,
        "promotion_blocked":            True,
        "promotion_decision_emitted":   False,
        "operator_review_required":     True,
        "blocked_actions":              list(_BLOCKED_ACTIONS),
        "notes": (
            f"TR-06D stub execution report for plan {plan['live_eval_plan_id']!r}. "
            f"Adapter: {adapter_id!r} (deterministic_stub). "
            f"{len(case_results)} case(s) recorded. "
            "No real inference occurred. Operator review required."
        ),
    }


def validate_execution_report(report: dict) -> dict:
    """Validate a TR-06D execution report. Raises LocalEvalReportValidationError on violations."""
    errors = []
    for field in sorted(REQUIRED_REPORT_FIELDS):
        if field not in report:
            errors.append(f"missing required field: {field!r}")
    if errors:
        raise LocalEvalReportValidationError(
            f"Execution report validation failed ({len(errors)} error(s)):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    if report.get("real_model_inference_performed") is not False:
        raise LocalEvalReportValidationError(
            "real_model_inference_performed must be false."
        )
    if report.get("provider_calls_performed") is not False:
        raise LocalEvalReportValidationError("provider_calls_performed must be false.")
    if report.get("model_weights_loaded") is not False:
        raise LocalEvalReportValidationError("model_weights_loaded must be false.")
    if report.get("promotion_blocked") is not True:
        raise LocalEvalReportValidationError("promotion_blocked must be true.")
    if report.get("promotion_decision_emitted") is not False:
        raise LocalEvalReportValidationError("promotion_decision_emitted must be false.")
    if report.get("operator_review_required") is not True:
        raise LocalEvalReportValidationError("operator_review_required must be true.")
    if report.get("requires_live_inference") is not True:
        raise LocalEvalReportValidationError("requires_live_inference must be true.")
    if not report.get("blocked_actions"):
        raise LocalEvalReportValidationError("blocked_actions must be a non-empty list.")

    for i, cr in enumerate(report.get("case_results", [])):
        disclaimer = cr.get("disclaimer", "")
        if STUB_DISCLAIMER not in disclaimer:
            raise LocalEvalReportValidationError(
                f"case_result[{i}] missing required disclaimer: {STUB_DISCLAIMER!r}."
            )

    return {
        "valid":               True,
        "execution_report_id": report.get("execution_report_id"),
        "cases_executed":      report.get("cases_executed"),
    }


# ---------------------------------------------------------------------------
# Save / load / summarize
# ---------------------------------------------------------------------------

def save_execution_report(report: dict, out_dir: str) -> Path:
    """Validate and save execution report + checksums.sha256 to out_dir."""
    validate_execution_report(report)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    report_json = json.dumps(report, indent=2)
    report_path = out / "live_evaluation_execution_report.json"
    report_path.write_text(report_json, encoding="utf-8")

    sha256 = hashlib.sha256(report_json.encode("utf-8")).hexdigest()
    checksum_path = out / "checksums.sha256"
    checksum_path.write_text(
        f"{sha256}  live_evaluation_execution_report.json\n", encoding="utf-8"
    )
    return report_path


def summarize_execution_report(report: dict) -> dict:
    """Return a summary of an execution report."""
    counts: dict = {}
    for cr in report.get("case_results", []):
        r = cr.get("result", "unknown")
        counts[r] = counts.get(r, 0) + 1

    return {
        "execution_report_id":            report.get("execution_report_id"),
        "live_eval_plan_id":              report.get("live_eval_plan_id"),
        "candidate_artifact_id":          report.get("candidate_artifact_id"),
        "adapter_id":                     report.get("adapter_id"),
        "adapter_type":                   report.get("adapter_type"),
        "execution_status":               report.get("execution_status"),
        "cases_executed":                 report.get("cases_executed"),
        "by_result":                      counts,
        "real_model_inference_performed": report.get("real_model_inference_performed"),
        "provider_calls_performed":       report.get("provider_calls_performed"),
        "model_weights_loaded":           report.get("model_weights_loaded"),
        "promotion_blocked":              report.get("promotion_blocked"),
        "promotion_decision_emitted":     report.get("promotion_decision_emitted"),
        "operator_review_required":       report.get("operator_review_required"),
    }


# ---------------------------------------------------------------------------
# Main entry point: execute_plan_with_stub_adapter
# ---------------------------------------------------------------------------

def execute_plan_with_stub_adapter(
    plan: dict,
    adapter: dict = None,
    out_dir: str = None,
) -> dict:
    """Execute a TR-06C plan against the deterministic stub adapter.

    Validates the plan, applies blocked-adapter checks, runs per-case stub logic,
    builds and validates the execution report, and optionally saves to out_dir.

    No real model inference occurs. No provider calls occur. No weights are loaded.
    """
    validate_plan_for_stub_execution(plan)

    if adapter is None:
        adapter = build_deterministic_stub_adapter()

    assert_real_adapter_blocked(adapter)

    case_results = [_stub_execute_case(case) for case in plan.get("cases", [])]

    report = build_execution_report(plan, adapter["adapter_id"], case_results)
    validate_execution_report(report)

    if out_dir is not None:
        save_execution_report(report, out_dir)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_execute_stub(args):
    plan = load_live_eval_plan(args.plan)
    adapter = build_deterministic_stub_adapter(args.adapter_id)
    report = execute_plan_with_stub_adapter(plan, adapter=adapter, out_dir=args.out_dir)
    summary = summarize_execution_report(report)
    print(json.dumps(summary, indent=2))


def _cli_summarize(args):
    p = Path(args.report)
    if not p.exists():
        print(f"ERROR: report file not found: {args.report}", file=sys.stderr)
        sys.exit(1)
    report = json.loads(p.read_text(encoding="utf-8"))
    validate_execution_report(report)
    print(json.dumps(summarize_execution_report(report), indent=2))


def _cli_assert_blocked_adapter(args):
    p = Path(args.adapter_config)
    if not p.exists():
        print(f"ERROR: adapter config not found: {args.adapter_config}", file=sys.stderr)
        sys.exit(1)
    config = json.loads(p.read_text(encoding="utf-8"))
    try:
        assert_real_adapter_blocked(config)
        print("ERROR: adapter config was NOT blocked (should have been).", file=sys.stderr)
        sys.exit(1)
    except LocalEvalAdapterBlockedError as exc:
        print(f"BLOCKED (expected): {exc}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TR-06D local eval adapter harness CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_exec = sub.add_parser("execute-stub", help="Execute a plan with the stub adapter.")
    p_exec.add_argument("--plan",       required=True, help="Path to LP-*.json plan file.")
    p_exec.add_argument("--out-dir",    required=False, default=None)
    p_exec.add_argument("--adapter-id", default=STUB_ADAPTER_ID)
    p_exec.set_defaults(func=_cli_execute_stub)

    p_sum = sub.add_parser("summarize", help="Summarize an execution report.")
    p_sum.add_argument("--report", required=True)
    p_sum.set_defaults(func=_cli_summarize)

    p_blk = sub.add_parser("assert-blocked-adapter", help="Assert an adapter config is blocked.")
    p_blk.add_argument("--adapter-config", required=True)
    p_blk.set_defaults(func=_cli_assert_blocked_adapter)

    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    args.func(args)
