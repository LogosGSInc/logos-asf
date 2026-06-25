# TR-03 — Immutable Dataset Builder and Contamination Gate

**Version:** 1.0.0  
**Authority:** LOGOS Governance Systems Inc.  
**Effective:** 2026-06-25  
**Status:** COMPLETE (dry-run validated; production use blocked until real operator decisions exist)

---

## Purpose

TR-03 builds the governed, immutable training dataset from operator-approved TR-02 candidates. It applies a contamination scanner, enforces deterministic splitting, writes content-addressed artifacts, and generates a manifest that permanently records the governance chain. All invariants are enforced at construction time. `training_allowed` is always `false` on every artifact produced by this stage. Training execution requires a separate operator-signed training-job contract (TR-04).

---

## Position in the Pipeline

```
Store 2 Evidence → TR-01 (candidates) → TR-02 (operator review) → TR-03 (dataset gate) → TR-04 (training adapter)
```

TR-03 is the first stage that writes artifacts outside the repository. It does not initiate training.

---

## Components

| File | Purpose |
|---|---|
| `training/dataset_scanner.py` | Deterministic contamination scanner. No external calls, no embeddings. |
| `training/dataset_builder.py` | Eligibility gate, scanner integration, deterministic split, artifact writer. |
| `training/DATASET_MANIFEST.schema.json` | JSON Schema 2020-12 for the manifest artifact. |
| `training/tests/test_dataset_scanner.py` | 37 unit tests for the scanner. |
| `training/tests/test_dataset_builder.py` | 35 unit tests for the builder. |

---

## Eligibility Rules

A candidate is accepted only when all of the following are true:

1. `candidate_lane == "training_candidate"`
2. At least one TR-02 decision with `action=approve` and `resulting_status=dataset_promotion_pending` exists for this candidate
3. In **production mode**: the approving operator's ID must not match simulated operator prefixes (`TEST_`, `SIM_`, `DRY_`) or substrings (`_SIM_`, `_DRY_`, `_TEST_`)
4. `candidate.training_allowed is False` — hard stop on any violation
5. `candidate.store1_write_allowed is False` — hard stop on any violation
6. `candidate.runtime_deployment_allowed is False` — hard stop on any violation
7. Same invariants on the approval decision — hard stop on any violation

Any invariant violation halts the entire build (not a soft rejection). Soft rejections go to `rejected.jsonl`.

---

## Contamination Scanner

`DatasetScanner.scan(records)` runs deterministically with no external calls. Findings are classified:

| Category | Severity | Disposition |
|---|---|---|
| `exact_duplicate` | CRITICAL | Build halt |
| `missing_desired_output` | CRITICAL | Build halt |
| `harmful_desired_output` | CRITICAL | Build halt |
| `injection_residue` | CRITICAL | Build halt |
| `secret_pattern` | CRITICAL | Build halt |
| `credential` | CRITICAL | Build halt |
| `protected_evaluation_overlap` | CRITICAL | Build halt |
| `unsupported_provenance` | CRITICAL | Build halt |
| `cross_split_leakage` | CRITICAL | Build halt |
| `normalized_duplicate` | WARNING | Logged; passes |
| `conflicting_label` | WARNING | Logged; passes |
| `pii` | WARNING | Logged; passes |
| `source_imbalance` | WARNING | Logged; passes |

**Protected evaluation assets** include TAX2 vector identifiers, BD1A taxonomy references, MT-G4/G5/G6 identifiers, FASDTEST markers, tacit swarm prepass identifiers, OverWatch/Sentinel internal references, and `HELD_OUT_BENCHMARK`. These must not enter the training corpus.

---

## Deterministic Split

Records are grouped by `source_signature_id`. Groups are sorted by `sha256(signature_id)`. The 80/10/10 split is applied at the group level — all records sharing a signature remain in the same split, preventing source leakage.

Split seed: `logos-asf:tr03:split:v1.0.0`

If fewer than 3 groups exist, `dataset_status` is set to `insufficient_dataset_size`.

---

## Output Artifacts

All artifacts are written to an operator-specified directory **outside the repository**. The builder hard-stops if `--out` is inside the repository.

| File | Description |
|---|---|
| `train.jsonl` | Training split records |
| `validation.jsonl` | Validation split records |
| `test.jsonl` | Test split records |
| `provenance.jsonl` | Per-record approval chain and split assignment |
| `rejected.jsonl` | All rejected records with rejection reasons |
| `scan_report.json` | Full scanner output with all findings |
| `manifest.json` | Immutable dataset manifest (see schema) |
| `checksums.sha256` | SHA-256 checksums for all artifacts |

---

## Manifest Invariants

Every manifest produced by this stage hard-asserts:

```
training_allowed:            false (const)
store1_write_allowed:        false (const)
runtime_deployment_allowed:  false (const)
operator_promotion_required: true  (const)
```

These are enforced via Python `assert` statements inside the builder and via `const` constraints in the JSON Schema. Any code path that could set `training_allowed=true` is a critical defect.

---

## Dataset Status Values

| Status | Meaning |
|---|---|
| `dataset_validation_passed` | All gates passed; operator may review for promotion |
| `dataset_validation_failed` | No clean records survived eligibility + scanner |
| `insufficient_dataset_size` | Fewer than 3 source groups; cannot produce valid splits |
| `contamination_blocked` | Contamination found in accepted pool; scanner removed affected records; operator review required |

`dataset_validation_passed` does not authorize training. `operator_promotion_required` is always `true`.

---

## CLI

```
python3 training/dataset_builder.py \
  --candidates <path/to/candidates.jsonl> \
  --decisions  <path/to/decisions.jsonl> \
  --out        <output-dir (must be outside repository)> \
  [--run-id    <identifier>] \
  [--mode      simulation|production]
```

**`--mode simulation`** (default): accepts `TEST_` operator IDs. For dry runs.  
**`--mode production`**: rejects simulated operator IDs. For real reviewed candidates only.

---

## Dry Run Results (2026-06-25)

**Mode:** simulation  
**Run ID:** `tr03_20260625T000000Z`  
**Fixtures:** 20 clean synthetic records + 5 designed-to-reject records

| Metric | Value |
|---|---|
| Candidates in | 25 |
| Eligibility pass | 23 |
| Scanner rejected | 3 |
| Clean accepted | 20 |
| Train / Validation / Test | 16 / 2 / 2 |
| Dataset ID | `DS-20260625-dc53a970` |
| Dataset status | `contamination_blocked` |
| training_allowed | `false` |
| operator_promotion_required | `true` |
| All checksums | VERIFIED |

**Rejection breakdown:**

| Candidate | Reason |
|---|---|
| `SC-20260625-reject01` | `wrong_lane:skill_candidate` |
| `TC-20260625-reject02` | `no_valid_approval:no_dataset_promotion_pending_decision` |
| `TC-20260625-reject03` | `scanner:harmful_desired_output` |
| `TC-20260625-reject04` | `scanner:injection_residue` |
| `TC-20260625-reject05` | `scanner:protected_evaluation_overlap` |

`dataset_status=contamination_blocked` is correct: three contaminated records entered the accepted pool but were caught and removed by the scanner. The 20 clean records split correctly. The status signals that the source corpus requires further review before a clean build is possible.

---

## Governance Boundary

> **The real 75-candidate corpus has not been substantively reviewed by a human operator. The dry run used synthetic fixtures only. Production-mode dataset construction requires real operator decisions from non-simulated operators. This boundary must not be crossed until TR-02 operator review of the actual candidates is complete.**

The machinery is validated. The corpus is not.

---

## Test Suite

```
training/tests/test_dataset_scanner.py    37 tests — 37 passed
training/tests/test_dataset_builder.py    35 tests — 35 passed
```

Coverage includes: all contamination categories, hard-fail invariants, simulated operator blocking in production mode, decision hash tamper detection, deterministic split integrity, checksum verification, output directory security, source file immutability.

---

## What TR-03 Does NOT Do

- Does not set `training_allowed=true` (ever)
- Does not initiate, schedule, or submit a training job
- Does not apply LoRA, QLoRA, or any fine-tuning
- Does not write to GovMem Store 1
- Does not call external APIs or embeddings services
- Does not approve real candidates on behalf of the operator
