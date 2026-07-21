# TR-04A.3: Training Source Registry Validator

**Version**: 1.0.0  
**Status**: Implemented  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-26  
**Requires**: TR-04A.1 (SOURCE_REGISTRY.schema.json), TR-04A.2 (source_registry_seed.json)  
**Gates**: TR-04B (dry-run training adapter inputs)  
**Not implemented here**: clearance_ledger.json (TR-04A.4), Ed25519 signing (TR-04A.5)

---

## What TR-04A.3 Does

`training/source_registry.py` is the executable validator and clearance state
machine for the Training Source Registry. It enforces the constitutional
constraint declared in `source_registry_seed.json`:

> No data source enters the Abigail training pipeline without registry
> presence, clearance posture, provenance, checksum manifest, allowed-use
> declaration, and Human Principal authority where required.

The validator loads a registry JSON document, validates its structure and
invariants, and exposes a `assert_source_allowed(source_id, requested_use)`
gate that the TR-04 dry-run trainer calls before producing any output.

---

## Clearance State Machine

Every source in the registry moves through the following nomination-to-approval
pipeline. Only `approved` sources may enter TR-04B.

```
NOMINATION
  └─► draft
        └─► reg01_pending   ← REG-01 intake review
              └─► lgl01_pending   ← LGL-01 legal review
                    └─► ea00_pending   ← EA-00 ethics/architecture review
                          └─► hp_pending   ← Human Principal decision
                                └─► approved   ← cleared for use
                                └─► rejected   ← permanently denied
                                └─► blocked    ← immediate block, no path forward
                                └─► archived   ← sunset/retired
```

**Terminal statuses** (`blocked`, `rejected`, `archived`) cannot be reversed
through the state machine. A new source_id must be nominated for reconsideration.

**clearance_ledger.json** (TR-04A.4) and **Ed25519 signing** (TR-04A.5) are
not implemented in this module. When they are implemented, a valid clearance
ledger entry will be an additional required gate before TR-04B admission.

---

## Gate Rules: `assert_source_allowed(source_id, requested_use)`

The following checks are applied in sequence. Any failure raises
`SourceRegistryError` (or a subclass), which the dry-run trainer converts
to `HARD_STOP` + nonzero exit.

| # | Check | Exception |
|---|-------|-----------|
| 1 | `requested_use` is a valid use value | `SourceNotAllowedError` |
| 2 | `source_id` exists in registry | `SourceNotFoundError` |
| 3 | `registry_status` is not `blocked` | `SourceBlockedError` |
| 4 | `registry_status` is not `rejected` or `archived` | `SourceBlockedError` |
| 5 | `registry_status` is not pending (any sub-status) | `SourceNotAllowedError` |
| 6 | `registry_status` is `approved` | `SourceNotAllowedError` |
| 7 | `requested_use` is in `allowed_uses` | `SourceNotAllowedError` |
| 8 | `sha256_manifest` is present and non-empty | `SourceNotAllowedError` |
| 9 | `hp_decision_status` is `approved` or `not_required` | `SourceNotAllowedError` |
| 10 | If HP approved: `hp_decision_timestamp` is non-null | `SourceNotAllowedError` |

---

## Blocked and Pending Examples

| Source | Status | Reason |
|--------|--------|--------|
| L6-001 Common Crawl | `blocked` | Uncertain third-party rights, high PII/copyright risk. `allowed_uses: []` permanently. |
| L5-001 Common Pile v0.1 | `hp_pending` | Component-level review not complete. No SFT/pretraining until HP approval. |
| L7-001 Stack Exchange CC BY-SA | `hp_pending` | Share-alike mitigation strategy not yet established. |
| L2-001 NIST AI RMF | `reg01_pending` | REG-01 intake review not complete. |
| L4-001 PMC Open Access | `hp_pending` | Article-level license filtering required. |

---

## TR-04 Dry-Run Trainer Integration

The TR-04 dry-run trainer now enforces source registry clearance as gate step 10:

```
--source-id      Required: an approved registry entry (e.g. L1-001).
--requested-use  Default: sft_candidate. One of: rag, sft_candidate,
                 synthetic_seed, evaluation_reference, pretraining_candidate.
--source-registry  Optional: alternate registry path.
--allow-unregistered-source-for-tests  TEST-ONLY bypass flag.
```

**Behavior without `--source-id`**: fails closed with `SOURCE_REGISTRY_BLOCK`
unless `--allow-unregistered-source-for-tests` is explicitly set. That flag is
test-only and must not appear in production invocations.

Source clearance is recorded in:
- `dry_run_envelope.job_intent.source_registry_cleared`
- `dry_run_envelope.validation_summary.source_registry_cleared`
- `audit_record.source_id`, `audit_record.requested_use`,
  `audit_record.source_registry_cleared`

---

## Public API

```python
from source_registry import (
    get_source,               # get_source("L1-001") → dict
    list_sources,             # list_sources(status="approved", lane=1) → list
    validate_registry,        # validate_registry() → {"valid": True, ...}
    assert_source_allowed,    # assert_source_allowed("L1-001", "sft_candidate") → dict
    build_registry_summary,   # build_registry_summary() → audit-safe dict
)
```

All functions accept an optional `registry_path` argument to override the
default (`training/source_registry_seed.json`).

---

## Exact Commands

```bash
# Run registry validator tests
python3 -m pytest -q training/tests/test_source_registry.py

# Run dry-run trainer bridge tests
python3 -m pytest -q training/tests/test_dry_run_trainer.py

# Run with approved source (L1-001 for sft_candidate)
python3 training/dry_run_trainer.py \
  --dataset-dir /tmp/tr03_output \
  --out-dir     /tmp/tr04_dry_run \
  --mode        simulation \
  --operator-id TEST_OP_001 \
  --source-id   L1-001 \
  --requested-use sft_candidate

# Blocked example (will fail with SOURCE_REGISTRY_BLOCK)
python3 training/dry_run_trainer.py \
  --dataset-dir /tmp/tr03_output \
  --out-dir     /tmp/tr04_dry_run_blocked \
  --source-id   L6-001 \
  --requested-use sft_candidate
```

---

## What Is Not Implemented

**TR-04A.4 — clearance_ledger.json**: Not implemented. The clearance ledger
will record HP decisions, REG-01 outcomes, and LGL-01 outcomes as signed
WORM entries. Until TR-04A.4 is implemented, the registry seed is the
authoritative source of clearance state.

**TR-04A.5 — Ed25519 signing**: Not implemented. Future versions of this
module will require Ed25519 signatures on HP decisions and clearance ledger
entries.

**TR-05 — Model registry and lineage**: Not started.

---

## Governance Attestation

No real training occurred in this phase. TR-04A.3 adds a validation and
gating layer only. All TR-04 governance invariants (`training_allowed: false`,
`operator_promotion_required: true`, etc.) remain unchanged.
