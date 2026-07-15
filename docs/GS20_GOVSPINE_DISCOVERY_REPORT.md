# GS-2.0: Governance-Spine Discovery Report

**Document ID:** GS20_GOVSPINE_DISCOVERY_REPORT
**Version:** 1.0
**Date:** 2026-07-15
**Status:** ACTIVE — discovery/report only (no code changed)
**Classification:** Internal Governance Doctrine
**Authority:** LOGOS Governance Systems Inc.
**Sprint:** GOVSPINE-02 / task GS-2.0
**Branch surveyed:** `sprint/full-doctrine-mode` @ `80765bf`

---

## Executive Summary

This is the read-only discovery pass mandated by GS-2.0, and the prerequisite for
GS-2.1 through GS-2.4. Per the sprint's governing axiom — *"If real repo structure
contradicts an assumption below, the discovery task's findings override this document"*
— two findings materially change the shape of Sprint 02:

1. **The Sprint-02 target substrate (RAG / embeddings / vector store / durable
   long-term memory) is not implemented.** It exists as scaffolding, `TODO`s, and an
   unused trust-class enum. GS-2.2 / GS-2.3 / GS-2.4 as written target a pipeline that
   does not yet exist. This is not a defect to patch; it is a build-vs-harden decision
   (see §7).

2. **The fail-closed prerequisite (ABIGAIL-SPRINT-01 Phase 0) is NOT merged into this
   sprint branch.** The corrective work is real and test-backed but lives on unmerged
   branch `sprint/p0-corrective` (`f16f83a`). On `sprint/full-doctrine-mode`, Sentinel
   still fails **open**. Per the sprint's own words, hardening built on this base "is
   cosmetic" until the merge lands (see §6).

The five GS-2.0 inventory items follow, each with concrete `file:function:line`
references or an explicit "not found."

---

## 1. Where retrieved / RAG content enters the pipeline (before vectorization / context)

**Finding: NOT FOUND as an implemented pipeline stage.** There is no code that fetches
external documents, queries a store, and injects results into model context.

- Trust classes for retrieval are *named but never populated* —
  `abigail/orchestration/schemas.py:29-33` `VALID_TRUST_CLASSES` includes
  `rag_retrieved`, `web_retrieved`, `tool_returned`, `untrusted_external`. A repo-wide
  search shows these values appear **only** in this enum; no code constructs a manifest
  with them.
- The one real content-source assignment is a constant:
  `abigail/orchestration/runtime_bridge.py:47` `_DEFAULT_SOURCE_TRUST = "user_supplied"`,
  applied at `runtime_bridge.py:113`. Every request is tagged `user_supplied`.
- The only "prior content" pulled into context is a session **summary** (not document
  text): `abigail/tacit_prepass.py:248-254` `_prior_context()`, fed to the Tacit Context
  Card and appended to the system prompt at
  `abigail/abigail_hardened_enhanced.py:646-660`.
- Rust `corridor.rs` / `pipeline.rs` / `govmem.rs` contain no retrieval code — they
  inspect the raw inbound/outbound payload only.

**Implication for GS-2.2:** there is no ingestion point at which to attach provenance
tags, because there is no ingestion.

---

## 2. Where embeddings are generated / which store they land in

**Finding: NOT FOUND. No embeddings are generated and no vector store exists.**

- Embedding call site is a zero-vector stub — `governance-spine/src/govmem.rs:305-310`
  `SentenceEmbedder::encode()` returns `vec![0.0; 384]` with `// TODO: Actual embedding`.
  The struct is empty (`govmem.rs:297-299`, `// TODO: rust-bert or candle`).
  `GovMem.embedding_model` is `None` (`govmem.rs:162`) and never loaded; the embedding
  step in `record_turn_v2` is commented out (`govmem.rs:224-225`).
- No vector DB anywhere: `requirements.txt` has only anthropic/flask/groq/httpx/pyyaml;
  `docker-compose.yml` has only `sentinel` + `abby`; `docker-compose.govmem-v2.yml` only
  sets `GOVMEM_MODE=v2` + a "Future: RL model" ONNX path; `.abigail.env.example` has no
  store config. No Pinecone/Weaviate/pgvector/qdrant/chroma/faiss.
- Note on nomenclature: `tools/govmem/store2_loader.py`'s `vector_id` field
  (`store2_loader.py:96`) is an **attack-taxonomy id** (e.g. `MT-G4-01-…`), *not* an
  embedding vector. Store1/Store2 are a doctrine-record JSONL pipeline, not a vector DB.

**Implication for GS-2.3:** the embedding-inversion monitoring target (vector-store query
patterns) has no store to monitor yet. The task can still land as a **query-pattern
monitor on the govmem read API** (see §7), but not on embedding queries per se.

---

## 3. Where conversation / session memory is read and written

**Finding: FOUND (runtime governance memory); the durable long-term write is a stub.**

Two systems exist:

**Runtime governance memory (Rust)** — `governance-spine/src/session_memory.rs`:
- Tier 1 `SessionMemory` (per-session): struct `session_memory.rs:47-70`;
  **write** `ingest_signal()` `:143-252`; **read** `threshold_modifier()` `:255`,
  `to_fingerprint()` `:314`.
- Tier 2 `StrategicMemory` (cross-session actor profiles): struct `:406-408`, backed by
  an **in-memory** `HashMap<String, ActorProfile>`.
- **Long-term WRITE path** — `governance-spine/src/pipeline.rs:340-350`
  `end_session()` → `StrategicMemory::ingest_session()` (`session_memory.rs:416-447`,
  carries forward 30% of session threat at `:441`).
- **Long-term READ path** — `pipeline.rs:385` `advise_session_start()`
  (`session_memory.rs:450-486`), invoked from `init_session_memory()` `:374-399`.

**Critical caveat (affects GS-2.4):** the long-term write is **not durable**.
`POST /session/end` (`server.rs:187-201`) returns `"persisted":true`, but there is **no
filesystem persistence** — no `fs::write`/`File::create` in `governance-spine/src/*.rs`.
`StrategicMemory` is a process-lifetime HashMap; the `SENTOW_MEMORY_PATH` env var
(`docker-compose.yml`) is only printed (`server.rs:235-236`), never read/written.
The `"persisted":true` response is misleading.

**Conversation memory (Python)** — `abigail/abigail_hardened_enhanced.py:678,682`
append user/assistant turns to an in-memory `session.messages`; `session.record_turn()`
at `:643` updates DRS/CRSV counters. The only durable conversation artifact is CLI input
history `~/.abigail_history` (`:109`, `:1540`) — terminal history, not semantic memory.

**Implication for GS-2.4:** the write path to gate exists (`end_session` →
`ingest_session`), but it persists nothing to disk. Gating it stops in-process poisoning
carry-over across sessions **within one process lifetime**; cross-restart durability is a
separate, unbuilt concern.

---

## 4. Does any existing constitutional gate inspect retrieved content?

**Finding: NO. The gate inspects only the user prompt (inbound) and model output
(outbound). Retrieved / memory content has no path through the gate.**

- Gate entrypoints take single opaque strings:
  `governance-spine/src/pipeline.rs:162` `inbound(user_input, session_id)` and
  `pipeline.rs:297` `outbound(model_output, session_id)`. No parameter or layer accepts
  retrieved documents / memory context.
- HTTP surface — `server.rs:118` `POST /inspect` → `inbound`; `server.rs:131`
  `POST /outbound` → `outbound`; verdicts serialized `server.rs:82-98` are UPPERCASE
  (`APPROVED`, `RESTRICTED`, `QUARANTINED`, `HARD_LOCKED`, `HAAP_GATED`).
- Python caller inspects only the raw user turn —
  `abigail/abigail_hardened_enhanced.py:603` `_sentinel_inspect(raw, …)`; `_sentinel_inspect`
  (`:863`) POSTs `{"payload": <raw user msg>}`.
- Injection detection is real but runs on that same payload:
  `governance-spine/src/sentinel.rs:105` `inspect()`, `INJECTION_PATTERNS`
  `sentinel.rs:9-75` (SENT-001 "ignore previous instructions" `:12`, variants `:34-39`),
  with unicode/zero-width/homoglyph/l33t/base64 normalization (`:127,138,185,207,212`).
  `overwatch.rs:305` `detect_poisoning()` matches `<!-- ignore`, `[system]`, `{{prompt}}`
  — again on the inbound/outbound payload, not on separately-tagged retrieved text.
- **Trust-tier / provenance in the gate: NOT FOUND.** Zero matches for
  `trust_tier|provenance|untrusted|source_tag` in `governance-spine/src/*.rs`. The
  Python `source_trust_class` (`schemas.py:102`) is audit-label-only — hardcoded to
  `user_supplied` and never branched on.

**Implication for GS-2.2:** this is the genuine gap. Even the existing SENT-009
"indirect injection" rule cannot fire on retrieved content, because retrieved content is
never a gate input. The gate must gain a *typed, provenance-tagged* input path before
untrusted-tier handling means anything.

---

## 5. Red-team harness (FASDTEST) entrypoint + coverage format

**Finding: FOUND — three components; only one has produced live results; none run in CI.**

- **Live BD1A runner** — `tests/run_redteam.py`, `main()` `:100`. Fires a hardcoded
  `VECTORS` list (`:40`) as HTTP POSTs to `SENTINEL_URL` (`:14`, `:9091/inspect`),
  writing JSONL to `redteam_live_results.jsonl` (`:15`). Run: `python3 tests/run_redteam.py`.
  Output is **per-vector pass/fail via `blocked`** (set when verdict ∈
  QUARANTINED/HARD_LOCKED/HAAP_GATED/RESTRICTED, `:119`) plus an aggregate `block_rate`
  (`:150`). Sample: `{"probe_id":"A01","verdict":"QUARANTINED","blocked":true,…}`.
  Currently exercises phases **A,B,C,D,E,F,V,G,N,J,P** (36 records, all `blocked:true`);
  does **not** exercise H,I,K,X,M,O.
- **Probe/battery generator** — `tests/sentow_redteam.py`, `main()` `:648`, argparse
  `--mode battery|vector|single|ddos|list`. Runs against `mock_sentinel_response()`
  (`:558`), not the live spine, unless the mock is swapped. Own 7-vector × 4-level
  taxonomy (`VECTOR_TAXONOMY` `:37`).
- **FASDTEST dark-psychology harness (dormant)** —
  `redteam/tax2/harness/fasdtest_dark_psych_v2_1.py`, class `FASDTESTDarkPsychHarness`.
  Iterates `DARK_PSYCH_VECTORS` (`:49`, `MT-G4-…`) × levels A/B/C/D. Emits **detection-rate
  per vector per level** (`pass = rate ≥ 80%`), writing `haap_audits/dark_psych_*.log`
  and `govmem_ingest/dark_psych_*.jsonl`. Explicitly barred from CI per
  `redteam/tax2/README.md` and `RUNBOOK.md`.
- **Makefile / CI:** `make redteam` (`Makefile:110-114`) shells to `tests/redteam.sh`,
  **which does not exist** — the target is a stub. The only workflow is
  `.github/workflows/pages.yml` (GitHub Pages deploy). **No red-team job runs in CI.**
- **Adding cases:** BD1A vectors are edited inline in `run_redteam.py:40`; source-of-truth
  taxonomy is `tests/vectors/logos_bd1a_taxonomy_v4.md` +
  `tests/vectors/threat-taxonomy.yaml`; FASDTEST vectors in `DARK_PSYCH_VECTORS`
  (`fasdtest_dark_psych_v2_1.py:49`).

**Implication for GS-4.3:** the harness exists and has a block-rate format, but is
manual/uncategorized-by-layer, tests the pattern-matcher (not real RAG/tool/agent paths),
and is not in CI. Per-layer measurable coverage is a real gap.

---

## 6. Prerequisite check — ABIGAIL-SPRINT-01 Phase 0 (fail-closed)

**Verdict: NOT MERGED into this sprint branch → prerequisite UNMET on `sprint/full-doctrine-mode`.**

- The full P0 set is one commit `f16f83a` "ABIGAIL-SPRINT-01 Phase 0 corrective fixes
  (fail-closed baseline)" on branch **`sprint/p0-corrective`**.
- `git merge-base --is-ancestor f16f83a HEAD` → **NO**. `f16f83a` is absent from both
  local `sprint/full-doctrine-mode` (`80765bf`) and `origin/sprint/full-doctrine-mode`
  (also `80765bf` after fetch).
- The three security commits cited in the sprint brief (`80765bf` scope escalation,
  `0ee22bb` admin auth, `db39de1` Sentinel verdict case) are Bucket-2 / Layer-0 items
  that predate and are ancestors of both branches — they are **not** the P0 corrective
  sprint.
- **Proof main still fails open:** `abigail/abigail_hardened_enhanced.py:602-618` blocks
  only on `quarantined`/`hard_locked`; `restricted` merely logs-and-continues; there is
  **no branch for an offline/unreachable/unrecognized verdict** — it falls through to the
  weaker Python layer. `_sentinel_inspect` on network error returns
  `{"verdict":"sentinel_offline"}` (`:872`), which is not in the block set.
- **P0-4 Ed25519 (needed by GS-3.2) is split:** the **Rust** signer is real and in main
  (`governance-spine/src/crypto.rs:33,48,65,71,115`, `ed25519_dalek`). The **Python**
  handoff-packet signer is still a placeholder in main
  (`abigail/orchestration/handoff_packet.py:88,111` emit `SHA256_CHAIN_PLACEHOLDER`); the
  real Python implementation exists only on the unmerged `sprint/p0-corrective`.

> **Note on the memory record.** The project memory states "ABIGAIL-SPRINT-01 P0 —
> Phase 0 corrective fixes DONE 2026-07-15 (PR #2)." That reflects the PR being *opened*;
> it is **not merged** into the branch this series builds on. This report's finding
> overrides the assumption of a merged prerequisite.

---

## 7. Consequence for GS-2.1 → GS-2.4 (discovery overrides the plan)

| Task | Stated target | Reality (this report) | Recommended disposition |
|------|---------------|------------------------|--------------------------|
| **GS-2.1** Crosswalk | Map internal taxonomy vs MS v2.0 / ATLAS / OWASP ASI | BD1A is prose (`logos_bd1a_taxonomy_v4.md`); already has a phase-level external crosswalk; "36" is an unbacked policy figure (real count ~77 codes; a separate 25-entry NIST YAML uses a different id scheme) | **Proceed now.** Extend the existing crosswalk with as-built control + red-team coverage columns; document the id-reconciliation gap. Delivered as `GS21_TAXONOMY_CROSSWALK.md`. |
| **GS-2.2** Provenance + trust separation | Tag retrieved content at ingestion; gate untrusted tier | No ingestion point, no gate input for retrieved content, trust enum unused | **Rescope decision needed** (§below). Cannot attach provenance to a pipeline that does not exist. |
| **GS-2.3** Embedding-inversion monitoring | Rate/pattern monitor on vector-store queries | No embeddings, no vector store | **Rescope** to a query-pattern monitor on the govmem read API, or defer until a store exists. |
| **GS-2.4** LT-memory write gating | Gate untrusted writes to long-term memory | Write path exists (`end_session`→`ingest_session`) but persists nothing to disk | **Partially actionable** — can gate the in-process carry-over now; durable persistence is out of scope. |

**The Sprint-02 fork.** GS-2.2–2.4 assume an implemented memory/RAG layer. Two honest paths:

- **(A) Harden-as-built:** implement the provenance/trust/gate abstractions on the *govmem
  and session-memory paths that do exist* (typed inputs, trust tier on `ingest_signal`
  and `ingest_session`, gate-before-persist), and build the RAG entry point *with the
  gate already wired* when RAG is implemented. This keeps the sprint's intent without
  faking a pipeline.
- **(B) Rescope the sprint:** formally move GS-2.2–2.4 to "build the memory/vector layer
  gated-by-construction" and re-baseline the exit criteria, since the current criteria
  ("untrusted retrieved content cannot reach model-as-instruction") are vacuously true
  when no retrieval exists.

Either way, **the fail-open prerequisite (§6) should be resolved first** — merging
`sprint/p0-corrective` — or all of the above sits on a fail-open Sentinel.

---

## Verification (GS-2.0 exit criteria)

> *"Discovery report exists and lists concrete file:function:line references for each of
> the five items above, or explicitly states 'not found' for any that don't exist."*

- Item 1 (RAG entry): **not found** — §1, with the trust-enum + `runtime_bridge.py:47`
  evidence for why.
- Item 2 (embeddings/store): **not found** — §2, `govmem.rs:305-310` stub + dependency
  survey.
- Item 3 (session memory R/W): **found** — §3, `session_memory.rs` + `pipeline.rs:340-350`;
  durability caveat documented.
- Item 4 (gate on retrieved content): **found (gate) / not found (retrieved-content
  path)** — §4, `pipeline.rs:162/297`.
- Item 5 (FASDTEST harness + format): **found** — §5, `run_redteam.py` + `fasdtest_*`.

All references are to `sprint/full-doctrine-mode` @ `80765bf`.

---

*LOGOS Governance Systems Inc. — Internal Governance Doctrine*
