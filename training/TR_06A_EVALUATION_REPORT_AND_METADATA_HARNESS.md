# TR-06A: Evaluation Report Schema and Metadata-Only Harness

**Version**: 1.0.0  
**Status**: Implemented  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-27  
**Requires**: TR-05 (model_registry.py), TR-04D (dep_keystone_ingress.py), TR-04B (dry_run_trainer.py)  
**Not implemented here**: Live behavioral evaluation (TR-06B), shadow/canary (TR-07), model promotion, model weights, real training

---

## What TR-06A Creates

1. **`training/EVALUATION_REPORT.schema.json`** — constitutional contract for one evaluation run against one registered candidate.
2. **`training/evaluation_harness.py`** — metadata-only evaluation harness with 11 gate stubs.
3. **`training/tests/test_evaluation_harness.py`** — 131-test suite covering all gates, rejection guards, and report invariants.

TR-06A is the first evaluation layer. It gives TR-06B (future fixture-based eval) and TR-06C (future live behavioral eval) a typed, enforceable target.

---

## Architecture Position

```
TR-05 Model Registry + Lineage
  ↓  (registered dry_run_adapter_candidate, promotion_status=not_promoted)
TR-06A Evaluation Report + Metadata Harness   ← this file
  ↓  (EVALUATION_REPORT per gate, promotion_blocked=True)
  [operator review]
  ↓
TR-06B Live Behavioral Eval Fixtures          ← NOT started
  ↓
TR-07 Shadow/Canary                           ← NOT started
```

---

## What TR-06A Does Not Do

- Does not run model inference.
- Does not load model weights.
- Does not train a model.
- Does not create LoRA, QLoRA, or any adapter checkpoint.
- Does not promote any candidate.
- Does not write to Store 1 or any model registry at a provider.
- Does not make network calls.
- Does not call any external provider SDK (OpenAI, Anthropic, Gemini, Groq, HuggingFace, etc.).
- Does not start TR-06B live behavioral evaluation.
- Does not start TR-07 shadow/canary.

---

## Promotion Is Constitutionally Blocked

Every evaluation report produced by TR-06A has:

```json
{
  "promotion_blocked":        true,
  "promotion_decision_emitted": false,
  "metadata_only":            true,
  "operator_review_required": true
}
```

These are `const` values in `EVALUATION_REPORT.schema.json`. `build_evaluation_report`
hardcodes them regardless of gate result. No evaluation outcome in TR-06A can unblock a
candidate or emit a promotion decision.

`validate_evaluation_report` raises `EvaluationReportError` if any of these invariants
are violated in a report.

---

## Evaluation Report Contract

`EVALUATION_REPORT.schema.json` (draft 2020-12) defines 15 required fields:

| Field | Notes |
|---|---|
| `evaluation_report_id` | `ER-<sha256[:16]>`, deterministic for same candidate/gate/evidence |
| `schema_version` | `"1.0.0"` |
| `created_at` | ISO 8601 UTC |
| `candidate_artifact_id` | `MA-*` from TR-05 registry |
| `candidate_lineage_record_id` | `LR-*` from TR-05 lineage |
| `evaluation_gate` | Enum of 11 defined gates |
| `result` | `pass` / `fail` / `block` / `not_evaluated` |
| `requires_live_inference` | `false` for all TR-06A stubs |
| `metadata_only` | const `true` |
| `evidence` | Gate-specific key/value dict |
| `promotion_blocked` | const `true` |
| `promotion_decision_emitted` | const `false` |
| `operator_review_required` | const `true` |
| `evaluated_by` | Harness or operator ID |
| `notes` | Free-text gate explanation |

---

## The 11 Evaluation Gates

### `constitutional_fidelity`

Metadata-only check that the candidate's lineage includes DEP.KEYSTONE ingress refs,
source registry refs, clearance ledger refs, and deny-by-default governance flags.
Does **not** claim live constitutional behavior has been tested.

### `haap_refusal_behavior`

Metadata-only provenance check: verifies that HAAP/GovSec/Layer Zero provenance exists
in lineage and provenance records (dep_keystone_ingress_refs non-empty, govsec_layer
present). Does **not** claim live refusal testing — live refusal behavior requires
TR-06B behavioral evaluation.

### `routing_correctness`

Metadata-only check: verifies artifact_type, source_id, requested_use, dry-run refs,
and dataset refs are internally consistent. Does **not** test live routing behavior.

### `audit_safe_json_ir_output`

Metadata-only check: verifies lineage_record_id, checksum_manifest, and lineage_hash
are present; notes field within safe size. Does **not** inspect model output.

### `store1_govmem_boundary_preservation`

Metadata-only check: store1_write_allowed=false and external_calls_allowed=false in
both the candidate record and lineage governance_flags. Any violation → `block`.

### `dep_keystone_govsec_provenance_completeness`

Metadata-only check: dep_keystone_ingress_ref, dep_keystone_evidence_sha256_ref, and
dep_keystone_verification_report_ref present on candidate; corresponding lists
non-empty in lineage. Missing refs → `fail`.

Boundary: this gate checks that DEP.KEYSTONE evidence refs are present. It does not
re-run DEP.KEYSTONE verification (DEP.KEYSTONE is a standalone product;
`LogosGSInc/dep.keystone` runs independently).

### `source_registry_clearance_completeness`

Metadata-only check: source_registry_refs in lineage are non-empty and provenance.source_id
is present. Missing refs → `fail`.

### `clearance_ledger_completeness`

Metadata-only check: clearance_ledger_refs in lineage are non-empty and
provenance.ledger_entry_id is present. Missing refs → `fail`.

### `dry_run_integrity`

Metadata-only check: dry_run_envelope_refs in lineage are non-empty; all deny-by-default
governance flags (training_allowed, model_weights_present, runtime_deployment_allowed,
store1_write_allowed, external_calls_allowed) are false in both candidate and lineage.
Governance flag violations → `block`. Missing dry-run refs → `fail`.

### `synthetic_provenance_integrity`

Metadata-only check: if synthetic_manifest_refs or synthetic_review_bridge_refs are
non-empty in lineage, verifies they contain non-empty string entries.

If the candidate has no synthetic lineage at all → `not_evaluated` (this is correct
and expected for non-synthetic candidates).

Full synthetic provenance validation (synthetic_origin, prompt_hash,
generation_agent_id) requires TR-06B fixture evaluation.

### `promotion_blocking_invariants`

Hard check: promotion_status=not_promoted, training_allowed=false,
model_weights_present=false, runtime_deployment_allowed=false, store1_write_allowed=false,
external_calls_allowed=false, operator_promotion_required=true. Any violation → `block`.
Also fails if model_weights_path or adapter_checkpoint_path are present.

---

## Metadata-Only vs. Future Live Behavioral Evaluation

| Check | TR-06A | TR-06B (future) |
|---|---|---|
| Governance flags in metadata | ✓ metadata | — |
| Provenance refs completeness | ✓ metadata | — |
| DEP.KEYSTONE refs present | ✓ metadata | — |
| Promotion-blocking invariants | ✓ metadata | — |
| Dry-run governance anchors | ✓ metadata | — |
| Constitutional fidelity behavior | ✗ not tested | ✓ behavioral fixture |
| HAAP refusal on live prompts | ✗ not tested | ✓ behavioral fixture |
| Routing accuracy on live inputs | ✗ not tested | ✓ behavioral fixture |
| Audit-safe JSON IR from live runs | ✗ not tested | ✓ behavioral fixture |

TR-06A is honest: gate stubs set `requires_live_inference=false` and the `notes`
field explicitly states what is not claimed. A gate that cannot be meaningfully
evaluated from metadata returns `result=not_evaluated` rather than a false `pass`.

---

## Public API

```python
from training.evaluation_harness import (
    load_registry_candidate,
    load_lineage_record_from_candidate,
    run_evaluation_gate,
    run_all_metadata_gates,
    build_evaluation_report,
    save_evaluation_report,
    validate_evaluation_report,
    summarize_evaluation_reports,
    EvaluationCandidateError,
    EvaluationGateError,
    EvaluationReportError,
    EVALUATION_GATES,
    VALID_RESULTS,
)

# Load and safety-check a registry candidate
candidate = load_registry_candidate("/path/to/model_registry.json", "MA-abc123")

# Run a single gate
gate_result = run_evaluation_gate(candidate, "dep_keystone_govsec_provenance_completeness")

# Build and validate a typed report
report = build_evaluation_report(candidate, gate_result, evaluated_by="TEST_EVAL_OP_001")
validate_evaluation_report(report)  # raises EvaluationReportError if invariants violated

# Save and summarize
save_evaluation_report(report, "/tmp/eval_out")

# Run all 11 gates at once
gate_results = run_all_metadata_gates(candidate)
reports = [build_evaluation_report(candidate, gr) for gr in gate_results]
summary = summarize_evaluation_reports(reports)
# summary["promotion_blocked"] is always True
```

---

## CLI Commands

```bash
# Run a single gate
python3 training/evaluation_harness.py run-gate \
  --registry /tmp/model_registry.json \
  --candidate-artifact-id MA-abc123 \
  --gate dep_keystone_govsec_provenance_completeness \
  --out-dir /tmp/tr06a_eval \
  --evaluated-by TEST_EVAL_OP_001

# Run all 11 metadata gates
python3 training/evaluation_harness.py run-all \
  --registry /tmp/model_registry.json \
  --candidate-artifact-id MA-abc123 \
  --out-dir /tmp/tr06a_eval_all \
  --evaluated-by TEST_EVAL_OP_001

# Summarize a directory of saved reports
python3 training/evaluation_harness.py summarize \
  --reports-dir /tmp/tr06a_eval_all
```

---

## Relationship to Earlier Pipeline Stages

**DEP.KEYSTONE / TR-04D**: TR-06A checks that dep_keystone_ingress_refs,
dep_keystone_evidence_sha256_refs, and dep_keystone_verification_report_refs are present
in the registered candidate. DEP.KEYSTONE is a standalone LOGOS product
(`LogosGSInc/dep.keystone`). TR-06A does not re-run DEP.KEYSTONE verification.
The `dep_keystone_govsec_provenance_completeness` gate verifies the evidence refs exist;
it does not become DEP.KEYSTONE.

**GovSec V2 / Layer Zero**: The `constitutional_fidelity` and `haap_refusal_behavior`
gates verify GovSec/Layer Zero provenance chain exists in lineage metadata. They do not
re-adjudicate admissibility — that happened at TR-04D ingress.

**TR-03 (Dataset Builder)**: The `routing_correctness` and `dry_run_integrity` gates
verify dataset_manifest_refs are present in lineage, confirming the artifact traces
back through the immutable dataset builder.

**TR-04A (Source Registry, Clearance Ledger)**: `source_registry_clearance_completeness`
and `clearance_ledger_completeness` verify source_registry_refs and clearance_ledger_refs
are non-empty in lineage. These refs were populated by model_registry.py at TR-05
registration time.

**TR-04B (Dry-Run Trainer)**: `dry_run_integrity` verifies dry_run_envelope_refs and
all deny-by-default governance flags from the dry-run envelope.

**TR-04C (Synthetic Review Bridge)**: `synthetic_provenance_integrity` verifies
synthetic ref entries when synthetic lineage is present.

**TR-05 (Model Registry)**: TR-06A loads candidates from the TR-05 registry JSON.
It does not modify registry entries or promotion_status.

---

## Validation Commands

```bash
python3 -m py_compile training/evaluation_harness.py

python3 -m pytest -q training/tests/test_evaluation_harness.py

python3 -m pytest -q training/tests/test_model_registry.py

python3 -m pytest -q training/tests/test_dep_keystone_training_ingress.py

python3 -m pytest -q training/tests/test_dry_run_trainer.py

python3 -m pytest -q training/tests/

python3 -m pytest -q
```

---

## Governance Attestation

No real training occurred in TR-06A. No model weights were loaded or created. No
LoRA or QLoRA adapters were created. No adapter checkpoint files were created. No
Store 1 writes occurred. No external calls were made. No model was promoted. No
runtime deployment occurred.

All evaluation reports produced by TR-06A carry `promotion_blocked=true`,
`promotion_decision_emitted=false`, `metadata_only=true`, and
`operator_review_required=true`.

TR-06B live behavioral evaluations were not started.  
TR-07 shadow/canary evaluation was not started.
