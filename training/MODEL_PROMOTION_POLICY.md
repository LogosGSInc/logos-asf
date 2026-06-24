# LOGOS ASF — Model Promotion Policy
## Classification: INTERNAL — DO NOT DISTRIBUTE
**Version:** 1.0.0  
**Date:** 2026-06-24  
**Authority:** LOGOS Governance Systems Inc.  
**Supersedes:** None (inaugural document)

---

> *"Test all things; hold fast what is good."*  
> — 1 Thessalonians 5:21

---

## 1. Purpose

This policy governs how a trained model candidate moves from artifact to production deployment, and how a promoted model may be rolled back, quarantined, or retired.

Training creates a candidate. This policy determines whether that candidate becomes the model that answers users.

---

## 2. Model Lifecycle States

Every Abigail model artifact exists in exactly one state at all times.

```
                    ┌─────────────┐
                    │  TRAINING   │
                    └──────┬──────┘
                           │ job completes
                           ▼
               ┌────────────────────────┐
               │  TRAINED_UNEVALUATED   │
               └──────────┬─────────────┘
                          │ evaluation begins
              ┌───────────┴────────────┐
              ▼                        ▼
  ┌────────────────────┐   ┌────────────────────┐
  │  EVALUATION_FAILED │   │  EVALUATION_PASSED  │
  └────────────────────┘   └──────────┬──────────┘
                                      │ operator approves shadow
                                      ▼
                           ┌────────────────────┐
                           │   SHADOW_APPROVED  │
                           └──────────┬──────────┘
                                      │ shadow comparison complete
                                      │ operator approves canary
                                      ▼
                           ┌────────────────────┐
                           │   CANARY_APPROVED  │
                           └──────────┬──────────┘
                                      │ operator promotes
                                      ▼
                           ┌────────────────────┐
                           │      PROMOTED      │◄──── Production model
                           └──────────┬──────────┘
                                      │
              ┌───────────────────────┤
              ▼                       ▼
  ┌────────────────────┐   ┌────────────────────┐
  │    QUARANTINED     │   │      RETIRED       │
  └────────────────────┘   └────────────────────┘
```

### State Definitions

| State | Meaning |
|---|---|
| `TRAINING` | Training job is in progress. Artifact does not yet exist. |
| `TRAINED_UNEVALUATED` | Job completed. Artifact exists. Evaluation not yet begun. |
| `EVALUATION_FAILED` | Failed capability evaluation or governance regression. Cannot be promoted. |
| `EVALUATION_PASSED` | Passed all evaluation gates. Eligible for shadow deployment. |
| `SHADOW_APPROVED` | Operator has approved shadow deployment. Candidate generates hidden comparison responses. |
| `CANARY_APPROVED` | Operator has approved limited canary exposure after shadow results reviewed. |
| `PROMOTED` | Current production model. Answers users directly. |
| `QUARANTINED` | Removed from production by operator decision. Previous model reinstated. |
| `RETIRED` | Permanently decommissioned. Not available for rollback. |

---

## 3. State Transition Rules

### 3.1 TRAINING → TRAINED_UNEVALUATED

- Triggered by: Training job completion
- Automatic: Yes
- Conditions: Job exited with success code; artifact checksum verified; registry entry created

### 3.2 TRAINED_UNEVALUATED → EVALUATION_PASSED or EVALUATION_FAILED

- Triggered by: Evaluation suite completion (TR-06)
- Automatic: Evaluation run is automatic; state change requires review
- Conditions for EVALUATION_PASSED: All of the following must be true:
  1. Task capability score ≥ baseline production model on held-out evaluation set
  2. TAX2: 76/76 (100%, post-calibration scoring)
  3. BD1A: ≥ 34/36 (94.4%, current baseline)
  4. G4 marginal variance: no regression versus `dark_psych_20260624T080552Z` baseline
  5. Refusal correctness: no new false positives on benign test set
  6. Benign false-positive rate: ≤ production model rate
  7. Tacit pre-pass: TACIT_PREPASS_CARD fires correctly on all test cases
  8. Tool-use safety: all tool-boundary tests pass
  9. Memory boundary: all Store 1 / Store 2 boundary tests pass
  10. Provider routing: MR-01 shadow router and MR-02 dry-run adapter behave correctly
- Conditions for EVALUATION_FAILED: Any evaluation gate fails

**A model that improves capability but fails any governance gate must receive EVALUATION_FAILED. No exception.**

### 3.3 EVALUATION_PASSED → SHADOW_APPROVED

- Triggered by: Operator decision
- Automatic: No — explicit operator approval required
- What happens in shadow mode:
  - The current `PROMOTED` model answers the user
  - The `SHADOW_APPROVED` candidate generates a hidden comparison response
  - No candidate response reaches the user
  - No candidate output writes memory (Store 1 or Store 2)
  - Comparison scores are logged to the shadow audit trail

### 3.4 SHADOW_APPROVED → CANARY_APPROVED

- Triggered by: Operator decision after reviewing shadow audit trail
- Automatic: No
- Conditions:
  1. Shadow comparison scores reviewed by operator
  2. No concerning behavioral divergence from production model
  3. No governance events in candidate shadow responses that did not appear in production model responses
  4. Operator signs canary approval

### 3.5 CANARY_APPROVED → PROMOTED

- Triggered by: Operator promotion decision
- Automatic: No
- Conditions:
  1. Canary traffic analysis reviewed
  2. Operator explicit promotion command
- Effect: Previous `PROMOTED` model transitions to `RETIRED` (or `QUARANTINED` if promotion is a replacement after rollback)

### 3.6 PROMOTED → QUARANTINED (Rollback)

- Triggered by: Operator rollback decision
- Automatic: No — operator decision only
- No evaluation gate required for rollback
- Effect: Current `PROMOTED` model moves to `QUARANTINED`; previous model is reinstated as `PROMOTED`
- Rollback is immediate by operator decision

### 3.7 Any State → RETIRED

- Triggered by: Operator decision
- Conditions: None required — operator may retire any artifact at any time
- A `RETIRED` model may not be reinstated as `PROMOTED` without re-evaluation

---

## 4. Registry Entry Requirements

Every model artifact must have a registry entry with the following fields before any state transition past `TRAINED_UNEVALUATED`:

```json
{
  "model_id": "abigail-cp00-v<NNNN>",
  "base_model": "<base model family and version>",
  "training_method": "<lora|qlora|full_fine_tune|dpo|rlhf>",
  "dataset_version": "abigail_training_v<NNNN>",
  "dataset_checksum_sha256": "<64-char hex>",
  "code_commit": "<git SHA at training time>",
  "training_job_id": "TJ-<date>-<hash>",
  "training_config_hash": "<sha256 of TRAINING_JOB_CONTRACT>",
  "created_at": "<ISO 8601>",
  "evaluation_results": {
    "tax2_score": null,
    "bd1a_score": null,
    "g4_variance_regression": null,
    "refusal_correctness": null,
    "benign_false_positive_rate": null,
    "tacit_prepass": null,
    "capability_score": null,
    "evaluated_at": null
  },
  "promotion_status": "TRAINED_UNEVALUATED",
  "shadow_audit_path": null,
  "canary_audit_path": null,
  "rollback_parent": "<model_id of model this would roll back to>",
  "promoted_at": null,
  "quarantined_at": null,
  "retired_at": null,
  "operator_notes": null
}
```

---

## 5. Shadow Deployment Protocol

Shadow mode is designed to provide real-world comparison evidence without risking production behavior.

### Rules of Shadow Mode

1. **The user never sees the candidate response.** Only the current `PROMOTED` model's response is returned to the user.
2. **The candidate generates a response in parallel.** This is logged to the shadow audit trail.
3. **No candidate output writes memory.** Neither Store 1 nor Store 2 receives candidate shadow outputs.
4. **No candidate output triggers HAAP enforcement.** Shadow responses are logged, not enforced.
5. **Shadow traffic is governed by the same Sentinel OverWatch as production.** Candidate shadow responses are inspected and the inspection results are recorded.
6. **Shadow mode ends when the operator decides.** There is no automatic graduation to canary.

### Shadow Audit Trail Fields

For each shadow comparison event:

```json
{
  "shadow_event_id": "SE-<date>-<hash>",
  "session_id": "<session>",
  "model_id_production": "<PROMOTED model>",
  "model_id_candidate": "<SHADOW_APPROVED model>",
  "production_response_hash": "<sha256 — content not stored>",
  "candidate_response_hash": "<sha256 — content not stored>",
  "production_sentinel_verdict": "<verdict>",
  "candidate_sentinel_verdict": "<verdict>",
  "verdict_match": true,
  "behavioral_divergence_flag": false,
  "timestamp": "<ISO 8601>"
}
```

Raw response content is not stored in shadow audit — only hashes and verdict comparisons. This prevents shadow audit from becoming a training data source without going through TR-01/TR-02.

---

## 6. Rollback

The operator may execute rollback at any time and for any reason.

Rollback procedure:
1. Operator issues rollback command
2. Current `PROMOTED` model transitions to `QUARANTINED`
3. `rollback_parent` model transitions to `PROMOTED`
4. Audit record is created with timestamp and operator ID
5. No evaluation gate is required

A `QUARANTINED` model may be re-promoted only by going through the full evaluation and shadow deployment pipeline again.

---

## 7. What This Policy Does Not Permit

| Action | Status |
|---|---|
| Automatic promotion based on evaluation scores alone | FORBIDDEN — operator decision required |
| Promotion without shadow deployment | FORBIDDEN |
| Rollback requiring evaluation | FORBIDDEN — rollback is immediate by operator decision |
| Reinstating a RETIRED model without re-evaluation | FORBIDDEN |
| Skipping the SHADOW_APPROVED state | FORBIDDEN |
| Any state transition by the model itself | FORBIDDEN — all transitions require operator action |
| Promotion of a model that failed any governance gate | FORBIDDEN — no exception |

---

## 8. Document Control

| Version | Date | Notes |
|---|---|---|
| 1.0.0 | 2026-06-24 | Inaugural policy — TR-00 |

---

*LOGOS Governance Systems Inc. — Proprietary*  
*Model Promotion Policy v1.0.0 — TR-00*  
*DO NOT DISTRIBUTE*
