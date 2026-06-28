# TR-06E: Evaluation Dossier and Readiness Aggregator

**Version**: 1.0.0  
**Status**: Implemented (aggregation and readiness classification only — no inference, no promotion)  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-28  
**Requires**: TR-06A, TR-06B, TR-06C, TR-06D  
**Not implemented here**: Real model inference, provider execution, model promotion, deployment, training, TR-07

---

## What TR-06E Creates

1. **`training/EVALUATION_DOSSIER.schema.json`** — 26-field typed contract for one sealed candidate evaluation dossier.
2. **`training/evaluation_dossier.py`** — aggregator: collects TR-06A reports, TR-06C plans, TR-06D stub reports; classifies readiness; produces a checksum-addressed sealed dossier.
3. **`training/tests/test_evaluation_dossier.py`** — 117-test suite covering all readiness paths, input rejection guards, invariant validation, save/load, and module purity.
4. **`training/TR_06E_EVALUATION_DOSSIER_AND_READINESS_AGGREGATOR.md`** — this document.

TR-06E is the final pre-TR-07 audit checkpoint. It gathers all evaluation evidence and seals it into one checksum-addressed dossier without running inference, without changing model registry state, and without emitting a promotion decision.

---

## Architecture Position

```
TR-06A Metadata Evaluation Reports  ─┐
TR-06C Live Evaluation Plans        ─┼→  TR-06E Evaluation Dossier
TR-06D Stub Execution Reports       ─┘        ↓ readiness_state (not a promotion)
                                      [future TR-06Z audit seal]
                                             ↓ operator gate
                                      [future TR-07 shadow/canary]
```

---

## What TR-06E Is and Is Not

| Is | Is Not |
|---|---|
| A metadata-only evaluation dossier contract | Real inference |
| An aggregator for evaluation reports, plans, and stub reports | Live model evaluation |
| A readiness classifier (no promotion) | Model promotion |
| A checksum-addressed evidence package | Deployment |
| The final TR-06 pre-TR-07 checkpoint | Model training |
| | TR-07 shadow/canary |

---

## Dossier Schema

`EVALUATION_DOSSIER.schema.json` (draft 2020-12) defines 26 required fields with the following hard constants:

| Field | Value |
|---|---|
| `promotion_blocked` | const `true` |
| `promotion_decision_emitted` | const `false` |
| `operator_review_required` | const `true` |
| `real_model_inference_performed` | const `false` |
| `provider_calls_performed` | const `false` |
| `model_weights_loaded` | const `false` |
| `model_training_performed` | const `false` |
| `runtime_deployment_performed` | const `false` |
| `store1_writes_performed` | const `false` |

**Dossier ID:** `ED-<sha256[:16]>`, deterministic for same `candidate_artifact_id + sorted input ref IDs + readiness_state`.

**`dossier_hash`:** SHA-256 of canonical JSON content (sorted keys, excluding `dossier_hash` itself). Provides tamper-evidence.

**`previous_dossier_hash`:** chains dossiers chronologically. Null for the first dossier.

---

## Readiness State

`readiness_state` is one of four values. **No value constitutes promotion eligibility.** `promotion_blocked=true` is constant across all states.

| State | Meaning |
|---|---|
| `not_evaluated` | No evaluation inputs provided. Starting point. |
| `needs_more_evidence` | No blocks found, but fail/not_evaluated results remain, or only stub evidence exists without metadata reports. |
| `blocked` | A block or stub_block result was found, or a forbidden action was flagged in an input. Cannot proceed until cleared. |
| `metadata_ready` | No blocks, no fails, required metadata reports exist. **Not promotion.** Operator review still required before any next step. |

### Readiness rule precedence (highest to lowest)

1. Any `block` in gate results → `blocked`
2. Any `stub_block` or `blocked` in stub execution → `blocked`
3. No inputs at all → `not_evaluated`
4. Any `fail` or `not_evaluated` in gate summary → `needs_more_evidence`
5. Any `stub_fail` in stub summary → `needs_more_evidence`
6. Only stub evidence, no metadata reports → `needs_more_evidence`
7. No blocks, no fails, metadata reports present → `metadata_ready`

### `metadata_ready` is not promotion

`readiness_state='metadata_ready'` means no blocking evidence was found in the aggregated dossier inputs. It does **not** mean the candidate is ready for production. It does not change `promotion_blocked`. It does not open a promotion pathway. The `readiness_rationale` field explicitly states this.

Operator review is required regardless of readiness state. The next step after `metadata_ready` is a TR-06Z audit seal and subsequent operator decision — not automatic promotion.

### `needs_more_evidence` is expected before real live evals

Before TR-06D real model execution exists (which requires a separate operator-approved phase), all stub-only dossiers will classify as `needs_more_evidence`. This is correct behavior: stub execution is not behavioral evidence. The dossier honestly reflects that live behavioral evaluation has not occurred.

---

## Input Constraints

`build_evaluation_dossier` validates all inputs before building:

- All inputs must share the same `candidate_artifact_id`. Mixed candidates raise `EvaluationDossierInputError`.
- Any input with `promotion_blocked=false` is rejected.
- Any input with `promotion_decision_emitted=true` is rejected.
- Any stub execution report with `real_model_inference_performed=true`, `provider_calls_performed=true`, or `model_weights_loaded=true` is rejected.
- Any input containing `model_weights_path` or `adapter_checkpoint_path` is rejected.

---

## Public API

```python
from training.evaluation_dossier import (
    build_evaluation_dossier,
    validate_evaluation_dossier,
    compute_dossier_hash,
    summarize_metadata_reports,
    summarize_stub_execution_reports,
    classify_readiness,
    save_evaluation_dossier,
    load_evaluation_dossier,
    summarize_evaluation_dossier,
    assert_dossier_cannot_promote,
    load_json,
)

# Collect evidence from upstream phases
metadata_reports = [build_evaluation_report(c, gr) for gr in run_all_metadata_gates(c)]
plan = build_live_eval_plan(artifact_id, build_default_cases_for_candidate(artifact_id))
stub_report = execute_plan_with_stub_adapter(plan)

# Build dossier
dossier = build_evaluation_dossier(
    candidate_artifact_id="MA-abc123",
    metadata_reports=metadata_reports,
    live_eval_plans=[plan],
    stub_execution_reports=[stub_report],
    source_model_registry_ref="model_registry/MA-abc123",
)
# dossier["readiness_state"] in ("metadata_ready", "needs_more_evidence", "blocked", "not_evaluated")
# dossier["promotion_blocked"] == True  always
# dossier["promotion_decision_emitted"] == False  always

# Validate
validate_evaluation_dossier(dossier)

# Save to disk
path = save_evaluation_dossier(dossier, "/tmp/tr06e_dossiers")
# writes ed_{dossier_id}.json and checksums.sha256

# Summarize
summary = summarize_evaluation_dossier(dossier)
# {
#   "readiness_state": "needs_more_evidence",
#   "gate_summary": {"pass": 5, "fail": 3, "block": 0, "not_evaluated": 3, "total": 11},
#   "stub_execution_summary": {"stub_pass": 6, "total": 6},
#   "promotion_blocked": True,
#   ...
# }

# Assert promotion is blocked
assert_dossier_cannot_promote(dossier)  # always passes for valid dossiers
```

---

## Relationship to TR-06A through TR-06D and Future TR-07

| Layer | What it does | Inference |
|---|---|---|
| TR-06A | Metadata gate stubs — provenance and governance flags | No |
| TR-06B | Fixture corpus for TR-06A gate regression | No |
| TR-06C | Live eval case and plan interface, executor disabled | No |
| TR-06D | Stub adapter execution plumbing, typed result layer | No (stub only) |
| **TR-06E** | **Aggregates all evidence → sealed dossier + readiness state** | **No** |
| TR-06Z (future) | Audit seal — operator signs off on dossier | No |
| TR-07 (future) | Shadow/canary evaluation | Operator-approved, separate phase |

TR-06E is the aggregation and readiness checkpoint that sits between the evaluation layers (TR-06A–D) and the governance gate (TR-06Z). Nothing in TR-06E changes model registry state, triggers inference, or opens a promotion pathway.

---

## Validation Commands

```bash
python3 -m py_compile training/evaluation_dossier.py

python3 -m pytest -q training/tests/test_evaluation_dossier.py

python3 -m pytest -q training/tests/test_local_eval_adapter_harness.py

python3 -m pytest -q training/tests/test_live_eval_interface.py

python3 -m pytest -q training/tests/test_evaluation_fixtures.py

python3 -m pytest -q training/tests/test_evaluation_harness.py

python3 -m pytest -q training/tests/

python3 -m pytest -q
```

---

## Governance Attestation

No real training occurred in TR-06E. No model weights were loaded or created. No real model inference occurred. No provider calls were made. No LoRA or QLoRA adapters were created. No adapter checkpoint files were created. No Store 1 writes occurred. No model was promoted. No runtime deployment occurred.

All evaluation dossiers produced by TR-06E carry `promotion_blocked=true`, `promotion_decision_emitted=false`, `operator_review_required=true`, and all nine forbidden-action flags set to `false`.

TR-07 shadow/canary evaluation was not started.
