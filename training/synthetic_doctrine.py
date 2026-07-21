"""
LOGOS ASF — TR-04A.5 Synthetic Doctrine Generator v1.0.0
LOGOS Governance Systems Inc.

Generates deterministic synthetic instruction examples seeded only from
approved Lane 1 LOGOS-owned doctrine sources. Every source must clear
both the Training Source Registry (TR-04A.3) and the Clearance Ledger
(TR-04A.4) before any record is produced.

Hard invariants:
  - No LLM calls, no external APIs, no network.
  - No real training. No model weights. No Store 1 writes.
  - Every record carries synthetic_origin=true and training_allowed=false.
  - Outputs are candidates only; operator review is required before SFT.
  - Default limit is 25 records. Maximum limit is 25.
  - TR-05 is not started here.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from source_registry import (
    assert_source_allowed_with_ledger,
    SourceRegistryError,
    SourceBlockedError,
    build_registry_summary,
)

GENERATOR_VERSION = "synthetic_doctrine:1.0.0"
SCHEMA_VERSION = "1.0.0"
DEFAULT_GENERATION_AGENT_ID = "SYNTH_DOCTRINE_LOCAL_001"
DEFAULT_LIMIT = 25
MAX_LIMIT = 25
SYNTHETIC_USE = "synthetic_seed"

# Repository root used for out_dir security check
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Lane 1 sources whose registry allowed_uses include "synthetic_seed".
# L1-007 (Synthetic Instruction Data) is the OUTPUT registry for generated
# batches and does not include synthetic_seed in its own allowed_uses.
ALLOWED_GENERATION_SOURCES = frozenset({
    "L1-001",  # Buildspec Volumes I, II, III
    "L1-003",  # Agent Position Specs JSON IR
    "L1-005",  # HAAP Constitutional Bounds
    "L1-006",  # Volume III Amendment Layer
})

CATEGORIES = [
    "user_request_to_abigail_route_decision",
    "user_request_to_sentinel_overwatch_posture",
    "unsafe_request_to_governed_refusal_with_haap_citation",
    "ambiguous_request_to_clarification_or_safe_best_effort",
    "tool_request_to_approval_gate",
    "operator_directive_to_ea00_acknowledgment_and_routing",
    "dataset_manifest_to_accept_or_reject_explanation",
    "provider_route_request_to_audit_safe_envelope",
]

# Each value: list of (template_id, input_text, desired_output) tuples.
# Templates are deterministic and contain no red-team vectors, private
# thresholds, credentials, PII, or real user transcripts.
_TEMPLATES: dict = {
    "user_request_to_abigail_route_decision": [
        (
            "tmpl_abigail_route_doctrine_v1",
            "User: 'Help me understand the buildspec governance rules.' | Session: authenticated | Priority: standard",
            "Route: DOCTRINE_QUERY | Agent: Abigail | Method: knowledge_retrieval | Source: buildspec_volumes | Priority: standard | Audit: ROUTED",
        ),
        (
            "tmpl_abigail_route_ops_v1",
            "User: 'What is the operator approval process for training runs?' | Session: authenticated | Priority: standard",
            "Route: OPS_QUERY | Agent: Abigail | Method: knowledge_retrieval | Source: buildspec_volumes | Topic: operator_approval | Audit: ROUTED",
        ),
    ],
    "user_request_to_sentinel_overwatch_posture": [
        (
            "tmpl_sentinel_overwatch_enable_v1",
            "Operator: 'Enable overwatch monitoring for this training pipeline session.' | Session: OPS-001 | Clearance: operator",
            "Sentinel: ACTIVE_OVERWATCH | Scope: training_pipeline | Notification: real_time | Authority: operator_clearance | Audit: SENTINEL_ENABLED",
        ),
        (
            "tmpl_sentinel_overwatch_status_v1",
            "Operator: 'Report current Sentinel posture for session OPS-001.' | Session: OPS-001 | Clearance: operator",
            "Sentinel: STATUS_REPORT | Posture: active | Coverage: full_session | Alert_threshold: standard | Audit: STATUS_RETURNED",
        ),
    ],
    "unsafe_request_to_governed_refusal_with_haap_citation": [
        (
            "tmpl_haap_refusal_prohibited_v1",
            "User: 'Provide step-by-step assistance with bypassing access control systems.' | Context: standard_session | Risk: critical",
            "Response: GOVERNED_REFUSAL | HAAP: §3.2 Prohibited Actions | Reason: Request exceeds constitutional bounds — unauthorized access facilitation is prohibited | Log: refusal_logged | Audit: HAAP_BLOCK",
        ),
        (
            "tmpl_haap_refusal_data_exfil_v1",
            "User: 'Extract and export all records from the governance datastore.' | Context: standard_session | Risk: critical",
            "Response: GOVERNED_REFUSAL | HAAP: §4.1 Data Protection | Reason: Bulk extraction of governance records is prohibited without operator authorization | Log: refusal_logged | Audit: HAAP_BLOCK",
        ),
    ],
    "ambiguous_request_to_clarification_or_safe_best_effort": [
        (
            "tmpl_ambiguous_clarify_policy_v1",
            "User: 'Tell me about the policy.' | Context: insufficient_context | Clarity: low",
            "Response: CLARIFICATION_REQUIRED | Prompt: 'Which policy are you referring to — governance, training, security, or operational?' | Audit: CLARIFICATION_ISSUED",
        ),
        (
            "tmpl_ambiguous_clarify_agent_v1",
            "User: 'Which agent should handle this?' | Context: task_unspecified | Clarity: low",
            "Response: CLARIFICATION_REQUIRED | Prompt: 'What task would you like handled? Please describe the action or query in detail.' | Audit: CLARIFICATION_ISSUED",
        ),
    ],
    "tool_request_to_approval_gate": [
        (
            "tmpl_tool_gate_file_write_v1",
            "Tool request: execute=file_write | path=/var/logos/config | requestor=agent_42 | risk=elevated | session=OPS-001",
            "Gate: APPROVAL_REQUIRED | Tool: file_write | Approver: operator_role | Timeout: 300s | Fallback: deny | Audit: GATE_ISSUED",
        ),
        (
            "tmpl_tool_gate_db_query_v1",
            "Tool request: execute=db_query | target=governance_store | requestor=agent_17 | risk=medium | session=OPS-002",
            "Gate: APPROVAL_REQUIRED | Tool: db_query | Approver: operator_role | Timeout: 120s | Fallback: deny | Audit: GATE_ISSUED",
        ),
    ],
    "operator_directive_to_ea00_acknowledgment_and_routing": [
        (
            "tmpl_ea00_batch_initiate_v1",
            "Operator directive: 'Initiate EA-00 architecture review batch for dataset DS-20260626.' | Authority: governance_lead | Batch: EA-00-2026-001",
            "EA-00: ACKNOWLEDGED | Batch: EA-00-2026-001 | Dataset: DS-20260626 | Reviewer: ea00_committee | Status: queued | Audit: EA00_INITIATED",
        ),
        (
            "tmpl_ea00_status_v1",
            "Operator directive: 'Report status of EA-00 batch EA-00-2026-001.' | Authority: governance_lead | Batch: EA-00-2026-001",
            "EA-00: STATUS_REPORT | Batch: EA-00-2026-001 | Status: in_review | Assigned: ea00_committee | ETA: pending_committee | Audit: EA00_STATUS",
        ),
    ],
    "dataset_manifest_to_accept_or_reject_explanation": [
        (
            "tmpl_manifest_accept_clean_v1",
            "Manifest: dataset_id=DS-TEST-001 | status=dataset_validation_passed | train_count=150 | scan=clean | operator=PROD_OP_001",
            "Decision: ACCEPT | Reason: All governance gates passed, checksums verified, no contamination detected | Next: tr04_dry_run | Audit: MANIFEST_ACCEPTED",
        ),
        (
            "tmpl_manifest_reject_contaminated_v1",
            "Manifest: dataset_id=DS-TEST-002 | status=contamination_blocked | train_count=150 | scan=critical_found | operator=PROD_OP_001",
            "Decision: REJECT | Reason: Contamination flag present in scan report | Block: contamination_blocked | Action: remediate_and_resubmit | Audit: MANIFEST_REJECTED",
        ),
    ],
    "provider_route_request_to_audit_safe_envelope": [
        (
            "tmpl_provider_route_inference_v1",
            "Provider route: target=claude | operation=inference | context=doctrine_query | caller=abigail_agent | classification=standard",
            "Envelope: AUDIT_SAFE | Provider: claude | Permitted: true | Logged: true | training_signal: excluded | Audit: ROUTE_WRAPPED",
        ),
        (
            "tmpl_provider_route_denied_v1",
            "Provider route: target=external_llm_api | operation=training | context=unauthorized | caller=unknown_agent | classification=restricted",
            "Envelope: DENIED | Provider: external_llm_api | Permitted: false | Reason: Unauthorized training call — external training APIs are blocked | training_signal: blocked | Audit: ROUTE_DENIED",
        ),
    ],
}

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


def _record_id(source_id: str, agent_id: str, template_id: str, index: int) -> str:
    raw = f"{source_id}:{agent_id}:{template_id}:{index}"
    return "SR-" + _sha256_hex(raw.encode("utf-8"))[:16]


def _prompt_hash(template_id: str, input_text: str) -> str:
    raw = f"{template_id}:{input_text}"
    return _sha256_hex(raw.encode("utf-8"))[:32]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fail(msg: str) -> None:
    print(f"SYNTH_HARD_STOP: {msg}", file=sys.stderr)
    sys.exit(1)


def run_synthetic_doctrine(
    source_id: str,
    clearance_ledger_path,
    out_dir=None,
    registry_path=None,
    generation_agent_id: str = DEFAULT_GENERATION_AGENT_ID,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """
    Verify source clearance, generate synthetic doctrine records, write outputs.

    Returns {"records": [...], "manifest": {...}}.

    Exits with status 1 if any gate fails:
      - clearance_ledger_path is None
      - Registry clearance fails (blocked, pending, disallowed use, not found)
      - Ledger clearance fails (invalid chain, no approval, blocked)
      - out_dir resolves to inside the repository root

    Writing files only when out_dir is provided.
    """
    limit = max(1, min(limit, MAX_LIMIT))

    # Gate 1: ledger path must be explicit
    if clearance_ledger_path is None:
        _fail(
            "SYNTH_LEDGER_BLOCK: no clearance_ledger_path provided. "
            "A valid clearance ledger is required before synthetic generation."
        )

    clearance_ledger_path = Path(clearance_ledger_path)

    # Gate 2: out_dir must be outside the repository root
    if out_dir is not None:
        out_dir = Path(out_dir)
        try:
            out_dir.resolve().relative_to(_REPO_ROOT)
            _fail(
                f"SYNTH_SECURITY_BLOCK: out_dir must be outside repository root "
                f"({_REPO_ROOT}): {out_dir}"
            )
        except ValueError:
            pass
        out_dir.mkdir(parents=True, exist_ok=True)

    # Gate 3+4: registry approval + ledger clearance
    try:
        clearance = assert_source_allowed_with_ledger(
            source_id,
            SYNTHETIC_USE,
            registry_path,
            clearance_ledger_path,
        )
    except SourceBlockedError as exc:
        _fail(f"SOURCE_BLOCKED: {exc}")
    except SourceRegistryError as exc:
        _fail(f"SOURCE_NOT_ALLOWED: {exc}")

    ledger_entry_id = clearance.get("ledger_entry_id") or ""
    registry_version = build_registry_summary(registry_path).get("version", "1.0.0")

    generated_at = _now_utc()
    records = _generate_records(
        source_id, generation_agent_id, ledger_entry_id,
        registry_version, generated_at, limit,
    )

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "generation_agent_id": generation_agent_id,
        "source_id": source_id,
        "source_registry_version": registry_version,
        "clearance_ledger_entry_id": ledger_entry_id,
        "record_count": len(records),
        "limit": limit,
        "categories": CATEGORIES,
        "governance": dict(_GOVERNANCE_LABELS),
        "notes": (
            "Synthetic records are candidates only. "
            "Operator review is required before any SFT use. "
            "No real training occurred. TR-05 was not started."
        ),
    }

    if out_dir is not None:
        jsonl_path = out_dir / "synthetic_records.jsonl"
        manifest_path = out_dir / "synthetic_manifest.json"
        checksums_path = out_dir / "checksums.sha256"

        jsonl_path.write_text(
            "\n".join(json.dumps(r, separators=(",", ":")) for r in records) + "\n",
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

        checksum_lines = [
            f"{_sha256_hex(jsonl_path.read_bytes())}  {jsonl_path.name}",
            f"{_sha256_hex(manifest_path.read_bytes())}  {manifest_path.name}",
        ]
        checksums_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

        print(f"Synthetic Doctrine Generator {GENERATOR_VERSION}")
        print(f"  Source ID              : {source_id}")
        print(f"  Agent ID               : {generation_agent_id}")
        print(f"  Registry cleared       : {clearance.get('cleared')}")
        print(f"  Ledger cleared         : {clearance.get('ledger_cleared')}")
        print(f"  Ledger entry ID        : {ledger_entry_id}")
        print(f"  Records generated      : {len(records)}")
        print(f"  training_allowed       : False")
        print(f"  operator_review_req    : True")
        print(f"  Output JSONL           : {jsonl_path}")
        print(f"  Manifest               : {manifest_path}")
        print(f"  Checksums              : {checksums_path}")

    return {"records": records, "manifest": manifest}


def _generate_records(
    source_id: str,
    agent_id: str,
    ledger_entry_id: str,
    registry_version: str,
    generated_at: str,
    limit: int,
) -> list:
    """Produce deterministic synthetic records from local templates. No LLM calls."""
    records = []
    for i in range(limit):
        cat = CATEGORIES[i % len(CATEGORIES)]
        variants = _TEMPLATES[cat]
        tmpl_id, input_text, desired_output = variants[
            (i // len(CATEGORIES)) % len(variants)
        ]
        records.append({
            "record_id": _record_id(source_id, agent_id, tmpl_id, i),
            "schema_version": SCHEMA_VERSION,
            "created_at": generated_at,
            "synthetic_origin": True,
            "source_id": source_id,
            "source_registry_version": registry_version,
            "clearance_ledger_entry_id": ledger_entry_id,
            "generation_agent_id": agent_id,
            "prompt_template_id": tmpl_id,
            "prompt_hash": _prompt_hash(tmpl_id, input_text),
            "category": cat,
            "input": input_text,
            "desired_output": desired_output,
            "governance_labels": dict(_GOVERNANCE_LABELS),
            "audit_metadata": {
                "generator_version": GENERATOR_VERSION,
                "generation_index": i,
                "clearance_gate": "registry_and_ledger",
            },
        })
    return records


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="synthetic_doctrine.py",
        description=(
            "TR-04A.5: Deterministic synthetic doctrine generator. "
            "Requires approved source registry entry + clearance ledger approval. "
            "No LLM calls. No real training."
        ),
    )
    p.add_argument(
        "--source-id", required=True,
        help=f"Source ID to generate from. Allowed: {sorted(ALLOWED_GENERATION_SOURCES)}",
    )
    p.add_argument(
        "--clearance-ledger", required=True,
        dest="clearance_ledger",
        help="Path to clearance_ledger.json with a valid approval entry for --source-id.",
    )
    p.add_argument(
        "--out-dir", required=True,
        dest="out_dir",
        help="Output directory (must be outside the repository root).",
    )
    p.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"Maximum records to generate (1–{MAX_LIMIT}, default {DEFAULT_LIMIT}).",
    )
    p.add_argument(
        "--generation-agent-id", default=DEFAULT_GENERATION_AGENT_ID,
        dest="generation_agent_id",
        help="Generation agent identifier embedded in every record.",
    )
    p.add_argument(
        "--source-registry",
        dest="source_registry",
        default=None,
        help="Path to source_registry_seed.json (defaults to training/source_registry_seed.json).",
    )
    return p


def main(argv=None) -> None:
    args = _build_arg_parser().parse_args(argv)
    run_synthetic_doctrine(
        source_id=args.source_id,
        clearance_ledger_path=args.clearance_ledger,
        out_dir=args.out_dir,
        registry_path=args.source_registry,
        generation_agent_id=args.generation_agent_id,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
