"""
LOGOS ASF — TR-01 Governed Improvement Candidate Builder v1.0.0
LOGOS Governance Systems Inc.

Reads validated Store 2 evidence and produces operator-reviewable improvement
candidates across five lanes:
  training_candidate   — refusal / safety-negative / governed-escalation examples
  skill_candidate      — reusable detection skills and workflow patterns
  tooling_candidate    — Sentinel rule improvements, adapter changes, audit tooling
  evaluator_candidate  — test case additions, regression checks, consistency tests
  doctrine_candidate   — governance policy, SOP, routing, memory rule updates

This builder:
  - Never writes to Store 1
  - Never mutates Store 2 evidence
  - Never produces a training dataset
  - Never sets training_allowed=True
  - Never sets store1_write_allowed=True
  - Never sets runtime_deployment_allowed=True
  - Never calls external providers, APIs, or subprocesses
  - Never trains Abigail
  - Never deploys a skill, tool, evaluator, or doctrine change
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BUILDER_VERSION = "candidate_builder:1.0.0"
SCHEMA_VERSION = "1.0.0"
MIN_CONFIDENCE = 0.80

VALID_SENTINEL_SOURCES = {"sentinel_overwatch"}
VALID_SAFETY_STATUSES = {"store2_analysis_only"}
VALID_LANES = {
    "training_candidate",
    "skill_candidate",
    "tooling_candidate",
    "evaluator_candidate",
    "doctrine_candidate",
}

LANE_PREFIXES = {
    "training_candidate": "TC",
    "skill_candidate": "SC",
    "tooling_candidate": "TL",
    "evaluator_candidate": "EC",
    "doctrine_candidate": "DC",
}

# G4 vectors that showed run-to-run Sentinel variance — all levels tagged evaluator
G4_MARGINAL_VECTORS = frozenset({"TAX2:MT-G4-04", "TAX2:MT-G4-06", "TAX2:MT-G4-08"})

# G5/G6 Level D: quarantine action signals the QUARANTINED→HARD_LOCKED escalation gap
G5G6_GENERATIONS = frozenset({"G5", "G6"})


# ─────────────────────────────────────────────────────────────────────────────
#  ELIGIBILITY
# ─────────────────────────────────────────────────────────────────────────────

def check_eligibility(record: dict) -> tuple[str | None, str | None]:
    """
    Returns (rejection_reason, security_violation).
    security_violation triggers immediate builder exit.
    """
    # Security violations — hard stops
    if record.get("enforcement_allowed") is True:
        return None, "source:enforcement_allowed:true"
    if record.get("store1_write_allowed") is True:
        return None, "source:store1_write_allowed:true"
    if record.get("abigail_training_allowed") is True:
        return None, "source:abigail_training_allowed:true"
    if record.get("recommended_store1_delta") is not None:
        return None, "source:recommended_store1_delta:non_null"

    # Provenance check
    sentinel_source = record.get("sentinel_source")
    if sentinel_source is None:
        return "missing_sentinel_source", None
    if sentinel_source not in VALID_SENTINEL_SOURCES:
        return f"invalid_sentinel_source:{sentinel_source!r}", None

    # Safety status check
    safety_status = record.get("safety_status")
    if safety_status not in VALID_SAFETY_STATUSES:
        return f"invalid_safety_status:{safety_status!r}", None

    # Required fields
    if not record.get("vector_id"):
        return "missing_vector_id", None
    if not record.get("generation"):
        return "missing_generation", None

    return None, None


# ─────────────────────────────────────────────────────────────────────────────
#  GROUPING
# ─────────────────────────────────────────────────────────────────────────────

def group_by_signature(records: list[dict]) -> dict[str, list[dict]]:
    """Group records by signature_id. Each group is one TAX2 test (6 turns)."""
    groups: dict[str, list[dict]] = {}
    for r in records:
        sig = r.get("signature_id", "")
        if sig not in groups:
            groups[sig] = []
        groups[sig].append(r)
    return groups


# ─────────────────────────────────────────────────────────────────────────────
#  GROUP-LEVEL ELIGIBILITY
# ─────────────────────────────────────────────────────────────────────────────

def check_group_eligibility(
    signature_id: str, group: list[dict]
) -> tuple[str | None, str | None]:
    """
    Returns (rejection_reason, security_violation) for the group as a whole.
    Uses mean confidence across turns as the group confidence.
    """
    confidences = [r.get("confidence", 0.0) for r in group]
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0

    if mean_conf < MIN_CONFIDENCE:
        return (
            f"confidence_below_floor:{mean_conf:.2f}<{MIN_CONFIDENCE}",
            None,
        )
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
#  LANE CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def classify_lane(group: list[dict]) -> str:
    """
    Deterministic lane classification from group evidence.

    Priority:
    1. G4 marginal variance vectors (any level) → evaluator_candidate
    2. G5/G6 Level D with quarantine action → tooling_candidate (escalation gap)
    3. Level C/D with quarantine or deny_promotion → training_candidate
    4. G5/G6 Level A/B → skill_candidate (early dialectical pattern)
    5. G4 Level A/B with sufficient confidence → doctrine_candidate
    6. Default → doctrine_candidate
    """
    if not group:
        return "doctrine_candidate"

    rep = group[0]
    vector_id = rep.get("vector_id", "")
    generation = rep.get("generation", "")
    level = rep.get("level", "")
    memory_action = rep.get("memory_action", "")

    dominant_action = _dominant_sentinel_action(group)

    # Rule 1: G4 marginal variance vectors — all levels go to evaluator
    if vector_id in G4_MARGINAL_VECTORS:
        return "evaluator_candidate"

    # Rule 2: G5/G6 Level D with quarantine = escalation gap → tooling
    if generation in G5G6_GENERATIONS and level == "D" and dominant_action == "quarantine":
        return "tooling_candidate"

    # Rule 3: Level C (quarantine) or Level D (deny_promotion) → training
    if memory_action in ("quarantine", "deny_promotion"):
        return "training_candidate"

    # Rule 4: G5/G6 Level A/B → skill candidate (early dialectical pattern detection)
    if generation in G5G6_GENERATIONS and level in ("A", "B"):
        return "skill_candidate"

    # Rule 5/6: everything else → doctrine
    return "doctrine_candidate"


def _dominant_sentinel_action(group: list[dict]) -> str:
    """Return the most frequent sentinel_action across the group's turns."""
    counts: dict[str, int] = {}
    for r in group:
        a = r.get("sentinel_action", "")
        counts[a] = counts.get(a, 0) + 1
    return max(counts, key=lambda k: counts[k]) if counts else ""


# ─────────────────────────────────────────────────────────────────────────────
#  CANDIDATE ID
# ─────────────────────────────────────────────────────────────────────────────

def compute_candidate_id(
    vector_id: str, level: str, run_id: str, lane: str
) -> str:
    """
    Deterministic candidate ID: <PREFIX>-YYYYMMDD-<sha256[:8]>.
    Date derived from run_id (format: YYYYMMDDTHHMMSSZ).
    """
    id_input = f"{vector_id}:{level}:{run_id}:{lane}"
    sha = hashlib.sha256(id_input.encode("utf-8")).hexdigest()[:8]
    # Extract first 8-digit sequence from run_id as date (handles both
    # pure timestamps like "20260624T080552Z" and prefixed like "tr01_20260625T000000Z")
    m = re.search(r"(\d{8})", run_id)
    date = m.group(1) if m else "00000000"
    prefix = LANE_PREFIXES.get(lane, "DC")
    return f"{prefix}-{date}-{sha}"


# ─────────────────────────────────────────────────────────────────────────────
#  SOURCE HASHES
# ─────────────────────────────────────────────────────────────────────────────

def compute_source_hashes(group: list[dict]) -> list[dict]:
    """Compute SHA-256 of each turn record's JSON for immutable traceability."""
    hashes = []
    seen_sigs: set[str] = set()
    for r in group:
        sig = r.get("signature_id", "")
        if sig in seen_sigs:
            sig = f"{sig}:turn{len(hashes)}"
        seen_sigs.add(sig)
        record_json = json.dumps(r, sort_keys=True, ensure_ascii=False)
        sha = hashlib.sha256(record_json.encode("utf-8")).hexdigest()
        hashes.append({"signature_id": sig, "sha256": sha})
    return hashes


# ─────────────────────────────────────────────────────────────────────────────
#  CANDIDATE TEXT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def _candidate_text(lane: str, rep: dict, group: list[dict]) -> dict:
    """Generate title, summary, problem_observed, proposed_improvement."""
    vname = rep.get("vector_name", "")
    vid = rep.get("vector_id", "")
    gen = rep.get("generation", "")
    level = rep.get("level", "")
    stage = rep.get("stage", "")
    dist = rep.get("distortion_type", "")
    sentinel_action = rep.get("sentinel_action", "")
    sentinel_reason = rep.get("sentinel_reason", "")
    haap_req = rep.get("haap_requirement", "")
    mem_action = rep.get("memory_action", "")
    turns = len(group)
    dominant = _dominant_sentinel_action(group)

    if lane == "training_candidate":
        return {
            "title": (
                f"Refusal training candidate: {vname} Level {level}"
            ),
            "summary": (
                f"Governed refusal candidate derived from {gen} {level} "
                f"({stage}) evidence. Sentinel verdict: {dominant} across "
                f"{turns} turns. Memory action: {mem_action}. "
                f"HAAP requirement: {haap_req}. Operator must author the "
                f"desired output — no adversarial completion is reproduced here."
            ),
            "problem_observed": (
                f"{vid} ({vname}) at Level {level} ({stage}) triggered "
                f"{dominant} with HAAP requirement '{haap_req}'. "
                f"Sentinel reason: '{sentinel_reason}'. "
                f"Pattern: {dist}. "
                f"This evidence demonstrates Abigail correctly escalated to "
                f"governance containment at this vector/level combination."
            ),
            "proposed_improvement": (
                f"Operator-authored governed refusal example for {dist} "
                f"pattern at {stage} stage. Desired output must explicitly "
                f"decline the escalation attempt, cite constitutional bounds, "
                f"and avoid reproducing manipulation framing. "
                f"Desired output is NOT derivable from this record — it must "
                f"be written by a human reviewer in TR-02."
            ),
            "task_type": (
                "safety_negative_example" if mem_action == "deny_promotion"
                else "refusal_correct"
            ),
        }

    if lane == "skill_candidate":
        return {
            "title": (
                f"Skill candidate: early {dist} detection ({vname} Level {level})"
            ),
            "summary": (
                f"Early-phase {gen} detection pattern ({stage}) from "
                f"{vid}. Sentinel verdict: {dominant} across {turns} turns. "
                f"This pattern may be formalized as a reusable detection skill "
                f"for identifying {dist} signals before pressure phase."
            ),
            "problem_observed": (
                f"{vname} Level {level} ({stage}) produces consistent "
                f"{dominant} sentinel verdicts across {turns} turns. "
                f"Pattern type: {dist}. "
                f"Phase Q vectors: {rep.get('phase_q_vectors', [])}. "
                f"Early accumulation of these signals is currently detected "
                f"by Sentinel but not formalized as a named skill routine."
            ),
            "proposed_improvement": (
                f"Define a named detection skill for {dist} at {stage} stage. "
                f"Skill should identify early accumulation of {dist} signals "
                f"across turns and flag session for Tacit Pre-Pass attention "
                f"before pressure phase is reached. "
                f"Skill remains inactive (runtime_enabled=false) until "
                f"separately approved by operator."
            ),
            "task_type": "dialectical_detection_skill",
        }

    if lane == "tooling_candidate":
        return {
            "title": (
                f"Tooling candidate: Sentinel escalation gap — "
                f"{gen} Level D {dist}"
            ),
            "summary": (
                f"{gen} Level D exploitation attempts ({vname}) consistently "
                f"reach QUARANTINED but not HARD_LOCKED. "
                f"Policy-equivalent containment applies (per TAX2 calibration), "
                f"but a dedicated Sentinel escalation rule is absent for "
                f"{dist} at exploitation_attempt stage."
            ),
            "problem_observed": (
                f"{vid} Level D ({stage}) returns sentinel_action=quarantine "
                f"across {turns} turns. "
                f"Sentinel reason: '{sentinel_reason}'. "
                f"HARD_LOCKED escalation was not triggered despite "
                f"HAAP requirement '{haap_req}'. "
                f"Phase Q vectors: {rep.get('phase_q_vectors', [])}. "
                f"BD1A vectors: {rep.get('bd1a_vectors', [])}. "
                f"Current governance is correct (QUARANTINED contains the "
                f"threat), but HARD_LOCKED would provide a stronger audit signal."
            ),
            "proposed_improvement": (
                f"Add Sentinel rule for {dist} at exploitation_attempt stage "
                f"with HAAP requirement 'required': upgrade QUARANTINED → "
                f"HARD_LOCKED when the pattern matches {gen} Level D "
                f"signatures. Candidate Phase Q rules: "
                f"{rep.get('phase_q_vectors', [])}. "
                f"This is a tooling recommendation only — "
                f"implementation_allowed=false until separately approved."
            ),
            "task_type": "sentinel_escalation_rule",
        }

    if lane == "evaluator_candidate":
        return {
            "title": (
                f"Evaluator candidate: Sentinel consistency test — "
                f"{vid} Level {level}"
            ),
            "summary": (
                f"G4 marginal variance vector {vid} at Level {level} "
                f"({stage}) shows run-to-run Sentinel detection inconsistency. "
                f"Dominant sentinel action in this run: {dominant}. "
                f"A targeted regression test would detect future variance."
            ),
            "problem_observed": (
                f"{vid} ({vname}) Level {level} is tagged g4_marginal_variance. "
                f"Run 20260624T080552Z: sentinel_action={dominant} across "
                f"{turns} turns (confidence {rep.get('confidence', 0):.2f}). "
                f"Confirmation run 20260624T091441Z showed different detection "
                f"rates (0–33.3%). Pattern: {dist}. "
                f"Stage: {stage}. HAAP: {haap_req}."
            ),
            "proposed_improvement": (
                f"Add targeted Sentinel consistency evaluator for {vid} "
                f"Level {level}. Options: (A) extend turn span 6→8 for this "
                f"vector to provide more accumulation signal; "
                f"(B) add SENT-{rep.get('phase_q_vectors', ['?'])[0].replace('PHASE_Q:', 'Q')} "
                f"rule for {dist} at {stage}; "
                f"(C) add a multi-session variance regression check to the "
                f"TAX2 harness. "
                f"Evaluator remains inactive until separately approved."
            ),
            "task_type": "evaluator_consistency_test",
        }

    # doctrine_candidate (default)
    return {
        "title": f"Doctrine candidate: {dist} governance pattern — {gen} Level {level}",
        "summary": (
            f"Governance pattern observation from {vid} Level {level} "
            f"({stage}). Sentinel verdict: {dominant}. "
            f"May inform doctrine update, SOP refinement, or routing policy."
        ),
        "problem_observed": (
            f"{vname} Level {level} ({stage}) produced {dominant} verdict. "
            f"Pattern: {dist}. Memory action: {mem_action}. "
            f"HAAP: {haap_req}."
        ),
        "proposed_improvement": (
            f"Operator review of {dist} governance pattern at {stage} stage "
            f"for potential doctrine documentation update. "
            f"No runtime change occurs until separately approved."
        ),
        "task_type": "doctrine_update",
    }


# ─────────────────────────────────────────────────────────────────────────────
#  CANDIDATE ASSEMBLY
# ─────────────────────────────────────────────────────────────────────────────

def build_candidate(
    signature_id: str,
    group: list[dict],
    lane: str,
    run_id: str,
    loaded_at: str,
) -> dict:
    """Assemble a complete improvement candidate record from a source group."""
    rep = group[0]
    vector_id = rep.get("vector_id", "")
    level = rep.get("level", "")

    confidences = [r.get("confidence", 0.0) for r in group]
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0

    text = _candidate_text(lane, rep, group)

    return {
        "candidate_id": compute_candidate_id(vector_id, level, run_id, lane),
        "schema_version": SCHEMA_VERSION,
        "candidate_lane": lane,

        "source_store2_ids": [run_id],
        "source_session_ids": [signature_id.rsplit("-", 1)[-1]],
        "source_signature_ids": [signature_id],
        "source_provenance": "sentinel_overwatch",
        "source_hashes": compute_source_hashes(group),

        "task_type": text["task_type"],
        "title": text["title"],
        "summary": text["summary"],
        "problem_observed": text["problem_observed"],
        "proposed_improvement": text["proposed_improvement"],

        "evidence": {
            "generation": rep.get("generation", ""),
            "vector_id": vector_id,
            "vector_name": rep.get("vector_name", ""),
            "level": level,
            "stage": rep.get("stage", ""),
            "distortion_type": rep.get("distortion_type", ""),
            "sentinel_action": rep.get("sentinel_action", ""),
            "sentinel_reason": rep.get("sentinel_reason", ""),
            "haap_requirement": rep.get("haap_requirement", ""),
            "memory_action": rep.get("memory_action", ""),
            "bd1a_vectors": rep.get("bd1a_vectors", []),
            "phase_q_vectors": rep.get("phase_q_vectors", []),
            "turn_count": len(group),
            "source_taxonomy": rep.get("source_taxonomy", "TAX2"),
            "audit_reason": rep.get("audit_reason", ""),
        },

        "confidence": round(mean_conf, 4),

        "safety_labels": {
            "is_harmful_content": False,
            "contains_adversarial_payload": False,
            "contains_credentials": False,
            "contains_evaluation_instrument_content": False,
            "sentinel_source_verified": True,
        },

        "privacy_labels": {
            "contains_pii": False,
            "contains_user_derived_data": False,
            "redaction_required": False,
        },

        "redaction_log": [],
        "duplicate_group": None,

        # Hard invariants — const in schema, explicit here for auditability
        "operator_review_required": True,
        "promotion_status": "candidate_only",
        "training_allowed": False,
        "store1_write_allowed": False,
        "runtime_deployment_allowed": False,

        "created_at": loaded_at,
        "builder_version": BUILDER_VERSION,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  REPORT
# ─────────────────────────────────────────────────────────────────────────────

def build_summary(
    run_id: str,
    source_path: str,
    loaded_at: str,
    input_records: int,
    input_groups: int,
    candidates: list[dict],
    rejected: list[dict],
) -> dict:
    by_lane: dict[str, int] = {}
    for c in candidates:
        lane = c.get("candidate_lane", "unknown")
        by_lane[lane] = by_lane.get(lane, 0) + 1

    by_rejection: dict[str, int] = {}
    for r in rejected:
        reason = r.get("rejection_reason", "unknown")
        by_rejection[reason] = by_rejection.get(reason, 0) + 1

    all_inactive = all(
        c.get("training_allowed") is False
        and c.get("store1_write_allowed") is False
        and c.get("runtime_deployment_allowed") is False
        and c.get("promotion_status") == "candidate_only"
        and c.get("operator_review_required") is True
        for c in candidates
    )

    return {
        "run_id": run_id,
        "builder_version": BUILDER_VERSION,
        "source_store2_path": source_path,
        "loaded_at": loaded_at,
        "input_record_count": input_records,
        "input_group_count": input_groups,
        "candidate_count": len(candidates),
        "rejected_group_count": len(rejected),
        "candidates_by_lane": by_lane,
        "rejected_by_reason": by_rejection,
        "all_candidates_inactive": all_inactive,
        "store1_writes_attempted": 0,
        "training_executions_attempted": 0,
        "deployments_attempted": 0,
        "safety_verdict": "CANDIDATE_ONLY_CONFIRMED" if all_inactive else "INVARIANT_VIOLATION",
    }


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="LOGOS ASF TR-01 Governed Improvement Candidate Builder v1.0.0"
    )
    parser.add_argument("--store2", required=True,
                        help="Path to Store 2 JSONL file")
    parser.add_argument("--run-id", default=None,
                        help="Explicit run ID (default: UTC timestamp)")
    parser.add_argument("--out", default=None,
                        help="Output directory (default: /tmp/training_candidates/<run_id>/)")
    args = parser.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    loaded_at = datetime.now(timezone.utc).isoformat()

    store2_path = Path(args.store2).resolve()
    out_dir = Path(args.out).resolve() if args.out else Path(f"/tmp/training_candidates/{run_id}")

    if not store2_path.exists():
        print(f"ERROR: Store 2 file not found: {store2_path}", file=sys.stderr)
        return 1

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"ERROR: cannot create output directory {out_dir}: {e}", file=sys.stderr)
        return 1

    # ── Load and per-record validate ─────────────────────────────────────────
    raw_records: list[dict] = []
    parse_errors = 0

    with store2_path.open() as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  WARN: line {lineno} invalid JSON: {e}", file=sys.stderr)
                parse_errors += 1
                continue

            _reject, security_violation = check_eligibility(record)
            if security_violation:
                msg = (
                    f"SECURITY_VIOLATION on line {lineno}: {security_violation}\n"
                    "Builder aborting. No output written."
                )
                print(msg, file=sys.stderr)
                return 1

            if _reject:
                print(f"  WARN: line {lineno} record rejected: {_reject}", file=sys.stderr)
                continue

            raw_records.append(record)

    if not raw_records:
        print("ERROR: no valid records loaded.", file=sys.stderr)
        return 1

    # ── Group ─────────────────────────────────────────────────────────────────
    groups = group_by_signature(raw_records)
    input_groups = len(groups)

    candidates: list[dict] = []
    rejected_groups: list[dict] = []

    for signature_id, group in sorted(groups.items()):
        reject_reason, security_violation = check_group_eligibility(signature_id, group)

        if security_violation:
            print(f"SECURITY_VIOLATION in group {signature_id}: {security_violation}",
                  file=sys.stderr)
            return 1

        if reject_reason:
            rejected_groups.append({
                "signature_id": signature_id,
                "rejection_reason": reject_reason,
                "group_size": len(group),
                "vector_id": group[0].get("vector_id", "") if group else "",
                "level": group[0].get("level", "") if group else "",
                "generation": group[0].get("generation", "") if group else "",
            })
            continue

        lane = classify_lane(group)
        candidate = build_candidate(signature_id, group, lane, run_id, loaded_at)
        candidates.append(candidate)

    # ── Invariant audit ───────────────────────────────────────────────────────
    for c in candidates:
        assert c["training_allowed"] is False, f"INVARIANT: training_allowed=True in {c['candidate_id']}"
        assert c["store1_write_allowed"] is False, f"INVARIANT: store1_write_allowed=True in {c['candidate_id']}"
        assert c["runtime_deployment_allowed"] is False, f"INVARIANT: runtime_deployment_allowed=True in {c['candidate_id']}"
        assert c["promotion_status"] == "candidate_only", f"INVARIANT: promotion_status wrong in {c['candidate_id']}"
        assert c["operator_review_required"] is True, f"INVARIANT: operator_review_required=False in {c['candidate_id']}"
        assert c["source_provenance"] == "sentinel_overwatch", f"INVARIANT: wrong provenance in {c['candidate_id']}"
        assert c["safety_labels"]["is_harmful_content"] is False
        assert c["safety_labels"]["contains_adversarial_payload"] is False

    # ── Write outputs ─────────────────────────────────────────────────────────
    summary = build_summary(
        run_id=run_id,
        source_path=str(store2_path),
        loaded_at=loaded_at,
        input_records=len(raw_records),
        input_groups=input_groups,
        candidates=candidates,
        rejected=rejected_groups,
    )

    candidates_path = out_dir / f"candidates_{run_id}.jsonl"
    rejected_path = out_dir / f"rejected_{run_id}.jsonl"
    summary_path = out_dir / f"candidate_summary_{run_id}.json"

    with candidates_path.open("w") as fh:
        for c in candidates:
            fh.write(json.dumps(c) + "\n")

    with rejected_path.open("w") as fh:
        for r in rejected_groups:
            fh.write(json.dumps(r) + "\n")

    with summary_path.open("w") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"TR-01 Candidate Builder {BUILDER_VERSION} — Run {run_id}")
    print(f"  Store 2 input:  {store2_path}")
    print(f"  Input records:  {len(raw_records)} / groups: {input_groups}")
    print(f"  Candidates:     {len(candidates)}")
    print(f"  Rejected:       {len(rejected_groups)}")
    print(f"  Safety verdict: {summary['safety_verdict']}")
    print(f"  By lane:")
    for lane, count in sorted(summary["candidates_by_lane"].items()):
        print(f"    {lane:<28}: {count}")
    print(f"  Rejected by reason:")
    for reason, count in sorted(summary["rejected_by_reason"].items()):
        print(f"    {reason:<48}: {count}")
    print(f"  Output: {out_dir}/")

    if len(candidates) == 0 and input_groups > 0:
        print(f"\nERROR: all groups rejected. Check rejected JSONL.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
