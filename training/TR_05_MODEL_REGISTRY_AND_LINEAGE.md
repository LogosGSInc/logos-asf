# TR-05: Model Registry and Lineage

**Version**: 1.0.0  
**Status**: Implemented  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-27  
**Requires**: TR-04D (dep_keystone_ingress.py), TR-04B (dry_run_trainer.py), TR-03 (dataset_builder.py)  
**Not implemented here**: Real training, model weights, Store 1 writes, runtime deployment, model promotion, TR-06 evaluation gates

---

## TR-05 Is Metadata Only

`training/model_registry.py` is a **metadata-only** local model registry and
lineage DAG. It records what a governed training run would have produced, but
no model weights exist and no training occurs.

TR-05:
- Records dry-run model/adaptor candidates with full provenance.
- Chains each artifact back to DEP.KEYSTONE/GovSec ingress, source registry,
  clearance ledger, synthetic provenance, TR-03 dataset manifests, and TR-04B
  dry-run envelopes.
- Defaults all artifacts to `promotion_status=not_promoted`.
- Enforces `training_allowed=false`, `model_weights_present=false`, and
  `operator_promotion_required=true` at both code and assertion level.

TR-05 is **not**:
- Real training (no model weight file is created or read).
- Model selection for production.
- Model promotion.
- Adapter creation.
- Model registry upload to any cloud provider.
- Runtime deployment.

---

## No Model Weights Are Created

Every registry entry carries:

```json
{
  "training_allowed":           false,
  "model_weights_present":      false,
  "runtime_deployment_allowed": false,
  "store1_write_allowed":       false,
  "external_calls_allowed":     false,
  "operator_promotion_required": true
}
```

These are `const` values in `MODEL_REGISTRY.schema.json`. The code enforces
them with `assert` statements inside `register_dry_run_candidate`. No call
site can override them.

`register_dry_run_candidate` explicitly rejects `model_weights_path` and
`adapter_checkpoint_path` parameters — passing either causes an immediate
`ModelRegistryBlockedError`.

---

## Registry Entry Types

| `artifact_type` | Meaning |
|---|---|
| `dry_run_adapter_candidate` | Registered from a TR-04B dry-run envelope; metadata only |
| `base_model_reference` | A reference to an external base model (future use) |
| `future_adapter_placeholder` | Reservation for a future training run |
| `evaluation_baseline` | Reference artifact for TR-06 evaluation |
| `rejected_candidate` | A dry-run candidate rejected at a governance gate |

All entries in TR-05 have `artifact_type=dry_run_adapter_candidate` and
`artifact_status=dry_run_only`.

---

## Lineage DAG Fields

Each `MODEL_LINEAGE_RECORD.schema.json` record ties an artifact back through
the full pipeline:

| Field | Provenance chain |
|---|---|
| `dep_keystone_ingress_refs` | TR-04D ingress clearance record IDs (DKI-*) |
| `dep_keystone_evidence_sha256_refs` | References to DEP.KEYSTONE `evidence.sha256` files |
| `dep_keystone_verification_report_refs` | References to DEP.KEYSTONE `verification-report.json` files |
| `source_registry_refs` | Training Source Registry IDs (L<N>-NNN) |
| `clearance_ledger_refs` | Clearance Ledger entry IDs (LE-*) |
| `synthetic_manifest_refs` | synthetic_doctrine.py manifest files |
| `synthetic_review_bridge_refs` | Bridge manifest files |
| `dataset_manifest_refs` | TR-03 dataset manifest IDs |
| `dry_run_envelope_refs` | TR-04B dry-run envelope IDs (DR-*) |
| `training_job_contract_refs` | Signed training-job contracts (empty until a contract is signed) |
| `evaluation_refs` | TR-06 evaluation records (empty until TR-06 is implemented) |
| `promotion_decision_refs` | Operator promotion decisions |

`lineage_hash` is computed from `artifact_id`, `artifact_type`, and all `*_refs`
arrays. Changing any ref changes the hash. `previous_lineage_hash` enables
tamper detection across a chain of lineage records.

---

## Relationship to DEP.KEYSTONE/GovSec, TR-03, TR-04A, TR-04B, TR-04C

**TR-04D → TR-05**: When a DEP.KEYSTONE ingress record is supplied,
`assert_training_ingress_allowed(record, next_gate="tr05_model_registry")` is
called before registration. The ingress record must have
`dep_keystone_status=VERIFIED`, `dep_keystone_trust_score >= 70`,
`govsec_admissibility_status=approved`, `training_pipeline_allowed=true`, and
`"tr05_model_registry"` in `allowed_next_gates`.

**TR-03 → TR-05**: The dataset manifest is loaded and verified (
`training_allowed=false`, `operator_promotion_required=true`). The `dataset_id`
and `content_hash` are preserved in the lineage record.

**TR-04A → TR-05**: The source registry and clearance ledger are implicitly
verified through the dry-run envelope (`validation_summary.source_registry_cleared=true`,
`validation_summary.ledger_cleared=true`). `ledger_entry_id` is recovered from
`audit_record.json` if present in the same directory as the dry-run envelope.

**TR-04B → TR-05**: The dry-run envelope is the primary registration input.
All governance constants are verified from the envelope. `dry_run_id`,
`dataset_id`, `source_id`, and `requested_use` drive deterministic artifact IDs
and lineage record construction.

**TR-04C → TR-05**: Synthetic review bridge output (operator-approved candidates)
enters TR-03 as dataset material. When synthetic candidates are present in the
dataset, their `synthetic_manifest_refs` and `synthetic_review_bridge_refs` can
be added to the lineage record.

---

## Why promotion_status Defaults to not_promoted

TR-05 registers artifacts that have passed governance validation but have not
been promoted to a real training run. `not_promoted` is the safe default — it
requires an explicit, separate operator action (a signed
`TRAINING_JOB_CONTRACT`) to change.

No code in TR-05 transitions an artifact to any state other than `not_promoted`.
The states `promotion_pending_operator`, `eligible_for_future_evaluation`, and
`archived` are reserved for future operator decisions.

---

## Artifact and Lineage ID Derivation

**`model_artifact_id`** (`MA-<sha256[:16]>`):
```
SHA-256("dry_run:{dry_run_id}:dataset:{dataset_id}:source:{source_id}")[:16]
```
Stable for the same `dry_run_id`, `dataset_id`, and `source_id`. Two registry
runs on the same TR-04B output produce the same artifact ID.

**`lineage_record_id`** (`LR-<sha256[:16]>`):
```
SHA-256("{artifact_id}:{first_dep_keystone_ingress_ref}:{first_dry_run_ref}")[:16]
```

**`lineage_hash`** (full SHA-256):
SHA-256 of the key provenance arrays (`artifact_id`, `artifact_type`, and all
`*_refs` fields). Changing any provenance reference changes the hash.

---

## CLI Commands

```bash
# Create an empty registry
python3 training/model_registry.py init \
  --out /tmp/model_registry.json \
  --operator-id TEST_REGISTRY_OP_001

# Register a TR-04B dry-run candidate with DEP.KEYSTONE ingress
python3 training/model_registry.py register-dry-run \
  --registry /tmp/model_registry.json \
  --dry-run-envelope /tmp/tr04_dry_run/dry_run_envelope.json \
  --dataset-manifest /tmp/tr03_dataset/manifest.json \
  --dep-keystone-ingress /tmp/dep_keystone_ingress.json \
  --out /tmp/model_registry_updated.json \
  --operator-id TEST_REGISTRY_OP_001

# Print a summary
python3 training/model_registry.py summarize \
  --registry /tmp/model_registry_updated.json
```

---

## Validation Commands

```bash
python3 -m py_compile training/model_registry.py

python3 -m pytest -q training/tests/test_model_registry.py

python3 -m pytest -q training/tests/test_dep_keystone_training_ingress.py

python3 -m pytest -q training/tests/test_synthetic_review_bridge.py

python3 -m pytest -q training/tests/test_dry_run_trainer.py

python3 -m pytest -q training/tests/

python3 -m pytest -q
```

---

## No Real Training

TR-05 performs no real training. It does not:

- Train a model.
- Load model weights.
- Run model inference.
- Create LoRA or QLoRA adapters.
- Create adapter checkpoint files.
- Write to Store 1.
- Deploy to the runtime.
- Promote any model to a registry.
- Upload artifacts to any cloud provider.
- Call any external provider SDK.
- Make any network call.

TR-06 (Evaluation Gates) was not started in this task.

---

## No Store 1 Writes

No writes to Store 1 occurred in TR-05. The registry is a local JSON file only.
All provenance records are local metadata files. No training pipeline
infrastructure was triggered.

---

## No Runtime Deployment

No runtime deployment occurred. The model registry does not interface with any
serving infrastructure, inference server, or deployment pipeline.

---

## Governance Attestation

No real training occurred in TR-05. No model weights were created. No Store 1
writes occurred. No external calls were made. No adapter checkpoints were
created. No model was promoted. All registry entries carry
`training_allowed=false`, `model_weights_present=false`, and
`promotion_status=not_promoted`. Operator review and a signed training-job
contract are required before any real training may proceed. TR-06 evaluation
gates were not started.
