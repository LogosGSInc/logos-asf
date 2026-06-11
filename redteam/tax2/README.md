# TAX2 — Multi-Turn Reasoning Hardening Taxonomy
## LOGOS Governance Systems Inc. — Red-Team / GovMem Layer

**Status:** Staged, dormant. Harness not executed.
**Sprint staged:** Sprint 5A
**Baseline taxonomy:** BD1A (assumed present in GovMem v2)
**Extension layer:** TAX2 G2–G6 + BD1A Phase Q Addendum

---

## Purpose

TAX2 is the multi-turn reasoning hardening taxonomy for Abigail and the LOGOS Agentic Software Firm. It is a **defensive instrument** — every entry describes detection signatures, escalation patterns, and mitigation doctrine so Abigail can recognize reasoning pressure before it becomes a breach.

TAX2 does **not** catalog attack recipes. It does not preserve payloads, bypass instructions, or reusable offensive tooling.

---

## Relationship to BD1A

BD1A remains the baseline taxonomy. TAX2 extends BD1A by adding multi-turn detection layers that BD1A's single-turn framework cannot cover.

| BD1A Weakness | TAX2 Extension |
|---------------|----------------|
| BD1A:F01 — Multi-Turn Semantic Drift | All TAX2 G2–G6 entries provide causal attribution: not just "drift occurred" but "drift was caused by mechanism X" |
| BD1A:F02 — Soft Precursor Accumulation | TAX2 Level A detection signatures define exactly what soft precursors look like and when to escalate |

Do not remove or replace BD1A entries. TAX2 links back to BD1A vector identifiers (`BD1A:F01`, `BD1A:F02`, etc.) throughout.

---

## Generation Architecture

| Generation | Class | File | Status |
|-----------|-------|------|--------|
| G2 | Structural Variants | `TAX2-G2-structural-variants-v1.1.md` | Staged |
| G3 | Encoding + Multi-Turn Hybrids | `TAX2-G3-encoding-hybrids.md` | Staged |
| G4 | Cognitive Distortion Chains (Phase Q) | `TAX2-G4-cognitive-distortion.md` | Staged |
| G5 | Dialectical Manipulation | `TAX2-G5-dialectical.md` | Staged |
| G6 | Cognitive-Dialectical Fusion | `TAX2-G6-fusion.md` | Staged |

---

## Harness

`harness/fasdtest_dark_psych_v2_1.py` is a regression test harness. It is **dormant**.

- Do not execute it without explicit operator approval.
- Do not add it to CI or any automatic execution hook.
- Do not import it from other modules.
- See `RUNBOOK.md` for future controlled execution requirements.

**No TAX2 execution occurred during Sprint 5A staging.**

---

## Safety Boundaries

- Do not add raw offensive payloads to this directory.
- Do not add working jailbreak prompts or bypass recipes.
- All TAX2 entries must remain written from the defender's position.
- Sanitized regression templates (placeholders, not payloads) are permitted in the harness.

---

## Future Execution Requirements

Future controlled runs require:

1. Isolated local environment — no production endpoints, no secrets
2. Explicit operator approval before each run
3. Output routed to `audit/` and `govmem_ingest/` directories only
4. Post-run review before GovMem ingestion is accepted

See `RUNBOOK.md` for the full checklist.
