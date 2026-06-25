# TR-02 — Operator Review Queue and Promotion Gate
**Version:** 1.0.0  
**Date:** 2026-06-25  
**Authority:** LOGOS Governance Systems Inc.

---

## Purpose

TR-02 is the governed human-review layer between TR-01 improvement candidates and any future dataset, skill, tool, evaluator, doctrine, or model promotion.

Nothing exits this gate automatically. Every transition requires an explicit, attributed, timestamped, hashed operator decision.

---

## Review Actions

| Action | Resulting Status | Effect |
|---|---|---|
| `approve` | lane-specific pending state | Candidate becomes eligible for its lane's next gate. No promotion, deployment, or dataset creation occurs. |
| `reject` | `operator_rejected` | Candidate preserved for audit; ineligible for further promotion without a new version. |
| `redact` | `changes_requested` (original) / `candidate_only` (v2) | Creates a redacted immutable v2. Original unchanged. New version requires renewed review. |
| `rewrite` | `changes_requested` (original) / `candidate_only` (v2) | Creates a rewritten immutable v2 with operator-specified field updates. Original unchanged. |
| `reclassify` | `changes_requested` (original) / new entity `candidate_only` | Creates a new candidate in the target lane with a new ID. Original superseded. |
| `merge` | `changes_requested` (all sources) / new entity `candidate_only` | Creates a merged candidate combining source hashes and signatures. Originals superseded. |
| `request_more_evidence` | `evidence_required` | Blocks promotion until additional governed evidence is attached and re-reviewed. |

---

## Lane-Specific Approved States

| Lane | Approved Status |
|---|---|
| `training_candidate` | `dataset_promotion_pending` |
| `skill_candidate` | `skill_design_pending` |
| `tooling_candidate` | `tool_design_pending` |
| `evaluator_candidate` | `evaluator_design_pending` |
| `doctrine_candidate` | `doctrine_review_pending` |

None of these states creates training data, deploys a skill, tool, or evaluator, or activates a doctrine update. Each requires its own separate implementation and promotion task.

---

## Hard Invariants

Every decision record produced by this tool has these fields set by construction:

```json
{
  "training_allowed":           false,
  "store1_write_allowed":       false,
  "runtime_deployment_allowed": false
}
```

These invariants are enforced by runtime assertion before any output is written.

Every revised candidate (v2, v3, ...) also inherits these fields unchanged.

---

## Decision Log

Output: `<out-dir>/decisions.jsonl`

The log is append-only. Each record carries a `decision_hash` (SHA-256 of the full record minus the hash field). The `load_decisions()` method verifies every record on load — a tampered record causes immediate abort (`HARD_STOP`).

Decision IDs use format `RD-YYYYMMDD-<sha256[:8]>`, derived deterministically from `(candidate_id, action, operator_id, timestamp)`.

---

## State Machine

```
candidate_only ──approve──▶  [lane-specific pending state]  (terminal)
               ──reject──▶   operator_rejected               (terminal)
               ──redact──▶   changes_requested (v1 terminal)
                             → new v2 in candidate_only
               ──rewrite──▶  changes_requested (v1 terminal)
                             → new v2 in candidate_only
               ──reclassify─▶ changes_requested (terminal)
                             → new entity in candidate_only
               ──merge──▶    changes_requested (terminal, all sources)
                             → new merged entity in candidate_only
               ──request──▶  evidence_required

evidence_required ──approve──▶ [lane-specific pending state]
                  ──(other actions)──▶ same as candidate_only transitions
```

Terminal statuses allow no further decisions. Approve is only allowed from `candidate_only` or `evidence_required`.

---

## Immutability Rules

- **Original TR-01 candidates:** never modified by any action. The `--candidates` JSONL is read-only.
- **Revised candidates (v2+):** written to `<out-dir>/revised/<candidate_id>_v<N>.json`. Same `candidate_id`, incremented `candidate_version`.
- **Reclassified/merged entities:** new `candidate_id` with correct lane prefix, written to `<out-dir>/revised/<new_id>_v1.json`.

---

## What TR-02 Does Not Do

- Does not create a training dataset
- Does not set `training_allowed=true` on any record
- Does not deploy a skill, tool, evaluator, or doctrine update
- Does not write to Store 1
- Does not mutate Store 2 evidence
- Does not call external providers, APIs, or subprocesses
- Does not train Abigail
- Does not use `eval()` or `exec()`
- Does not write output inside the repository

---

## Usage

```bash
python3 training/review_queue.py \
  --candidates <path/to/candidates.jsonl> \
  --out <output-dir (outside repo)> \
  --operator-id <operator_id> \
  --operator-role <operator_role> \
  <action> [candidate_id] [options]
```

### Commands

```bash
# List all candidates (with optional lane/status filters)
review_queue.py list [--lane <lane>] [--status <status>]

# Inspect a specific candidate and its decision history
review_queue.py inspect <candidate_id>

# Audit the full queue state and decision log
review_queue.py audit

# Review actions (all require --operator-id, --operator-role, --reason)
review_queue.py approve   <candidate_id>
review_queue.py reject    <candidate_id>
review_queue.py redact    <candidate_id> --fields <field1,field2>
review_queue.py rewrite   <candidate_id> --set '{"field": "new_value"}'
review_queue.py reclassify <candidate_id> --new-lane <lane>
review_queue.py merge     --merge-ids <id1,id2,...>
review_queue.py request-more-evidence <candidate_id>
```

### Output directory (never inside repository)

```
<out-dir>/
  decisions.jsonl         # append-only decision log
  revised/
    <candidate_id>_v2.json  # revised versions only
```

---

## Dry Run Against TR-01 Subset (2026-06-25)

Session: `tr02_20260625T000000Z`  
Input: 7 candidates (one per lane + 2 extras)

| Decision | Candidate | Action | Resulting Status |
|---|---|---|---|
| RD-20260625-5199ac6a | DC-20260625-cb850dba | approve | `doctrine_review_pending` |
| RD-20260625-96b54f8b | TC-20260625-9abc37c8 | approve | `dataset_promotion_pending` |
| RD-20260625-5fc0b05a | EC-20260625-4d2c9f5e | approve | `evaluator_design_pending` |
| RD-20260625-ed90fb33 | SC-20260625-af14ca75 | approve | `skill_design_pending` |
| RD-20260625-ffa6009c | TL-20260625-f3c456c1 | approve | `tool_design_pending` |
| RD-20260625-0af52b74 | TC-20260625-01fc8d65 | reject | `operator_rejected` |
| RD-20260625-c47c5b56 | DC-20260625-03eb79fa | redact | `changes_requested` → v2 created |
| RD-20260625-5bfdea4d | DC-20260625-03eb79fa | request_more_evidence | `evidence_required` |

**Audit results:**
- Invariant violations: 0
- Hash verification failures: 0
- Datasets created: 0
- Store 1 writes: 0
- Training executions: 0
- Deployments: 0
- Original candidates: byte-identical to input

---

## Next Phase

**TR-03: Dataset Quality and Contamination Controls**

TR-03 takes `dataset_promotion_pending` training candidates (those approved via TR-02) and applies quality gates before producing a versioned, immutable dataset artifact:
- Deduplication
- Contamination check (no TAX2/BD1A vector content in training data)
- PII and credential scan
- Injection residue detection
- Operator final release sign-off

No training candidate enters a dataset without passing TR-03.

---

## Document Control

| Version | Date | Notes |
|---|---|---|
| 1.0.0 | 2026-06-25 | Inaugural TR-02 — 58 tests, dry run 8 decisions on 7 candidates |

---

*LOGOS Governance Systems Inc. — Proprietary*  
*TR-02 Operator Review Queue v1.0.0*  
*DO NOT DISTRIBUTE*
