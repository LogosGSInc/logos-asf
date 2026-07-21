"""
LOGOS ASF — TR-02 Operator Review Queue v1.0.0
LOGOS Governance Systems Inc.

Fail-closed, file-backed, append-only review queue for TR-01 improvement candidates.
Supports all seven review actions. Never modifies original candidates. Never creates
training datasets, deploys skills/tools/evaluators/doctrine, or writes to Store 1.

Usage:
  python3 training/review_queue.py \\
    --candidates <path/to/candidates.jsonl> \\
    --out <output-dir (outside repo)> \\
    --operator-id <id> \\
    --operator-role <role> \\
    <action> [candidate_id] [options]

Actions: list, inspect, approve, reject, redact, rewrite, reclassify,
         merge, request-more-evidence, audit
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

QUEUE_VERSION = "review_queue:1.0.0"
DECISION_SCHEMA_VERSION = "1.0.0"

VALID_ACTIONS = frozenset({
    "approve", "reject", "redact", "rewrite",
    "reclassify", "merge", "request_more_evidence",
})

VALID_LANES = frozenset({
    "training_candidate", "skill_candidate", "tooling_candidate",
    "evaluator_candidate", "doctrine_candidate",
})

LANE_PREFIXES = {
    "training_candidate":  "TC",
    "skill_candidate":     "SC",
    "tooling_candidate":   "TL",
    "evaluator_candidate": "EC",
    "doctrine_candidate":  "DC",
}

LANE_APPROVED_STATES = {
    "training_candidate":  "dataset_promotion_pending",
    "skill_candidate":     "skill_design_pending",
    "tooling_candidate":   "tool_design_pending",
    "evaluator_candidate": "evaluator_design_pending",
    "doctrine_candidate":  "doctrine_review_pending",
}

# Actions that create a new version of the same candidate (same ID, v+1)
REVISE_ACTIONS = frozenset({"redact", "rewrite"})
# Actions that create a new candidate entity (new ID)
CREATE_ACTIONS = frozenset({"reclassify", "merge"})

# Statuses from which an approve is allowed
APPROVE_FROM = frozenset({"candidate_only", "evidence_required"})

# Terminal statuses — no further decisions allowed
TERMINAL_STATUSES = frozenset({
    "operator_rejected",
    "changes_requested",   # from reclassify/merge — original superseded; redact/rewrite resets to candidate_only
    "dataset_promotion_pending",
    "skill_design_pending",
    "tool_design_pending",
    "evaluator_design_pending",
    "doctrine_review_pending",
})

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fields that can never be overwritten by a rewrite action
INVARIANT_FIELDS = frozenset({
    "candidate_id", "schema_version", "source_provenance",
    "training_allowed", "store1_write_allowed", "runtime_deployment_allowed",
    "operator_review_required", "promotion_status", "candidate_lane",
})


# ── utilities ─────────────────────────────────────────────────────────────────

def _fail(msg: str) -> None:
    print(f"HARD_STOP: {msg}", file=sys.stderr)
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _date_from_ts(ts: str) -> str:
    m = re.search(r"(\d{8})", ts.replace("-", "").replace(":", ""))
    return m.group(1) if m else "00000000"


def _decision_id(candidate_id: str, action: str, operator_id: str, timestamp: str) -> str:
    raw = json.dumps({
        "candidate_id": candidate_id,
        "action": action,
        "operator_id": operator_id,
        "timestamp": timestamp,
    }, sort_keys=True, separators=(",", ":"))
    return f"RD-{_date_from_ts(timestamp)}-{_sha256(raw)[:8]}"


def _decision_hash(record: dict) -> str:
    r = {k: v for k, v in record.items() if k != "decision_hash"}
    return _sha256(json.dumps(r, sort_keys=True, separators=(",", ":")))


def _new_revised_id(original_id: str, action: str, timestamp: str) -> str:
    """New candidate_id for reclassify/merge — same prefix as original lane."""
    prefix = original_id.split("-")[0]
    raw = f"{action}:{original_id}:{timestamp}"
    return f"{prefix}-{_date_from_ts(timestamp)}-{_sha256(raw)[:8]}"


def _new_lane_id(lane: str, raw_seed: str, timestamp: str) -> str:
    prefix = LANE_PREFIXES[lane]
    return f"{prefix}-{_date_from_ts(timestamp)}-{_sha256(raw_seed)[:8]}"


# ── review queue ──────────────────────────────────────────────────────────────

class ReviewQueue:
    def __init__(self, candidates_path: Path, out_dir: Path):
        # Hard stop: refuse output inside repo
        try:
            out_dir.resolve().relative_to(REPO_ROOT)
            _fail(f"--out must be outside repository root ({REPO_ROOT}): {out_dir}")
        except ValueError:
            pass

        self.candidates_path = candidates_path.resolve()
        self.out_dir = out_dir.resolve()
        self.decisions_log = self.out_dir / "decisions.jsonl"
        self.revised_dir = self.out_dir / "revised"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.revised_dir.mkdir(exist_ok=True)

    # ── loaders ──────────────────────────────────────────────────────────────

    def load_candidates(self) -> dict:
        if not self.candidates_path.exists():
            _fail(f"candidates file not found: {self.candidates_path}")
        candidates = {}
        for i, line in enumerate(self.candidates_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError as e:
                _fail(f"malformed candidate on line {i}: {e}")
            cid = c.get("candidate_id")
            if not cid:
                _fail(f"candidate on line {i} missing candidate_id")
            if c.get("training_allowed") is not False:
                _fail(f"candidate {cid}: training_allowed must be false (security violation)")
            if c.get("store1_write_allowed") is not False:
                _fail(f"candidate {cid}: store1_write_allowed must be false (security violation)")
            if c.get("runtime_deployment_allowed") is not False:
                _fail(f"candidate {cid}: runtime_deployment_allowed must be false (security violation)")
            candidates[cid] = c
        return candidates

    def load_decisions(self) -> list:
        if not self.decisions_log.exists():
            return []
        decisions = []
        for i, line in enumerate(self.decisions_log.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                _fail(f"malformed decision on log line {i}: {e}")
            stored = d.get("decision_hash", "")
            expected = _decision_hash(d)
            if stored != expected:
                _fail(f"decision hash mismatch on line {i}: id={d.get('decision_id')} "
                      f"stored={stored[:8]} expected={expected[:8]}")
            decisions.append(d)
        return decisions

    def _load_revised(self) -> dict:
        """Load revised candidates from the revised dir (keyed by candidate_id)."""
        revised = {}
        for f in sorted(self.revised_dir.glob("*.json")):
            try:
                rc = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            cid = rc.get("candidate_id")
            version = rc.get("candidate_version", 1)
            if not cid:
                continue
            if cid not in revised or revised[cid]["candidate_version"] < version:
                revised[cid] = rc
        return revised

    # ── state machine ─────────────────────────────────────────────────────────

    def compute_state(self, candidates: dict, decisions: list) -> dict:
        state: dict = {}

        # Seed from originals
        for cid, c in candidates.items():
            state[cid] = {
                "candidate_id":    cid,
                "candidate_lane":  c["candidate_lane"],
                "current_version": 1,
                "promotion_status": "candidate_only",
                "training_allowed": False,
                "store1_write_allowed": False,
                "runtime_deployment_allowed": False,
                "decisions_applied": [],
            }

        # Seed from revised candidates not in originals (reclassified / merged)
        revised = self._load_revised()
        for cid, rc in revised.items():
            if cid not in state:
                state[cid] = {
                    "candidate_id":    cid,
                    "candidate_lane":  rc["candidate_lane"],
                    "current_version": rc.get("candidate_version", 1),
                    "promotion_status": rc.get("promotion_status", "candidate_only"),
                    "training_allowed": False,
                    "store1_write_allowed": False,
                    "runtime_deployment_allowed": False,
                    "decisions_applied": [],
                    "is_revised_entity": True,
                }

        # Replay decisions
        for d in decisions:
            cid = d["candidate_id"]
            if cid not in state:
                # Decision on a candidate we didn't seed — add it
                state[cid] = {
                    "candidate_id":    cid,
                    "candidate_lane":  d.get("previous_lane") or "unknown",
                    "current_version": d["candidate_version"],
                    "promotion_status": "candidate_only",
                    "training_allowed": False,
                    "store1_write_allowed": False,
                    "runtime_deployment_allowed": False,
                    "decisions_applied": [],
                }
            s = state[cid]
            s["decisions_applied"].append(d["decision_id"])

            action = d["action"]
            if action in REVISE_ACTIONS:
                # Same entity, new version available for review
                s["current_version"] = d["candidate_version"] + 1
                s["promotion_status"] = "candidate_only"
            elif action in CREATE_ACTIONS:
                # Original superseded — terminal
                s["promotion_status"] = "changes_requested"
            else:
                s["promotion_status"] = d["resulting_status"]

        return state

    def _check_can_act(self, cid: str, s: dict, action: str) -> None:
        status = s["promotion_status"]
        if status in TERMINAL_STATUSES:
            _fail(f"candidate {cid} is in terminal status {status!r} — no further decisions allowed")
        if action == "approve" and status not in APPROVE_FROM:
            _fail(f"candidate {cid} is in status {status!r} — approve requires one of {sorted(APPROVE_FROM)}")

    def _check_no_duplicate_approve(self, cid: str, version: int, decisions: list) -> None:
        existing = [d for d in decisions
                    if d["candidate_id"] == cid
                    and d["action"] == "approve"
                    and d["candidate_version"] == version]
        if existing:
            _fail(f"duplicate approval: {cid} v{version} already approved ({existing[0]['decision_id']})")

    def _validate_operator(self, operator_id: str, operator_role: str) -> None:
        if not operator_id or not operator_id.strip():
            _fail("--operator-id is required for all decision actions")
        if not operator_role or not operator_role.strip():
            _fail("--operator-role is required for all decision actions")

    # ── decision builder ──────────────────────────────────────────────────────

    def _make_decision(self, *, candidate_id: str, candidate_version: int,
                       action: str, operator_id: str, operator_role: str,
                       reason: str, resulting_status: str,
                       evidence_reviewed: bool = True,
                       redactions: list = None, rewritten_fields: list = None,
                       previous_lane: str = None, new_lane: str = None,
                       source_candidate_ids: list = None) -> dict:
        ts = _now()
        did = _decision_id(candidate_id, action, operator_id, ts)
        record = {
            "schema_version":             DECISION_SCHEMA_VERSION,
            "decision_id":                did,
            "candidate_id":               candidate_id,
            "candidate_version":          candidate_version,
            "operator_id":                operator_id,
            "operator_role":              operator_role,
            "action":                     action,
            "reason":                     reason,
            "evidence_reviewed":          evidence_reviewed,
            "redactions":                 redactions or [],
            "rewritten_fields":           rewritten_fields or [],
            "previous_lane":              previous_lane,
            "new_lane":                   new_lane,
            "source_candidate_ids":       source_candidate_ids or [],
            "resulting_status":           resulting_status,
            "training_allowed":           False,
            "store1_write_allowed":       False,
            "runtime_deployment_allowed": False,
            "timestamp":                  ts,
            "queue_version":              QUEUE_VERSION,
            "decision_hash":              "",
        }
        record["decision_hash"] = _decision_hash(record)
        # Hard invariant assertions — terminate if violated
        assert record["training_allowed"] is False, "INVARIANT: training_allowed must be false"
        assert record["store1_write_allowed"] is False, "INVARIANT: store1_write_allowed must be false"
        assert record["runtime_deployment_allowed"] is False, "INVARIANT: runtime_deployment_allowed must be false"
        return record

    def _append_decision(self, record: dict) -> None:
        with self.decisions_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _write_revised(self, candidate: dict) -> Path:
        cid = candidate["candidate_id"]
        version = candidate["candidate_version"]
        out_path = self.revised_dir / f"{cid}_v{version}.json"
        out_path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False))
        return out_path

    # ── commands ─────────────────────────────────────────────────────────────

    def cmd_list(self, candidates: dict, decisions: list,
                 lane: str = None, status: str = None) -> None:
        state = self.compute_state(candidates, decisions)
        rows = list(state.values())
        if lane:
            rows = [r for r in rows if r["candidate_lane"] == lane]
        if status:
            rows = [r for r in rows if r["promotion_status"] == status]
        rows.sort(key=lambda r: r["candidate_id"])
        print(f"{'CANDIDATE_ID':<38} {'LANE':<25} {'STATUS':<36} VER")
        print("-" * 108)
        for r in rows:
            print(f"{r['candidate_id']:<38} {r['candidate_lane']:<25} {r['promotion_status']:<36} {r['current_version']}")
        print(f"\nShowing {len(rows)} candidates.")

    def cmd_inspect(self, candidates: dict, decisions: list, candidate_id: str) -> None:
        state = self.compute_state(candidates, decisions)
        if candidate_id not in state:
            _fail(f"unknown candidate: {candidate_id}")
        s = state[candidate_id]
        version = s["current_version"]

        # Load the correct version of the candidate content
        if version == 1:
            c = candidates.get(candidate_id, {})
        else:
            rev = self.revised_dir / f"{candidate_id}_v{version}.json"
            c = json.loads(rev.read_text()) if rev.exists() else candidates.get(candidate_id, {})

        applied = [d for d in decisions if d["candidate_id"] == candidate_id]
        print(json.dumps({
            "current_state":    s,
            "candidate": {
                "title":                      c.get("title"),
                "candidate_lane":             c.get("candidate_lane"),
                "candidate_version":          c.get("candidate_version", 1),
                "confidence":                 c.get("confidence"),
                "problem_observed":           c.get("problem_observed"),
                "proposed_improvement":       c.get("proposed_improvement"),
                "evidence":                   c.get("evidence", {}),
                "safety_labels":              c.get("safety_labels", {}),
                "training_allowed":           c.get("training_allowed"),
                "store1_write_allowed":       c.get("store1_write_allowed"),
                "runtime_deployment_allowed": c.get("runtime_deployment_allowed"),
            },
            "decisions_on_candidate": applied,
        }, indent=2))

    def cmd_approve(self, candidates: dict, decisions: list,
                    candidate_id: str, operator_id: str, operator_role: str,
                    reason: str) -> None:
        self._validate_operator(operator_id, operator_role)
        state = self.compute_state(candidates, decisions)
        if candidate_id not in state:
            _fail(f"unknown candidate: {candidate_id}")
        s = state[candidate_id]
        self._check_can_act(candidate_id, s, "approve")
        version = s["current_version"]
        self._check_no_duplicate_approve(candidate_id, version, decisions)

        lane = s["candidate_lane"]
        approved_status = LANE_APPROVED_STATES.get(lane, "operator_rejected")
        record = self._make_decision(
            candidate_id=candidate_id, candidate_version=version,
            action="approve", operator_id=operator_id, operator_role=operator_role,
            reason=reason, resulting_status=approved_status,
        )
        self._append_decision(record)
        print(f"APPROVED  : {candidate_id} (v{version}) → {approved_status}")
        print(f"Decision  : {record['decision_id']}")

    def cmd_reject(self, candidates: dict, decisions: list,
                   candidate_id: str, operator_id: str, operator_role: str,
                   reason: str) -> None:
        self._validate_operator(operator_id, operator_role)
        state = self.compute_state(candidates, decisions)
        if candidate_id not in state:
            _fail(f"unknown candidate: {candidate_id}")
        s = state[candidate_id]
        self._check_can_act(candidate_id, s, "reject")
        record = self._make_decision(
            candidate_id=candidate_id, candidate_version=s["current_version"],
            action="reject", operator_id=operator_id, operator_role=operator_role,
            reason=reason, resulting_status="operator_rejected",
        )
        self._append_decision(record)
        print(f"REJECTED  : {candidate_id}")
        print(f"Decision  : {record['decision_id']}")

    def cmd_redact(self, candidates: dict, decisions: list,
                   candidate_id: str, operator_id: str, operator_role: str,
                   reason: str, fields: list) -> None:
        self._validate_operator(operator_id, operator_role)
        if not fields:
            _fail("redact requires --fields <field1,field2,...>")
        state = self.compute_state(candidates, decisions)
        if candidate_id not in state:
            _fail(f"unknown candidate: {candidate_id}")
        s = state[candidate_id]
        self._check_can_act(candidate_id, s, "redact")

        # Load current version content
        version = s["current_version"]
        if version == 1:
            original = candidates.get(candidate_id)
        else:
            rev = self.revised_dir / f"{candidate_id}_v{version}.json"
            original = json.loads(rev.read_text()) if rev.exists() else None
        if not original:
            _fail(f"candidate content not found for {candidate_id} v{version}")

        ts = _now()
        redaction_log = [
            {"field": f, "category": "operator_redaction", "redacted_at": ts}
            for f in fields
        ]
        revised = dict(original)
        revised["candidate_version"] = version + 1
        revised["promotion_status"] = "candidate_only"
        revised["training_allowed"] = False
        revised["store1_write_allowed"] = False
        revised["runtime_deployment_allowed"] = False
        revised["operator_review_required"] = True
        revised["redaction_log"] = original.get("redaction_log", []) + redaction_log
        for field in fields:
            if field in revised:
                revised[field] = "[REDACTED]"

        out_path = self._write_revised(revised)
        record = self._make_decision(
            candidate_id=candidate_id, candidate_version=version,
            action="redact", operator_id=operator_id, operator_role=operator_role,
            reason=reason, resulting_status="changes_requested",
            redactions=redaction_log,
        )
        self._append_decision(record)
        print(f"REDACTED  : {candidate_id} v{version} → new v{version+1} at {out_path}")
        print(f"Decision  : {record['decision_id']}")
        print(f"Original  : {candidate_id} v{version} is byte-unchanged.")

    def cmd_rewrite(self, candidates: dict, decisions: list,
                    candidate_id: str, operator_id: str, operator_role: str,
                    reason: str, set_fields: dict) -> None:
        self._validate_operator(operator_id, operator_role)
        if not set_fields:
            _fail("rewrite requires --set <json-object>")
        state = self.compute_state(candidates, decisions)
        if candidate_id not in state:
            _fail(f"unknown candidate: {candidate_id}")
        s = state[candidate_id]
        self._check_can_act(candidate_id, s, "rewrite")

        for field in set_fields:
            if field in INVARIANT_FIELDS:
                _fail(f"rewrite: field {field!r} is invariant and cannot be changed")

        version = s["current_version"]
        if version == 1:
            original = candidates.get(candidate_id)
        else:
            rev = self.revised_dir / f"{candidate_id}_v{version}.json"
            original = json.loads(rev.read_text()) if rev.exists() else None
        if not original:
            _fail(f"candidate content not found for {candidate_id} v{version}")

        rewritten_fields = [
            {"field": k, "previous_value": original.get(k), "new_value": v}
            for k, v in set_fields.items()
        ]
        revised = dict(original)
        revised["candidate_version"] = version + 1
        revised["promotion_status"] = "candidate_only"
        revised["training_allowed"] = False
        revised["store1_write_allowed"] = False
        revised["runtime_deployment_allowed"] = False
        revised["operator_review_required"] = True
        for field, value in set_fields.items():
            revised[field] = value

        out_path = self._write_revised(revised)
        record = self._make_decision(
            candidate_id=candidate_id, candidate_version=version,
            action="rewrite", operator_id=operator_id, operator_role=operator_role,
            reason=reason, resulting_status="changes_requested",
            rewritten_fields=rewritten_fields,
        )
        self._append_decision(record)
        print(f"REWRITTEN : {candidate_id} v{version} → new v{version+1} at {out_path}")
        print(f"Decision  : {record['decision_id']}")
        print(f"Original  : {candidate_id} v{version} is byte-unchanged.")

    def cmd_reclassify(self, candidates: dict, decisions: list,
                       candidate_id: str, operator_id: str, operator_role: str,
                       reason: str, new_lane: str) -> None:
        self._validate_operator(operator_id, operator_role)
        if new_lane not in VALID_LANES:
            _fail(f"reclassify: invalid lane {new_lane!r}. Must be one of {sorted(VALID_LANES)}")
        state = self.compute_state(candidates, decisions)
        if candidate_id not in state:
            _fail(f"unknown candidate: {candidate_id}")
        s = state[candidate_id]
        self._check_can_act(candidate_id, s, "reclassify")

        old_lane = s["candidate_lane"]
        if old_lane == new_lane:
            _fail(f"reclassify: new_lane {new_lane!r} is the same as current lane")

        version = s["current_version"]
        original = candidates.get(candidate_id)
        if not original:
            rev = self.revised_dir / f"{candidate_id}_v{version}.json"
            original = json.loads(rev.read_text()) if rev.exists() else None
        if not original:
            _fail(f"candidate content not found for {candidate_id}")

        ts = _now()
        raw_seed = f"reclassify:{candidate_id}:{new_lane}:{ts}"
        new_id = _new_lane_id(new_lane, raw_seed, ts)

        revised = dict(original)
        revised["candidate_id"] = new_id
        revised["candidate_version"] = 1
        revised["candidate_lane"] = new_lane
        revised["promotion_status"] = "candidate_only"
        revised["training_allowed"] = False
        revised["store1_write_allowed"] = False
        revised["runtime_deployment_allowed"] = False
        revised["operator_review_required"] = True

        out_path = self._write_revised(revised)
        record = self._make_decision(
            candidate_id=candidate_id, candidate_version=version,
            action="reclassify", operator_id=operator_id, operator_role=operator_role,
            reason=reason, resulting_status="changes_requested",
            previous_lane=old_lane, new_lane=new_lane,
        )
        self._append_decision(record)
        print(f"RECLASSIFY: {candidate_id} ({old_lane}) → {new_id} ({new_lane})")
        print(f"Decision  : {record['decision_id']}")
        print(f"Revised   : {out_path}")
        print(f"Original  : {candidate_id} is byte-unchanged.")

    def cmd_merge(self, candidates: dict, decisions: list,
                  candidate_ids: list, operator_id: str, operator_role: str,
                  reason: str) -> None:
        self._validate_operator(operator_id, operator_role)
        if len(candidate_ids) < 2:
            _fail("merge requires at least 2 candidate IDs (--merge-ids A,B,...)")
        state = self.compute_state(candidates, decisions)
        for cid in candidate_ids:
            if cid not in state:
                _fail(f"unknown candidate for merge: {cid}")
            self._check_can_act(cid, state[cid], "merge")

        first_cid = candidate_ids[0]
        lane = state[first_cid]["candidate_lane"]
        ts = _now()
        raw_seed = f"merge:{'|'.join(sorted(candidate_ids))}:{ts}"
        new_id = _new_lane_id(lane, raw_seed, ts)

        first = candidates[first_cid]
        merged = dict(first)
        merged["candidate_id"] = new_id
        merged["candidate_version"] = 1
        merged["promotion_status"] = "candidate_only"
        merged["training_allowed"] = False
        merged["store1_write_allowed"] = False
        merged["runtime_deployment_allowed"] = False
        merged["operator_review_required"] = True
        merged["source_candidate_ids"] = list(candidate_ids)
        merged["source_signature_ids"] = sorted(set(
            sig
            for cid in candidate_ids
            for sig in candidates[cid].get("source_signature_ids", [])
        ))
        merged["source_hashes"] = [
            h
            for cid in candidate_ids
            for h in candidates[cid].get("source_hashes", [])
        ]

        out_path = self._write_revised(merged)
        print(f"MERGED    : {', '.join(candidate_ids)} → {new_id}")
        print(f"Merged candidate: {out_path}")

        for cid in candidate_ids:
            s = state[cid]
            record = self._make_decision(
                candidate_id=cid, candidate_version=s["current_version"],
                action="merge", operator_id=operator_id, operator_role=operator_role,
                reason=reason, resulting_status="changes_requested",
                source_candidate_ids=list(candidate_ids),
            )
            self._append_decision(record)
        print(f"Originals : {', '.join(candidate_ids)} — byte-unchanged.")

    def cmd_request_more_evidence(self, candidates: dict, decisions: list,
                                   candidate_id: str, operator_id: str,
                                   operator_role: str, reason: str) -> None:
        self._validate_operator(operator_id, operator_role)
        state = self.compute_state(candidates, decisions)
        if candidate_id not in state:
            _fail(f"unknown candidate: {candidate_id}")
        s = state[candidate_id]
        self._check_can_act(candidate_id, s, "request_more_evidence")
        record = self._make_decision(
            candidate_id=candidate_id, candidate_version=s["current_version"],
            action="request_more_evidence", operator_id=operator_id,
            operator_role=operator_role, reason=reason,
            resulting_status="evidence_required",
        )
        self._append_decision(record)
        print(f"EVIDENCE  : {candidate_id} → evidence_required")
        print(f"Decision  : {record['decision_id']}")

    def cmd_audit(self, candidates: dict, decisions: list) -> None:
        state = self.compute_state(candidates, decisions)
        status_counts: dict = {}
        lane_counts: dict = {}
        for s in state.values():
            status_counts[s["promotion_status"]] = status_counts.get(s["promotion_status"], 0) + 1
            lane_counts[s["candidate_lane"]] = lane_counts.get(s["candidate_lane"], 0) + 1

        print("=== TR-02 Review Queue Audit ===")
        print(f"Candidates tracked : {len(state)}")
        print(f"Decisions recorded : {len(decisions)}")
        print(f"\nStatus distribution:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status:<40} {count}")
        print(f"\nLane distribution:")
        for lane, count in sorted(lane_counts.items()):
            print(f"  {lane:<30} {count}")
        print(f"\nRecent decisions (last 10):")
        for d in decisions[-10:]:
            print(f"  {d['decision_id']} | {d['action']:<25} | {d['resulting_status']:<35} | {d['candidate_id']}")

        # Invariant audit
        violations = []
        for d in decisions:
            if d.get("training_allowed") is not False:
                violations.append(f"training_allowed in {d['decision_id']}")
            if d.get("store1_write_allowed") is not False:
                violations.append(f"store1_write_allowed in {d['decision_id']}")
            if d.get("runtime_deployment_allowed") is not False:
                violations.append(f"runtime_deployment_allowed in {d['decision_id']}")

        print(f"\nInvariant violations: {len(violations)}")
        if violations:
            for v in violations[:5]:
                print(f"  VIOLATION: {v}")

        store1_count = sum(1 for d in decisions if "store1" in d.get("action", ""))
        print(f"Store 1 writes     : 0")
        print(f"Training executions: 0")
        print(f"Deployments        : 0")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="review_queue.py",
        description="TR-02 Operator Review Queue — governed candidate review",
    )
    parser.add_argument("--candidates", required=True,
                        help="Path to TR-01 candidates JSONL file")
    parser.add_argument("--out", required=True,
                        help="Output directory (must be outside repository)")
    parser.add_argument("--operator-id",   default="",  help="Operator identifier")
    parser.add_argument("--operator-role", default="",  help="Operator role")
    parser.add_argument("--lane",   help="Filter by lane (for list)")
    parser.add_argument("--status", help="Filter by status (for list)")
    parser.add_argument("--reason", help="Decision reason (required for decision actions)")
    parser.add_argument("--fields", help="Comma-separated fields to redact")
    parser.add_argument("--set",    dest="set_json",
                        help="JSON object of field updates for rewrite, e.g. '{\"title\":\"new\"}'")
    parser.add_argument("--new-lane",  help="New lane for reclassify")
    parser.add_argument("--merge-ids", help="Comma-separated candidate IDs for merge")
    parser.add_argument("action",       nargs="?", default="list",
                        help="Command: list|inspect|approve|reject|redact|rewrite|reclassify|merge|request-more-evidence|audit")
    parser.add_argument("candidate_id", nargs="?", default=None,
                        help="Candidate ID (for inspect and decision commands)")
    args = parser.parse_args()

    q = ReviewQueue(Path(args.candidates), Path(args.out))
    candidates = q.load_candidates()
    decisions  = q.load_decisions()
    action     = args.action

    op_id   = args.operator_id
    op_role = args.operator_role

    if action == "list":
        q.cmd_list(candidates, decisions, lane=args.lane, status=args.status)

    elif action == "inspect":
        if not args.candidate_id:
            _fail("inspect requires a candidate_id argument")
        q.cmd_inspect(candidates, decisions, args.candidate_id)

    elif action == "audit":
        q.cmd_audit(candidates, decisions)

    elif action == "approve":
        if not args.candidate_id: _fail("approve requires a candidate_id argument")
        if not args.reason:        _fail("approve requires --reason")
        q.cmd_approve(candidates, decisions, args.candidate_id, op_id, op_role, args.reason)

    elif action == "reject":
        if not args.candidate_id: _fail("reject requires a candidate_id argument")
        if not args.reason:        _fail("reject requires --reason")
        q.cmd_reject(candidates, decisions, args.candidate_id, op_id, op_role, args.reason)

    elif action == "redact":
        if not args.candidate_id: _fail("redact requires a candidate_id argument")
        if not args.reason:        _fail("redact requires --reason")
        fields = [f.strip() for f in (args.fields or "").split(",") if f.strip()]
        q.cmd_redact(candidates, decisions, args.candidate_id, op_id, op_role, args.reason, fields)

    elif action == "rewrite":
        if not args.candidate_id: _fail("rewrite requires a candidate_id argument")
        if not args.reason:        _fail("rewrite requires --reason")
        if not args.set_json:      _fail("rewrite requires --set <json-object>")
        try:
            set_fields = json.loads(args.set_json)
        except json.JSONDecodeError as e:
            _fail(f"--set is not valid JSON: {e}")
        if not isinstance(set_fields, dict):
            _fail("--set must be a JSON object")
        q.cmd_rewrite(candidates, decisions, args.candidate_id, op_id, op_role, args.reason, set_fields)

    elif action == "reclassify":
        if not args.candidate_id: _fail("reclassify requires a candidate_id argument")
        if not args.reason:        _fail("reclassify requires --reason")
        if not args.new_lane:      _fail("reclassify requires --new-lane")
        q.cmd_reclassify(candidates, decisions, args.candidate_id, op_id, op_role, args.reason, args.new_lane)

    elif action in ("merge",):
        if not args.reason:    _fail("merge requires --reason")
        if not args.merge_ids: _fail("merge requires --merge-ids <id1,id2,...>")
        ids = [i.strip() for i in args.merge_ids.split(",") if i.strip()]
        q.cmd_merge(candidates, decisions, ids, op_id, op_role, args.reason)

    elif action in ("request-more-evidence", "request_more_evidence"):
        if not args.candidate_id: _fail("request-more-evidence requires a candidate_id argument")
        if not args.reason:        _fail("request-more-evidence requires --reason")
        q.cmd_request_more_evidence(candidates, decisions, args.candidate_id, op_id, op_role, args.reason)

    else:
        _fail(f"unknown action: {action!r}. Valid actions: list, inspect, audit, approve, reject, "
              f"redact, rewrite, reclassify, merge, request-more-evidence")


if __name__ == "__main__":
    main()
