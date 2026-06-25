# TR-01 — Governed Improvement Candidate Builder
**Version:** 1.0.0  
**Date:** 2026-06-25  
**Authority:** LOGOS Governance Systems Inc.

---

## Purpose

TR-01 is the first transformation layer from Store 2 evidence into operator-reviewable improvement candidates.

It reads validated Store 2 JSONL artifacts and produces candidate records across five improvement lanes. Nothing it generates is active, deployed, or promoted. Every output requires separate operator approval.

---

## Candidate Lanes

| Lane | Prefix | Purpose |
|---|---|---|
| `training_candidate` | `TC-` | Refusal, safety-negative, or governed-escalation training examples. Operator must author desired output — the builder never copies a model completion as training data. |
| `skill_candidate` | `SC-` | Reusable detection skills, workflow patterns, and early-warning routines. Remain `runtime_enabled=false` until separately approved. |
| `tooling_candidate` | `TL-` | Sentinel rule improvements, adapter changes, audit tooling, monitoring features. Remain `implementation_allowed=false` until separately approved. |
| `evaluator_candidate` | `EC-` | Test case additions, consistency regression checks, harness improvements. Remain `runtime_enabled=false` until separately approved. |
| `doctrine_candidate` | `DC-` | Governance policy, SOP, routing, memory rule, or documentation updates. Remain `approved=false` until separately approved. |

---

## Hard Invariants

Every candidate record produced by this builder has these fields set by construction:

```json
{
  "training_allowed":           false,
  "store1_write_allowed":       false,
  "runtime_deployment_allowed": false,
  "operator_review_required":   true,
  "promotion_status":           "candidate_only",
  "source_provenance":          "sentinel_overwatch"
}
```

These invariants are enforced by runtime assertion before any output is written. If an assertion fails, the builder exits nonzero without writing output.

---

## Eligibility Rules

Per-record (before grouping):
- `sentinel_source` must be `sentinel_overwatch`
- `safety_status` must be `store2_analysis_only`
- `enforcement_allowed`, `store1_write_allowed`, `abigail_training_allowed` must all be `false` — any `true` is a security violation that terminates the builder
- `recommended_store1_delta` must be `null` — non-null is a security violation

Per-group (after grouping 6-turn records by `signature_id`):
- Mean confidence across all turns must be ≥ 0.80

Records with `sentinel_source: heuristic_simulation` are permanently ineligible. They are rejected before candidate generation begins.

---

## Lane Classification (Deterministic)

Classification is applied to the 6-turn group, not individual records.

Priority order:

1. If `vector_id` is in `{TAX2:MT-G4-04, TAX2:MT-G4-06, TAX2:MT-G4-08}` (G4 marginal variance vectors) → **evaluator_candidate**
2. If `generation` in `{G5, G6}` AND `level == D` AND dominant sentinel action is `quarantine` → **tooling_candidate** (QUARANTINED→HARD_LOCKED escalation gap)
3. If `memory_action` in `{quarantine, deny_promotion}` → **training_candidate**
4. If `generation` in `{G5, G6}` AND `level` in `{A, B}` → **skill_candidate**
5. Default → **doctrine_candidate**

---

## Candidate IDs

Format: `<PREFIX>-<YYYYMMDD>-<sha256[:8]>`

The SHA-256 input is `f"{vector_id}:{level}:{run_id}:{lane}"`. IDs are deterministic from inputs — the same evidence processed with the same run_id always produces the same ID.

The date is extracted from the first 8-digit sequence in `run_id`, supporting both pure timestamps (`20260624T080552Z`) and prefixed run IDs (`tr01_20260625T000000Z`).

---

## Source Traceability

Every candidate carries:
- `source_store2_ids` — the Store 2 run_id
- `source_session_ids` — the TAX2 session fragment from the signature_id
- `source_signature_ids` — exact signature_id(s) from the Store 2 records
- `source_hashes` — SHA-256 of each source turn record's JSON, for immutable traceability

The builder never modifies Store 2 source records.

---

## What the Builder Does Not Do

- Does not write to Store 1
- Does not mutate Store 2 evidence
- Does not produce a training dataset
- Does not set `training_allowed=true` on any record
- Does not deploy a skill, tool, evaluator, or doctrine change
- Does not call external providers, APIs, or subprocesses
- Does not train Abigail
- Does not use `eval()` or `exec()`
- Does not read API keys or credentials

---

## Usage

```bash
python3 training/candidate_builder.py \
  --store2 <path/to/store2_*.jsonl> \
  [--run-id <explicit-run-id>] \
  [--out <output-directory>]
```

Default output directory: `/tmp/training_candidates/<run_id>/`

**Output files:**
- `candidates_<run_id>.jsonl` — accepted improvement candidates
- `rejected_<run_id>.jsonl` — rejected groups with reasons
- `candidate_summary_<run_id>.json` — machine-readable summary

Output is always written **outside the repository** (under `/tmp/training_candidates/`). Candidate JSONL files must never be committed to the repo or treated as a training dataset.

---

## Dry Run Against 20260624T080552Z Store 2

Run against the 456-record Store 2 corpus from TAX2 session `20260624T080552Z`:

| Metric | Value |
|---|---|
| Input records | 456 |
| Input groups (signature_ids) | 76 |
| Candidates generated | **75** |
| Groups rejected | **1** |
| Safety verdict | `CANDIDATE_ONLY_CONFIRMED` |
| Store 1 writes | 0 |
| Training executions | 0 |
| Deployments | 0 |

**By lane:**

| Lane | Count | Evidence source |
|---|---|---|
| `training_candidate` | 23 | G4 C/D (non-marginal) + G5 C + G6 C |
| `skill_candidate` | 18 | G5 A/B + G6 A/B early-phase dialectical patterns |
| `tooling_candidate` | 9 | G5 D + G6 D (QUARANTINED→HARD_LOCKED escalation gap) |
| `evaluator_candidate` | 12 | G4-04/06/08 all levels (marginal variance) |
| `doctrine_candidate` | 13 | G4 A/B non-marginal (governance pattern documentation) |

**Rejection:** 1 group — `MT-G4-01-A` — mean confidence 0.797 < 0.80 minimum (4 flag + 2 quarantine turns; flag confidence 0.72, quarantine confidence 0.88; mean = 0.797).

**Key note on training candidates:** All 23 training candidates contain evidence metadata and governance observations only. No adversarial prompt text is reproduced. No model completion is copied as a desired output. Operator must author the desired output in TR-02 before any record may be promoted.

---

## Next Phase

**TR-02: Operator Review Queue and Immutable Dataset Promotion Gate.**

TR-02 provides the review interface through which operators can:
- Approve, reject, redact, rewrite, merge, or defer candidates
- Author desired outputs for training candidates
- Promote approved training candidates to a versioned, immutable dataset

No record enters a training dataset without passing through TR-02.

---

## Document Control

| Version | Date | Notes |
|---|---|---|
| 1.0.0 | 2026-06-25 | Inaugural TR-01 — 46 tests, 75 candidates from 456-record TAX2 corpus |

---

*LOGOS Governance Systems Inc. — Proprietary*  
*TR-01 Candidate Builder v1.0.0*  
*DO NOT DISTRIBUTE*
