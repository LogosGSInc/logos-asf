# TR-04: Dry-Run Training Adapter

**Version**: 1.0.0  
**Status**: Implemented  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-26  
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
| Output dir security | `--out-dir` is inside repository root |
| Manifest exists | `manifest.json` not found in dataset dir |
| Manifest version | `schema_versions.manifest_schema` not in supported set (`1.0.0`) |
| Required artifacts | Any of the 7 required files is absent |
| Checksum integrity | Any file listed in `checksums.sha256` does not match its stored hash |
| `training_allowed` | `manifest.training_allowed` is not exactly `false` |
| `operator_promotion_required` | `manifest.operator_promotion_required` is not exactly `true` |
| `store1_write_allowed` | `manifest.store1_write_allowed` is not exactly `false` |
| `runtime_deployment_allowed` | `manifest.runtime_deployment_allowed` is not exactly `false` |
| `model_promotion_allowed` | `manifest.model_promotion_allowed` is `true` |
| `external_calls_allowed` | `manifest.external_calls_allowed` is `true` |
| Scan report: no critical | `scan_report.has_critical` is `true` |
| Scan report: no protected eval | `"protected_evaluation_overlap"` in `scan_report.categories_found` |
| Dataset status | `manifest.dataset_status` is `contamination_blocked` or `dataset_validation_failed` |
| Split count match | Actual line count in any JSONL split differs from manifest declared count |
| Operator identity | Production mode + simulated operator ID (TEST_, SIM_, DRY_ prefixes or _SIM_, _DRY_, _TEST_ substrings) |

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

## Exact Commands

```bash
# Simulation mode (accepts TEST_ operators)
python3 training/dry_run_trainer.py \
  --dataset-dir /tmp/tr03_output \
  --out-dir     /tmp/tr04_dry_run \
  --mode        simulation \
  --operator-id TEST_OP_20260626

# Production mode (requires non-simulated operator ID)
python3 training/dry_run_trainer.py \
  --dataset-dir /tmp/tr03_output \
  --out-dir     /tmp/tr04_dry_run_prod \
  --mode        production \
  --operator-id PROD_GOVERNANCE_LEAD_001

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

**LoRA / QLoRA adapters**: Future work. TR-04 produces no adapters and contains
no training framework code. The training-job preview describes these methods
as placeholders (`future: local_lora or local_qlora`).

**Real training infrastructure**: Not implemented at any phase. A separately
signed `TRAINING_JOB_CONTRACT` (see `training/TRAINING_JOB_CONTRACT.schema.json`)
is required, and operator approval is final.

---

## Governance Attestation

> This dry-run produced no model weights, no store1 writes, no runtime
> deployment, no model promotion, and no external calls. Operator promotion
> is required before any real training may proceed.

This attestation is reproduced verbatim in every `audit_record.json` produced
by TR-04.
