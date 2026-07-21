# TR-06B: Metadata Evaluation Fixtures

**Version**: 1.0.0  
**Status**: Implemented  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-27  
**Requires**: TR-06A (evaluation_harness.py), TR-05 (model_registry.py)  
**Not implemented here**: Live model inference, behavioral eval (TR-06C), shadow/canary (TR-07), model promotion, model weights, real training

---

## What TR-06B Creates

1. **`training/EVALUATION_FIXTURE_CASE.schema.json`** — constitutional contract for one fixture case.
2. **`training/evaluation_fixture_builder.py`** — deterministic in-memory fixture corpus.
3. **`training/tests/test_evaluation_fixtures.py`** — 91-test suite covering all fixture cases and gate coverage.

TR-06B adds no new gate logic. It proves the TR-06A harness behaves correctly across a range of candidate states by building deterministic metadata fixtures and asserting expected results.

---

## Architecture Position

```
TR-06A Evaluation Harness (schema + gate stubs)
  ↑  (fixtures prove gate stub behavior is correct)
TR-06B Metadata Evaluation Fixtures   ← this file
  ↓  (locked metadata regression layer)

TR-06C Live Behavioral Eval Interface  ← NOT started
TR-07 Shadow/Canary                    ← NOT started
```

---

## What TR-06B Does Not Do

- Does not add live model evaluation.
- Does not test refusal behavior by prompt execution.
- Does not test constitutional behavior through inference.
- Does not promote any candidate.
- Does not load model weights.
- Does not train a model.
- Does not write to Store 1.
- Does not make network calls.
- Does not start TR-06C.
- Does not start TR-07.

---

## Fixture Case Schema

`EVALUATION_FIXTURE_CASE.schema.json` (draft 2020-12) defines 12 required fields:

| Field | Notes |
|---|---|
| `fixture_case_id` | `FC-<sha256[:16]>`, deterministic for same case_type |
| `schema_version` | `"1.0.0"` |
| `created_at` | ISO 8601 UTC |
| `case_type` | Enum of 15 case types |
| `candidate_artifact_id` | `MA-*` produced by the fixture builder |
| `candidate_mutations` | Description of what was changed from the base valid candidate |
| `lineage_mutations` | Description of what was changed in the lineage record |
| `expected_gate_results` | Map of gate → expected result for exercised gates |
| `expected_harness_rejection` | Whether the harness rejects before gate execution |
| `requires_live_inference` | const `false` |
| `metadata_only` | const `true` |
| `notes` | What this fixture case proves |

---

## The 15 Fixture Case Types

### `valid_complete_metadata`

**Purpose**: Reference case. All metadata present including synthetic provenance.
All 11 TR-06A metadata gates pass.

**What it proves**: The TR-06A harness does not false-positive on a well-formed candidate.

### `non_synthetic_candidate`

**Purpose**: Honest `not_evaluated` for `synthetic_provenance_integrity`.

**What it proves**: The gate returns `not_evaluated` for a candidate with no synthetic lineage — not `pass`. This is the correct behavior: a gate that cannot find evidence should say so rather than claim a check it did not perform.

### `missing_dep_keystone_refs`

**Purpose**: `dep_keystone_govsec_provenance_completeness` and `constitutional_fidelity` fail.

**Mutations**: `dep_keystone_ingress_ref`, `dep_keystone_evidence_sha256_ref`, and `dep_keystone_verification_report_ref` removed from candidate; corresponding lineage arrays emptied; lineage_hash recomputed.

**What it proves**: The provenance completeness gate reliably detects absent DEP.KEYSTONE refs.

### `missing_source_registry_refs`

**Purpose**: `source_registry_clearance_completeness` and `constitutional_fidelity` fail.

**Mutations**: `source_registry_refs` emptied in lineage.

### `missing_clearance_ledger_refs`

**Purpose**: `clearance_ledger_completeness` and `constitutional_fidelity` fail.

**Mutations**: `clearance_ledger_refs` emptied in lineage; `ledger_entry_id` removed from provenance.

### `missing_dry_run_refs`

**Purpose**: `dry_run_integrity` and `routing_correctness` fail.

**Mutations**: `dry_run_envelope_refs` emptied in lineage.

### `missing_synthetic_provenance`

**Purpose**: `synthetic_provenance_integrity` fails for a candidate with synthetic markers but invalid refs.

**Mutations**: `synthetic_manifest_refs = [""]` (empty string entry, invalid).

**What it proves**: The gate detects malformed synthetic refs rather than treating empty strings as valid.

### `tampered_lineage_hash`

**Purpose**: `audit_safe_json_ir_output` fails when `lineage_hash` does not match the computed hash.

**Mutations**: `lineage_hash` overwritten with `"000...000"` (64 zeros).

**What it proves**: The audit gate (enhanced in TR-06B) computes the expected lineage hash from provenance refs and detects a mismatch. This is a real integrity check — not just a presence check.

**Gate enhancement**: `audit_safe_json_ir_output` now calls `compute_lineage_hash(lineage_record)` and compares the result to `lineage_hash`. A mismatch is a gate failure.

### `raw_prompt_leak_violation`

**Purpose**: `audit_safe_json_ir_output` fails when `notes` exceeds 4096 characters.

**Mutations**: `notes` set to a >5000-character string simulating raw prompt/example text.

**What it proves**: The audit gate detects oversized text fields that may contain prompt content.

### `promotion_status_violation`

**Purpose**: Harness rejects the candidate before any gate runs.

**Mutations**: `promotion_status = "promoted"`.

**What it proves**: `_assert_candidate_safe` rejects non-`not_promoted` candidates. No gates are run; the rejection is caught before gate execution.

### `model_weights_present_violation`

**Mutations**: `model_weights_present = True`. Harness rejects.

### `runtime_deployment_violation`

**Mutations**: `runtime_deployment_allowed = True`. Harness rejects.

### `store1_write_violation`

**Mutations**: `store1_write_allowed = True`. Harness rejects.

### `external_calls_violation`

**Mutations**: `external_calls_allowed = True`. Harness rejects.

### `adapter_checkpoint_path_violation`

**Mutations**: `adapter_checkpoint_path = "/tmp/lora_adapter.pt"` added. Harness rejects.

---

## Pass / Fail / Block / not_evaluated Semantics

| Result | Meaning in fixture context |
|---|---|
| `pass` | Gate checked the relevant metadata and found no issues |
| `fail` | Gate found missing or inconsistent metadata |
| `block` | Gate found a hard governance violation (wrong flags, wrong path) |
| `not_evaluated` | Gate cannot evaluate from available metadata (e.g. no synthetic refs present) |

Fixtures assert these expected results for specific gates. Gates not listed in `expected_gate_results` may return any valid result for that fixture case.

---

## How TR-06B Verifies the TR-06A Harness Contract

The `run_fixture_case(case)` function:
1. Calls `_assert_candidate_safe` — detects rejection cases early.
2. Calls `run_all_metadata_gates` — exercises all 11 gate stubs.
3. Compares actual gate results against `expected_gate_results`.
4. Builds typed `EVALUATION_REPORT` for each gate result.
5. Calls `validate_evaluation_report` on every report.
6. Verifies `promotion_blocked=True` and `promotion_decision_emitted=False` on every report.
7. Returns `all_expectations_met=True` if no mismatches and no unexpected rejection behavior.

---

## Enhancement to TR-06A: Lineage Hash Verification

`audit_safe_json_ir_output` was enhanced to compute and verify `lineage_hash`:

```python
expected_hash = compute_lineage_hash(lineage_record)
if stored_lineage_hash != expected_hash:
    issues.append("lineage_hash mismatch: ...")
    # → result = "fail"
```

`compute_lineage_hash(lineage_record)` is now a public function in `evaluation_harness.py`, mirroring `model_registry._compute_lineage_hash`. This enables the `tampered_lineage_hash` fixture to produce a verifiable fail result.

---

## Gate Coverage Summary

| Gate | Fixture Case(s) |
|---|---|
| `constitutional_fidelity` | `valid_complete_metadata` (pass), `missing_dep_keystone_refs` (fail), `missing_source_registry_refs` (fail), `missing_clearance_ledger_refs` (fail) |
| `haap_refusal_behavior` | `valid_complete_metadata` (pass) |
| `routing_correctness` | `valid_complete_metadata` (pass), `missing_dry_run_refs` (fail) |
| `audit_safe_json_ir_output` | `valid_complete_metadata` (pass), `tampered_lineage_hash` (fail), `raw_prompt_leak_violation` (fail) |
| `store1_govmem_boundary_preservation` | `valid_complete_metadata` (pass), `store1_write_violation` (harness rejected) |
| `dep_keystone_govsec_provenance_completeness` | `valid_complete_metadata` (pass), `missing_dep_keystone_refs` (fail) |
| `source_registry_clearance_completeness` | `valid_complete_metadata` (pass), `missing_source_registry_refs` (fail) |
| `clearance_ledger_completeness` | `valid_complete_metadata` (pass), `missing_clearance_ledger_refs` (fail) |
| `dry_run_integrity` | `valid_complete_metadata` (pass), `missing_dry_run_refs` (fail) |
| `synthetic_provenance_integrity` | `valid_complete_metadata` (pass), `non_synthetic_candidate` (not_evaluated), `missing_synthetic_provenance` (fail) |
| `promotion_blocking_invariants` | `valid_complete_metadata` (pass), `promotion_status_violation` (harness rejected) |

---

## Public API

```python
from training.evaluation_fixture_builder import (
    build_valid_complete_candidate_fixture,
    build_non_synthetic_candidate_fixture,
    build_synthetic_candidate_fixture,
    build_mutated_candidate_fixture,
    build_fixture_catalog,
    write_fixture_catalog,
    run_fixture_case,
    summarize_fixture_results,
    CASE_TYPES,
)

# Get all 15 fixture cases
catalog = build_fixture_catalog()

# Run all cases through the TR-06A harness
results = [run_fixture_case(case) for case in catalog]

# Summarize
summary = summarize_fixture_results(results)
# summary["all_cases_met_expectations"] → True (regression passes)
# summary["promotion_blocked"]          → True (always)

# Write fixture metadata to disk (strips _candidate for clean JSON)
path = write_fixture_catalog("/tmp/tr06b_fixtures")

# Run a single specific case
case = build_mutated_candidate_fixture("missing_dep_keystone_refs")
result = run_fixture_case(case, out_dir="/tmp/tr06b_eval")
# result["all_expectations_met"] → True
```

---

## Relationship to TR-06A

TR-06B does not add new gate logic — it proves the existing TR-06A gates behave correctly. If a gate stub changes behavior in TR-06A, the corresponding fixture case's `expected_gate_results` must be updated. The fixture catalog is the regression layer.

TR-06B also documents the boundary between metadata-only evaluation and future live behavioral evaluation:

| Check | TR-06A / TR-06B (metadata) | TR-06C (future behavioral) |
|---|---|---|
| Provenance refs present | ✓ fixture-tested | — |
| Lineage hash integrity | ✓ fixture-tested | — |
| Governance flags deny-by-default | ✓ fixture-tested | — |
| HAAP refusal on live prompts | ✗ | ✓ |
| Constitutional fidelity on outputs | ✗ | ✓ |
| Routing on live inputs | ✗ | ✓ |

---

## Validation Commands

```bash
python3 -m py_compile training/evaluation_fixture_builder.py training/evaluation_harness.py

python3 -m pytest -q training/tests/test_evaluation_fixtures.py

python3 -m pytest -q training/tests/test_evaluation_harness.py

python3 -m pytest -q training/tests/test_model_registry.py

python3 -m pytest -q training/tests/test_dep_keystone_training_ingress.py

python3 -m pytest -q training/tests/

python3 -m pytest -q
```

---

## Governance Attestation

No real training occurred in TR-06B. No model weights were loaded or created. No LoRA or QLoRA adapters were created. No adapter checkpoint files were created. No Store 1 writes occurred. No external calls were made. No model was promoted. No runtime deployment occurred.

All evaluation reports produced via TR-06B fixtures carry `promotion_blocked=true`, `promotion_decision_emitted=false`, `metadata_only=true`, and `operator_review_required=true`.

TR-06C live behavioral evaluation interface was not started.  
TR-07 shadow/canary evaluation was not started.
