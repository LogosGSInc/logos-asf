# TR-04D: DEP.KEYSTONE / GovSec V2 Training Ingress Alignment

**Version**: 1.0.0  
**Status**: Implemented  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-27  
**Produces**: `dep_keystone_ingress.py` — callable training-ingress gate  
**Feeds into**: TR-04A (Source Registry), TR-03 (Dataset Builder), TR-04B (Dry Run), TR-05 (Model Registry)  
**Not implemented here**: Real training, model weights, Store 1 writes, TR-05

---

## Recon Result

A grep of `training/`, `abigail/`, `governance-spine/`, `agents/`, and `docs/`
for `DEP`, `KEYSTONE`, `Keystone`, `GovSec`, `Layer Zero`, `Perceptual`,
`admissibility`, `ingress`, `trust certificate`, `sbom`, and related field names
(`dep_keystone_ingress_id`, `keystone_evidence_ref`, `admissibility_status`,
`assert_training_source_admissible`) returned no matches for a callable
training-ingress gate.

Partial matches (`DEPT-*` in `abigail/abigail_hardened_enhanced.py`,
`GOVMEM_DEPARTMENT_ID` in `governance-spine/src/pipeline.rs`) were department
identifiers — not ingress control systems.

**Result: No pre-existing DEP.KEYSTONE / GovSec training-ingress gate existed.
`dep_keystone_ingress.py` was created as the new narrow TR-04D bridge.**

---

## What TR-04D Does

`training/dep_keystone_ingress.py` implements the DEP.KEYSTONE / GovSec V2 /
Layer Zero admissibility gate for training-source ingress. It is the first
explicit enforcement point between "a source exists" and "a source may enter
the training pipeline."

The gate:
1. Loads and validates DEP.KEYSTONE ingress records (JSON).
2. Verifies `admissibility_status=approved` and `admissibility_decision=accepted_for_clearance`.
3. Verifies evidence integrity (non-empty `evidence_sha256`, `artifact_sha256`, `keystone_evidence_ref`, `keystone_verification_report_ref`).
4. Verifies `training_pipeline_allowed=true`.
5. Optionally verifies source identity (`source_id`) and allowed next gate (`allowed_next_gates`).
6. Returns a typed clearance result or raises a structured exception.

---

## Why This Gate Exists

GovSec V2 / Layer Zero doctrine treats training corpora, fine-tuning corpora,
synthetic data, ingestion controls, embeddings, retrieved documents, memory
layers, and tool-returned context as **reality-formation inputs** — artifacts
that shape Abigail cognition. DEP.KEYSTONE is the supply-chain trust gate that
establishes artifact provenance and integrity before any of these inputs shape
the model.

Before TR-04D, the LOGOS ASF training pipeline enforced supply-chain trust
implicitly via the source registry (`registry_status=approved`,
`hp_decision_status=approved`) and the clearance ledger. TR-04D makes the
DEP.KEYSTONE layer explicit: a typed, callable gate with structured evidence
fields, audit-safe summaries, and machine-enforceable admissibility states.

---

## Layer Zero / DEP.KEYSTONE → Training Readiness Ingress

The ingress record schema (`DEP_KEYSTONE_TRAINING_INGRESS.schema.json`) maps
three GovSec V2 layers onto training contexts:

| `govsec_layer` | Meaning in training |
|---|---|
| `layer_zero_reality_formation` | This artifact shapes Abigail cognition directly (all Lane 1 doctrine, synthetic data, SFT corpora) |
| `dep_keystone_supply_chain` | Artifact provenance was verified through DEP.KEYSTONE supply-chain checks |
| `training_readiness_ingress` | Artifact has passed training-specific admissibility review |

All training data must be `reality_formation_input: true`. Lane 1 owned-doctrine
sources are the highest-confidence category.

---

## All Future Training Data Should Enter Through DEP.KEYSTONE

Every artifact that will enter the training pipeline — whether a source
registry entry, a synthetic batch, a review candidate, or a dataset manifest
— should carry a `dep_keystone_ingress_id` linking it to a cleared ingress
record. The ingress record provides:

- SHA-256 hashes of the evidence package and the artifact itself
- References to the verification report and SBOM
- `allowed_next_gates` limiting which pipeline gates the artifact may enter
- A typed `admissibility_status` the pipeline can assert at each gate

This makes pipeline admission decisions auditable and replayable. If an ingress
record is later blocked or archived, every downstream artifact referencing its
`dep_keystone_ingress_id` is immediately traceable.

**Current enforcement posture**: TR-04D introduces the gate and proves it works.
The `dep_keystone_ingress_id` field is optional in `SOURCE_REGISTRY.schema.json`
(not required). Existing source registry entries are not broken. Hard mandatory
enforcement at the source registry and clearance ledger level can be applied in
a future migration.

---

## Relationship to Source Registry, Clearance Ledger, and Downstream Gates

```
DEP.KEYSTONE/GovSec ingress clearance (TR-04D)
  ↓ keystone_ingress_id → source_registry.json (optional field, TR-04A.1/4A.3)
  ↓ clearance verified  → clearance_ledger.json (TR-04A.4)
  ↓ synthetic_seed use  → synthetic_doctrine.py (TR-04A.5)
  ↓ records bridged     → synthetic_review_bridge.py (TR-04C)
  ↓ operator approved   → dataset_builder.py (TR-03)
  ↓ dry-run validated   → dry_run_trainer.py (TR-04B)
  ↓ registered          → model_registry.py (TR-05)
```

**TR-04A (Source Registry + Clearance Ledger)**: The ingress gate runs before
or alongside source registry admission. The `dep_keystone_ingress_id` field
links a source registry entry to its DEP.KEYSTONE clearance record.

**TR-04A.5 (Synthetic Doctrine)**: Synthetic generation sources (L1-001, L1-003,
L1-005, L1-006) should carry `dep_keystone_ingress_id` references before being
used as generation seeds. The registry+ledger gate in `synthetic_doctrine.py`
is the current enforcement point; DEP.KEYSTONE ingress adds a supply-chain
layer on top.

**TR-04C (Synthetic Review Bridge)**: The bridge's output candidates can carry
a `dep_keystone_ingress_id` inherited from the source, linking the candidate
back through the entire ingress chain.

**TR-03 (Dataset Builder)**: Dataset manifests should reference DEP.KEYSTONE
ingress IDs for all contributing sources. The dataset builder can call
`assert_training_ingress_allowed(record, next_gate="tr03_dataset_builder")` to
verify that the cleared ingress record explicitly permits TR-03 entry.

**TR-04B (Dry-Run Trainer)**: Dry-run envelopes reference dataset manifests
that in turn reference ingress records. `assert_training_ingress_allowed(record, next_gate="tr04b_dry_run")` verifies the gate.

**TR-05 (Model Registry)**: Registry entries will reference DEP.KEYSTONE ingress
IDs in their lineage records. `assert_training_ingress_allowed(record, next_gate="tr05_model_registry")` verifies clearance before registration.

---

## Public API

```python
from training.dep_keystone_ingress import (
    load_ingress_record,           # Path → dict
    validate_ingress_record,       # dict → {"valid": True, ...}
    assert_training_ingress_allowed,  # dict, source_id=None, next_gate=None → clearance_dict
    summarize_ingress,             # dict → audit-safe summary dict
    KeystoneIngressBlockedError,   # terminal state (blocked/rejected/archived)
    KeystoneIngressNotAllowedError, # not cleared (pending/draft/missing evidence)
    KeystoneIngressValidationError, # structurally invalid record
)
```

`assert_training_ingress_allowed` fails closed. It raises:
- `KeystoneIngressBlockedError` for `blocked`, `rejected`, or `archived` records.
- `KeystoneIngressNotAllowedError` for `draft`, `pending`, wrong `source_id`, wrong `next_gate`, or missing evidence.
- Returns a `{"cleared": True, ...}` dict only if all checks pass.

---

## Ingress Record Required Fields

| Field | Type | Requirement |
|-------|------|------------|
| `dep_keystone_ingress_id` | string | Unique identifier (DKI-*) |
| `schema_version` | string | Must be `"1.0.0"` |
| `created_at` | string | ISO 8601 UTC |
| `source_id` | string | Matches source registry entry |
| `source_name` | string | Human-readable name |
| `source_type` | string | e.g., `logos_owned_doctrine` |
| `classification` | string | Handling classification |
| `admissibility_status` | enum | `approved` for pipeline entry |
| `admissibility_decision` | enum | `accepted_for_clearance` for pipeline entry |
| `keystone_evidence_ref` | string | Must be non-empty for approved records |
| `keystone_verification_report_ref` | string | Must be non-empty for approved records |
| `keystone_sbom_ref` | string | SBOM reference |
| `evidence_sha256` | string | Must be non-empty for approved records |
| `artifact_sha256` | string | Must be non-empty for approved records |
| `govsec_layer` | enum | `layer_zero_reality_formation` for training data |
| `reality_formation_input` | boolean | `true` for all training data |
| `ingress_actor_id` | string | Reviewer identifier |
| `ingress_actor_role` | string | Reviewer role |
| `operator_review_required` | boolean | `true` for training data |
| `training_pipeline_allowed` | boolean | `true` for pipeline entry |
| `allowed_next_gates` | array | Which pipeline gates are permitted |
| `notes` | string | Governance notes |

---

## Source Registry Change

`SOURCE_REGISTRY.schema.json` now includes `dep_keystone_ingress_id` as an
optional property in the `SourceEntry` definition. It accepts `string | null`.
Existing entries that do not carry this field continue to validate. Future
entries should populate it after DEP.KEYSTONE clearance.

---

## No Real Training

TR-04D performs no real training. It does not:

- Create or modify model weights
- Write to Store 1
- Deploy to the runtime
- Promote any model to the registry
- Call any external provider SDK or API
- Make any network call

TR-05 (Model Registry and Lineage) was not started in this task.

---

## Governance Attestation

No real training occurred in TR-04D. The gate validates DEP.KEYSTONE ingress
records only — it does not train, load, create, or modify model weights. No
Store 1 writes occurred. No external calls were made. TR-05 was not started.
