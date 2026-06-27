# TR-04C: Synthetic Output Review Bridge

**Version**: 1.0.0  
**Status**: Implemented  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-27  
**Requires**: TR-04A.5 (synthetic_doctrine.py)  
**Feeds into**: TR-02 review queue → TR-03 dataset pipeline → TR-04B dry-run  
**Not implemented here**: Real training, model weights, Store 1 writes, TR-05

---

## Synthetic Records Are Not Training Data

Records produced by `synthetic_doctrine.py` (TR-04A.5) are **candidates only**.
They cannot enter any training dataset directly. Every record must pass through:

```
synthetic_doctrine.py output
  ↓ [synthetic_review_bridge.py]
  ↓  checksum verification
  ↓  per-record validation
  ↓  provenance preservation
  ↓
operator-review candidates (training_candidate lane)
  ↓ [review_queue.py — TR-02]
  ↓  operator inspect + approve / reject / redact
  ↓
approved candidates → TR-03 dataset pipeline → TR-04B dry-run
```

The bridge enforces this gate. It does not short-circuit it.

---

## What TR-04C Does

`training/synthetic_review_bridge.py` reads a directory produced by
`synthetic_doctrine.py` and converts each valid synthetic record into a
reviewable improvement candidate in the `training_candidate` lane.

The bridge:
1. **Verifies SHA-256 checksums** of `synthetic_records.jsonl` and
   `synthetic_manifest.json` before reading any content.
2. **Validates each record** for required provenance fields and governance flags.
3. **Fails closed** if any record fails validation — no partial output.
4. **Converts valid records** into candidates preserving all provenance fields.
5. **Writes output** only after all validation passes.

---

## Required Provenance Fields

Every synthetic record must carry these fields before the bridge accepts it:

| Field | Requirement |
|-------|------------|
| `synthetic_origin` | Must be exactly `true` (boolean) |
| `prompt_hash` | Must be non-empty |
| `generation_agent_id` | Must be non-empty |
| `source_id` | Must be non-empty |
| `clearance_ledger_entry_id` | Must be non-empty |

If any field is missing or `synthetic_origin` is not `true`, the entire batch
is rejected and no output is written.

The bridge also checks `governance_labels` for security violations — any of
`training_allowed`, `store1_write_allowed`, `runtime_deployment_allowed`,
`model_promotion_allowed`, or `external_calls_allowed` being `true` triggers
an immediate hard stop.

---

## Checksum Validation

The bridge reads `checksums.sha256` from the synthetic output directory and
verifies SHA-256 of every listed file before loading any content. A mismatch
on either `synthetic_records.jsonl` or `synthetic_manifest.json` causes
immediate failure — the bridge will not process records from a tampered batch.

This protects against:
- Accidental file corruption
- Unauthorized record injection after generation
- Out-of-sync manifest / JSONL

---

## Preserved Provenance in Candidates

Every candidate produced by the bridge preserves the full synthetic lineage
from the original record:

| Candidate field | Source |
|----------------|--------|
| `synthetic_origin` | From record (always `true`) |
| `synthetic_record_id` | From record's `record_id` |
| `source_id` | From record |
| `source_registry_version` | From record |
| `clearance_ledger_entry_id` | From record |
| `generation_agent_id` | From record |
| `prompt_template_id` | From record |
| `prompt_hash` | From record |
| `category` | From record |

This chain allows any approved candidate to be traced back through:
- The clearance ledger entry that authorized the source
- The source registry entry for the doctrine source
- The specific template and generation agent

---

## Operator Review Required

Every candidate produced by the bridge carries:

```json
{
  "operator_review_required": true,
  "promotion_status":         "candidate_only",
  "training_allowed":         false,
  "store1_write_allowed":     false,
  "runtime_deployment_allowed": false,
  "model_promotion_allowed":  false,
  "external_calls_allowed":   false
}
```

These constants are enforced at both code and assertion level. A candidate
cannot enter the `dataset_promotion_pending` state until an operator explicitly
approves it via `review_queue.py`.

---

## Relationship to TR-04A.5, TR-03, and TR-04B

**TR-04A.5 → TR-04C**: The bridge reads the output of `synthetic_doctrine.py`.
It trusts the checksum-protected output and does not re-validate against the
source registry or clearance ledger — those gates were enforced at generation
time and the results are captured in `clearance_ledger_entry_id`.

**TR-04C → TR-02**: Bridge output is a valid `training_candidate` JSONL file
compatible with `review_queue.py`. Operators can inspect, approve, reject,
redact, or reclassify candidates using existing TR-02 tooling.

**TR-02 → TR-03**: Operator-approved candidates (status `dataset_promotion_pending`)
can then enter the TR-03 immutable dataset builder pipeline as governed training
material.

**TR-03 → TR-04B**: The TR-03 artifact (with checksums, manifests, and scan
reports) feeds the TR-04B dry-run trainer for pre-training validation.

---

## Output Artifacts

All artifacts are written to `--out-dir` (which must be outside the repository).

| File | Description |
|------|-------------|
| `synthetic_candidates.jsonl` | One candidate per line (TC-YYYYMMDD-sha8 format) |
| `bridge_manifest.json` | Bridge run metadata: operator, source, counts, governance |
| `audit_record.json` | Audit log: provenance references and counts (no raw content) |
| `checksums.sha256` | SHA-256 checksums of the three output files |

The `audit_record.json` explicitly excludes raw `input` and `desired_output`
text from the synthetic records (`raw_examples_excluded: true`). It contains
only provenance references (source IDs, ledger entry IDs, counts) and
governance flags.

---

## Candidate ID Stability

Candidate IDs are derived deterministically from the record's own `record_id`
and `created_at`:

```
candidate_id = "TC-{YYYYMMDD}-{SHA-256('synthetic:{record_id}')[:8]}"
```

Since `record_id` in the synthetic JSONL is stable (produced deterministically
by the generator), running the bridge twice on the same synthetic dir produces
the same candidate IDs. This enables idempotent bridge runs without duplication
concerns in downstream review queues.

---

## CLI Command

```bash
python3 training/synthetic_review_bridge.py \
  --synthetic-dir /tmp/synthetic_demo \
  --out-dir       /tmp/synthetic_candidates \
  --operator-id   TEST_REVIEW_OP_001
```

---

## Validation Commands

```bash
python3 -m py_compile training/synthetic_review_bridge.py

python3 -m pytest -q training/tests/test_synthetic_review_bridge.py

python3 -m pytest -q training/tests/test_synthetic_doctrine.py

python3 -m pytest -q training/tests/

python3 -m pytest -q
```

---

## No Real Training

TR-04C performs no real training. It does not:

- Create or modify model weights
- Write to Store 1
- Deploy to the runtime
- Promote any model to the registry
- Call any external provider SDK or API
- Make any network call

TR-05 (Model Registry and Lineage) was not started here.

---

## Governance Attestation

No real training occurred in TR-04C. The bridge converts synthetic records
into review candidates only. All candidates carry `training_allowed: false`
and `operator_review_required: true`. Operator review is required before any
SFT use of generated candidates. No Store 1 writes occurred. TR-05 was not
started.
