# TR-04: Dry-Run Training Adapter

**Version**: 1.1.0  
**Status**: Implemented (TR-04B gate hardening applied)  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-27  
**Prior Phase**: TR-03 — Immutable Dataset Builder and Contamination Gate  
**Next Phase**: TR-05 — Model Registry and Lineage (not started)

---

## What TR-04 Does

TR-04 validates an approved TR-03 dataset artifact directory and produces a
**governed training-job envelope** that describes what a future training job
would look like — without performing one.

**TR-04 performs no real training.** It does not:

- Create or modify model weights
- Create LoRA or QLoRA adapters
- Submit a training job to any infrastructure
- Upload a dataset to any external system
- Write to Store 1
- Deploy to the runtime
- Promote any model to the registry
- Make any network call
- Call any external provider SDK (OpenAI, Anthropic, Groq, HuggingFace, etc.)

All of these actions are explicitly listed in every envelope under
`blocked_real_actions` and are enforced through governance flag assertions
at both construction time (assertions in code) and schema level
(const: false / const: true in `TRAINING_DRY_RUN_ENVELOPE.schema.json`).

---

## Required Inputs from TR-03

TR-04 accepts one input: a directory produced by `training/dataset_builder.py`
(TR-03). This directory must contain:

| File | Required | Purpose |
|------|----------|---------|
| `manifest.json` | Yes | Dataset manifest with governance flags |
| `checksums.sha256` | Yes | SHA-256 checksums for all data files |
| `train.jsonl` | Yes | Training split |
| `validation.jsonl` | Yes | Validation split |
| `test.jsonl` | Yes | Test split |
| `provenance.jsonl` | Yes | Per-record provenance chain |
| `rejected.jsonl` | Yes | Records rejected during TR-03 eligibility or scanner passes |
| `scan_report.json` | Yes | TR-03 contamination scanner report |

---

## Validation Gates (in order)

TR-04 applies the following validation gates in sequence. Any failure causes
a nonzero exit and no output artifacts are written.

| Gate | Block condition |
|------|----------------|
| 0. Output dir security | `--out-dir` is inside repository root |
| 1. Manifest exists | `manifest.json` not found in dataset dir |
| 2. Manifest version | `schema_versions.manifest_schema` not in supported set (`1.0.0`) |
| 3. Required artifacts | Any of the 7 required files is absent |
| 4. Checksum integrity | Any file listed in `checksums.sha256` does not match its stored hash |
| 5. `training_allowed` | `manifest.training_allowed` is not exactly `false` |
| 5. `operator_promotion_required` | `manifest.operator_promotion_required` is not exactly `true` |
| 5. `store1_write_allowed` | `manifest.store1_write_allowed` is not exactly `false` |
| 5. `runtime_deployment_allowed` | `manifest.runtime_deployment_allowed` is not exactly `false` |
| 5. `model_promotion_allowed` | `manifest.model_promotion_allowed` is `true` |
| 5. `external_calls_allowed` | `manifest.external_calls_allowed` is `true` |
| 6. Scan report: no critical | `scan_report.has_critical` is `true` |
| 6. Scan report: no protected eval | `"protected_evaluation_overlap"` in `scan_report.categories_found` |
| 7. Dataset status | `manifest.dataset_status` is `contamination_blocked` or `dataset_validation_failed` |
| 8. Split count match | Actual line count in any JSONL split differs from manifest declared count |
| 9. Operator identity | Production mode + simulated operator ID (TEST_, SIM_, DRY_ prefixes or _SIM_, _DRY_, _TEST_ substrings) |
| **10. Source registry** | `--source-id` not provided (without test bypass), or source not `approved` in `source_registry_seed.json`, or `requested_use` not in `allowed_uses` |
| **10. Clearance ledger** | `--clearance-ledger` not provided (without test bypass), ledger hash chain invalid, or no valid approval entry for source_id |

---

## Dry-Run Envelope Fields

The primary output artifact is `dry_run_envelope.json`. All governance flags
are hardcoded deny-by-default and cannot be overridden by any argument.

| Field | Value | Meaning |
|-------|-------|---------|
| `training_allowed` | `false` | This envelope does not authorize training |
| `dry_run_only` | `true` | No real training adapter was invoked |
| `operator_promotion_required` | `true` | Operator must separately sign a training-job contract |
| `store1_write_allowed` | `false` | No Store 1 writes |
| `runtime_deployment_allowed` | `false` | No runtime deployment |
| `model_promotion_allowed` | `false` | No model registry promotion |
| `external_calls_allowed` | `false` | No external API or SDK calls |
| `dry_run_id` | `DR-<16 hex>` | Stable ID derived from manifest content hash + config digest |
| `job_intent` | object | Mode, operator ID, and description |
| `dataset_summary` | object | Record counts and scan status from manifest (no raw examples) |
| `validation_summary` | object | Which gates passed |
| `estimated_compute` | object | Approximate character/token volume (deterministic) |
| `blocked_real_actions` | list | Enumeration of all explicitly blocked actions |
| `next_required_gate` | string | Human-readable description of what must happen before real training |

Schema: `training/TRAINING_DRY_RUN_ENVELOPE.schema.json`

---

## Blocked Actions

Every dry-run envelope contains an explicit `blocked_real_actions` list:

- `real_model_training`
- `model_weight_update`
- `lora_adapter_creation`
- `qlora_adapter_creation`
- `dataset_upload`
- `store1_write`
- `runtime_deployment`
- `model_registry_promotion`
- `external_api_calls`
- `provider_sdk_calls`
- `network_egress`

---

## Simulation vs Production Mode

| Aspect | `simulation` | `production` |
|--------|-------------|--------------|
| Accepts `TEST_` operator IDs | Yes | No |
| Accepts `SIM_` operator IDs | Yes | No |
| Accepts `DRY_` operator IDs | Yes | No |
| Performs real training | No | No |
| Writes to Store 1 | No | No |
| Deploys to runtime | No | No |
| Promotes a model | No | No |

In both modes, `training_allowed` remains `false` and no real training occurs.
The distinction only affects operator identity validation.

---

## Output Artifacts

All artifacts are written to `--out-dir` (which must be outside the repository).

| File | Description |
|------|-------------|
| `dry_run_envelope.json` | Governed envelope with all flags and dataset summary |
| `training_job_preview.json` | Preview of what a future job contract would look like |
| `validation_report.json` | Gate-by-gate pass/fail report |
| `audit_record.json` | Audit log entry (no raw examples) |
| `checksums.sha256` | SHA-256 checksums of the four output files |

The `audit_record.json` explicitly excludes raw training examples
(`raw_examples_excluded: true`). The audit record is safe to store in
governance logs without re-exposing training material.

---

## Dry-Run ID Stability

The `dry_run_id` is derived deterministically:

```
content_hash  = manifest["content_hash"]   # from TR-03 manifest
config_digest = sha256(json({"adapter": VERSION, "mode": mode, "operator_id": op_id}))[:16]
dry_run_id    = "DR-" + sha256(f"{content_hash}:{config_digest}")[:16]
```

The same manifest + same mode + same operator ID produces the same `dry_run_id`
across runs. Changing any of these inputs changes the ID.

---

## TR-04B Gate: Registry + Ledger Required

As of TR-04B hardening, the dry-run trainer requires both gates to be satisfied
for normal operation:

**Gate 1 — Source Registry (TR-04A.3):** `--source-id` must be an `approved`
entry in `source_registry_seed.json` and `--requested-use` must be in its
`allowed_uses` list.

**Gate 2 — Clearance Ledger (TR-04A.4):** `--clearance-ledger` must point to a
valid clearance ledger file. The ledger must have a valid SHA-256 hash chain and
contain at least one approval-type decision (`hp_approve`, `reg01_clear`,
`lgl01_clear`, `ea00_batch`) for the source_id that has not been superseded by
a subsequent block/reject/archive decision.

If either gate fails, the dry-run exits with a nonzero status and no output
artifacts are written.

**Test-only bypass:** `--allow-unregistered-source-for-tests` skips both gates.
This flag must not appear in production invocations. When bypass is used,
`source_registry_cleared` and `ledger_cleared` are `false` in all outputs.

Both cleared flags appear in all four output artifacts:
- `dry_run_envelope.json` → `validation_summary.ledger_cleared`, `job_intent.ledger_cleared`
- `training_job_preview.json` → `ledger_cleared`
- `validation_report.json` → `gates.ledger_cleared`
- `audit_record.json` → `ledger_cleared`, `ledger_entry_id`

---

## Exact Commands

```bash
# Full two-gate dry-run (registry + ledger)
python3 training/dry_run_trainer.py \
  --dataset-dir    /tmp/tr03_output \
  --out-dir        /tmp/tr04_dry_run \
  --mode           simulation \
  --operator-id    TEST_OP_001 \
  --source-id      L1-001 \
  --requested-use  sft_candidate \
  --clearance-ledger /path/to/clearance_ledger.json

# Production mode (requires non-simulated operator ID + both gates)
python3 training/dry_run_trainer.py \
  --dataset-dir    /tmp/tr03_output \
  --out-dir        /tmp/tr04_dry_run_prod \
  --mode           production \
  --operator-id    PROD_GOVERNANCE_LEAD_001 \
  --source-id      L1-001 \
  --requested-use  sft_candidate \
  --clearance-ledger /path/to/clearance_ledger.json

# Run TR-04 tests only
python3 -m pytest -q training/tests/test_dry_run_trainer.py

# Run full training test suite
python3 -m pytest -q training/tests/

# Run full project test suite
python3 -m pytest -q
```

---

## What Is Not Implemented

**TR-05 — Model Registry and Lineage**: Not started. The `next_required_gate`
field in every envelope explicitly states that TR-05 is required before any
real training-job submission.

**synthetic_doctrine.py (TR-04A.5)**: Not started. Synthetic data generation
from owned doctrine is a separate phase after the clearance ledger is proven.

**LoRA / QLoRA adapters**: Future work. TR-04 produces no adapters and contains
no training framework code. The training-job preview describes these methods
as placeholders (`future: local_lora or local_qlora`).

**Real training infrastructure**: Not implemented at any phase. A separately
signed `TRAINING_JOB_CONTRACT` is required, and operator approval is final.

**Real Ed25519 signing on ledger entries**: TR-04A.5. All current ledger entries
carry `signature_status: unsigned_local` and `signature_algorithm: ed25519_placeholder`.

**No real training occurred in TR-04B.** The dry-run adapter continues to
produce no model weights, no training artifacts, and no external calls.

---

## Governance Attestation

> This dry-run produced no model weights, no store1 writes, no runtime
> deployment, no model promotion, and no external calls. Operator promotion
> is required before any real training may proceed.

This attestation is reproduced verbatim in every `audit_record.json` produced
by TR-04.
