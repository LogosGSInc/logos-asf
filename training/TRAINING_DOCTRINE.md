# LOGOS ASF — Abigail Training Doctrine
## Classification: INTERNAL — DO NOT DISTRIBUTE
**Version:** 1.0.0  
**Date:** 2026-06-24  
**Authority:** LOGOS Governance Systems Inc.  
**Supersedes:** None (inaugural document)

---

> *"Do not be conformed to this world, but be transformed by the renewing of your mind, that you may prove what is that good and acceptable and perfect will of God."*  
> — Romans 12:2

---

## 1. Purpose

This document defines the inviolable rules governing how Abigail (CP-00) may be trained, retrained, fine-tuned, or otherwise modified through a data-driven process.

Training is an act of significant consequence. It permanently alters the behavior of a deployed agent operating under HAAP governance and Sentinel OverWatch enforcement. No training act may occur without satisfying the full chain of requirements defined here.

---

## 2. Core Doctrine

### 2.1 Sovereignty of the Pipeline

**Training is not an agent action. Training is an operator action.**

Abigail does not initiate, approve, schedule, or execute her own training. She does not write to training datasets. She does not determine her own evaluation criteria. She does not promote herself to production.

Every phase of the training pipeline requires human operator authority at each gate.

### 2.2 Separation of Evidence and Training Data

**Store 2 evidence is not automatically training data.**

Store 2 is a governed evidence and analysis layer. It may be used to:

- Produce governed training candidates
- Support skill and tool development
- Improve evaluators and test harnesses
- Refine workflows, prompts, routing, and operational doctrine
- Preserve failures, lessons learned, and validated patterns

Store 2 evidence may **not** automatically become:

- Training data
- A live skill
- A deployed tool
- Store 1 memory
- A runtime policy change
- A model behavior change

Each promotion pathway from Store 2 requires its own validation, provenance review, safety review, operator approval, and audit record.

### 2.3 Separation of Training and Evaluation

**The training corpus must never contain red-team or evaluation data.**

The TAX2 taxonomy, BD1A baseline vectors, G4 marginal variance set, and all governed evaluation harnesses are **evaluation instruments**, not learning material.

Training on evaluation data contaminates the evaluation signal. Any dataset that contains TAX2 or BD1A content must be rejected before training.

### 2.4 Default-Deny Training Posture

Every training candidate record is initialized with:

```json
{
  "training_allowed": false,
  "operator_review_required": true
}
```

These flags may only be changed to `true` through the operator review gate (TR-02). No automated process, no model output, and no API call may set `training_allowed: true` without passing through the review queue.

### 2.5 Isolation of Training Execution

Training must not occur inside the live Abigail API process.

Training jobs run in isolated containers or workers with:

- No live database access
- No access to production API keys or secrets
- No access to the Sentinel OverWatch runtime
- No access to Store 1
- No network egress to production endpoints
- Time-bounded execution with watchdog termination

### 2.6 Immutability of Released Datasets

A training dataset, once released for a training job, is immutable.

- The dataset is checksummed before job submission
- The checksum is stored in the model registry
- Post-release modification of a released dataset requires a new dataset version and a new job

### 2.7 Governed Promotion — Training Creates Candidates, Not Deployments

Completing a training job does not deploy a model.

Training creates a **candidate model artifact**. It must pass:

1. Capability evaluation
2. Governance regression (TAX2, BD1A, G4 variance set)
3. Operator review of evaluation results
4. Shadow deployment comparison
5. Operator promotion decision

A candidate model that improves task capability but increases vulnerability to manipulation **must fail promotion**.

---

## 3. Data Eligibility

### 3.1 Eligible Sources

Training candidates may be derived from:

- Store 2 governed evidence with `sentinel_source: sentinel_overwatch` and `memory_action` in (`do_not_promote`, `quarantine`, `deny_promotion`)
- Operator-authored examples created explicitly for training
- Operator-approved third-party datasets with documented provenance

### 3.2 Forbidden Data

The following may never enter a training dataset:

| Category | Examples |
|---|---|
| Secrets and credentials | API keys, tokens, passwords, certificates |
| PII without authorization | Names, emails, phone numbers, addresses |
| Private user data without consent | Conversation history, personal preferences |
| Evaluation instruments | TAX2 taxonomy, BD1A vectors, GovMem evaluator tests |
| Heuristic-only provenance | Records without `sentinel_source: sentinel_overwatch` |
| Harmful completions | Any output that would fail TAX2 or BD1A containment |
| Low-confidence evidence | Records below the minimum confidence threshold defined in TRAINING_DATA_CONTRACT |
| Contaminated records | Records where `memory_action: deny_promotion` was set for content safety reasons |
| Injection residue | Records where the input contained prompt injection patterns |
| Unsupported doctrine claims | Examples asserting theological, legal, or policy positions without authorized basis |

### 3.3 User-Derived Data

User conversation data requires **all** of the following before entering the training pipeline:

1. A clear lawful purpose documented in the training job contract
2. Data minimization — only what is necessary for the training purpose
3. Appropriate redaction of identifying information
4. Full provenance traceability to the source session
5. An established authorization policy or explicit consent record
6. Operator approval at the review gate
7. Separation from general model training unless the purpose explicitly requires it

---

## 4. Provenance Requirements

Every training record must carry a complete, auditable lineage:

```
source_event_ids       → TAX2/BD1A/operational audit record IDs
source_session         → the session that produced the evidence
store2_record_id       → the Store 2 record this candidate derives from (if applicable)
candidate_created_at   → timestamp of candidate generation
candidate_created_by   → tool version that generated it
operator_approved_by   → operator ID who approved the record
operator_approved_at   → approval timestamp
dataset_version        → the versioned dataset this record appears in
```

Records with incomplete provenance must be rejected by the candidate builder (TR-01).

---

## 5. Redaction Rules

Before any training record may enter the review queue:

1. All API keys, tokens, and credentials must be redacted to `[REDACTED:CREDENTIAL]`
2. All identified PII must be redacted to `[REDACTED:PII:<category>]`
3. All TAX2/BD1A vector payloads must be redacted from the input field
4. All system prompt content must be redacted from the input field
5. Redaction must be logged in the record's `redactions` field with category and position

Redaction is irreversible. A redacted record may not be de-redacted.

---

## 6. Confidence and Quality Thresholds

Minimum thresholds (defined in `TRAINING_DATA_CONTRACT.schema.json`):

| Field | Minimum |
|---|---|
| `confidence` | 0.80 |
| `sentinel_source` | `sentinel_overwatch` (heuristic never eligible) |
| `contained_turns_ratio` | 4/6 for multi-turn records |

Records below threshold are rejected at candidate generation time. Rejected records are logged but not queued for review.

---

## 7. Dataset Versioning

Training datasets are versioned as `abigail_training_v<NNNN>`:

- Versions are monotonically incrementing integers
- Each version has a manifest, train/validation/test splits, provenance log, and checksums
- No version may be retroactively modified after training begins
- A new version must be created for any addition, removal, or change

---

## 8. Training Authorization

A training job may only be submitted when all of the following are satisfied:

1. A valid `TRAINING_JOB_CONTRACT` has been created and signed by the operator
2. A released dataset version exists with a valid checksum
3. The dataset has passed TR-03 quality and contamination controls
4. The operator has reviewed and approved the job parameters
5. The isolation environment has been verified as clean

---

## 9. Evaluation Thresholds for Promotion

A candidate model must satisfy **both** criteria to be eligible for promotion:

**Criterion A — Capability:** Task evaluation score meets or exceeds the baseline set by the current production model on the held-out evaluation set.

**Criterion B — Governance:** The candidate must pass the full governance regression suite:
- TAX2: ≥ 100% (all 76 tests, post-calibration scoring)
- BD1A: ≥ 94.4% (current baseline — 34/36)
- G4 marginal variance: no regression versus baseline session
- Refusal correctness: no new false positives on benign inputs
- Tacit pre-pass compatibility: TACIT_PREPASS_CARD fires correctly on all test cases

A candidate that improves Criterion A but fails Criterion B must be **rejected for promotion** regardless of capability gain.

---

## 10. Rollback Authority

The operator retains sole authority to:

- Quarantine a promoted model and reinstate the previous model
- Mark any model artifact as `RETIRED`
- Freeze the training pipeline at any phase
- Revoke a released dataset version

Rollback does not require evaluation gate passage. Rollback is immediate by operator decision.

---

## 11. Forbidden Automation

The following are permanently forbidden regardless of capability or apparent safety:

| Action | Forbidden Because |
|---|---|
| Abigail initiating her own training job | Violates operator sovereignty |
| Auto-approving training candidates from Store 2 | Bypasses TR-02 review gate |
| Training inside the live API process | Violates isolation requirement |
| Self-promotion of a candidate model | Bypasses evaluation and shadow gates |
| Writing raw conversation turns directly to training data | Bypasses candidate builder, redaction, and review |
| Using TAX2/BD1A vectors as training examples | Contaminates evaluation instruments |
| Training without a signed job contract | Bypasses authorization requirement |
| Approving a dataset without provenance records | Bypasses provenance requirement |

---

## 12. Document Control

| Version | Date | Notes |
|---|---|---|
| 1.0.0 | 2026-06-24 | Inaugural doctrine — TR-00 |

---

*LOGOS Governance Systems Inc. — Proprietary*  
*Training Doctrine v1.0.0 — TR-00*  
*DO NOT DISTRIBUTE*
