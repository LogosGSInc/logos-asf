# GS-2.1: Taxonomy Crosswalk — BD1A vs MS v2.0 / ATLAS / OWASP ASI

**Document ID:** GS21_TAXONOMY_CROSSWALK
**Version:** 1.0
**Date:** 2026-07-15
**Status:** ACTIVE — crosswalk / backlog artifact
**Classification:** Internal Governance Doctrine
**Authority:** LOGOS Governance Systems Inc.
**Sprint:** GOVSPINE-02 / task GS-2.1
**Depends on:** [GS20_GOVSPINE_DISCOVERY_REPORT](GS20_GOVSPINE_DISCOVERY_REPORT.md)
**Source taxonomy:** `tests/vectors/logos_bd1a_taxonomy_v4.md` (BD1A v4.0-draft)

---

## Purpose

GS-2.1 requires a crosswalk: *internal vector → Microsoft v2.0 failure mode → ATLAS
technique → OWASP ASI category → current spine control → current red-team coverage
(yes/no/partial)*, with every `no`/`partial` row routed to a sprint task or explicitly
deferred.

BD1A already carries a phase-level external crosswalk (`logos_bd1a_taxonomy_v4.md:326-348`)
mapping to MITRE ATLAS / OWASP ASI / MS AIRT / SAGE-RT. Per the axiom ("do not introduce a
new format without checking what's already there"), this document **extends that existing
matrix** with the two columns it lacks — **as-built spine control** and **red-team
coverage** — both grounded in the GS-2.0 discovery evidence, not in the taxonomy's stated
intent.

---

## 0. Taxonomy reconciliation gap (a GS-2.1 finding in itself)

Before the crosswalk: the internal taxonomy is not a single authoritative artifact.

| Artifact | Format | Count | Id scheme |
|----------|--------|-------|-----------|
| `tests/vectors/logos_bd1a_taxonomy_v4.md` | Prose + Markdown tables | ~77 codes / ~144 test cases | `A01`, `F02` |
| `tests/vectors/threat-taxonomy.yaml` | Structured YAML (NIST AI 100-2e2025) | 25 entries | `A.1`, `F.2` |
| `redteam/tax2/tax2_registry.json` | Structured JSON (TAX2 multi-turn ext.) | dormant | `MT-G4-01` + `BD1A:F01` |
| `training/MODEL_PROMOTION_POLICY.md:97` | Prose figure | "34/36" baseline | — |

- The **"36-vector"** figure in the sprint brief and promotion policy is **unbacked** —
  no file enumerates the 36. The real BD1A doc lists ~77 codes.
- Three **incompatible id schemes** with **no reconciling table**.
- BD1A itself is **prose-only**; there is no machine-readable BD1A registry.

> **BACKLOG-GS21-0 (prerequisite for measurable coverage):** produce a single structured,
> id-reconciled BD1A registry (JSON/YAML) so GS-4.3 can compute per-vector block-rates
> against a stable id set. Until then, coverage is tracked at **phase** granularity below.

---

## 1. Crosswalk (phase granularity)

Legend — **Control (as-built):** ✅ enforced in code · 🟡 partial / detection-only /
pattern-only · ❌ not implemented (scaffold or absent). **RT:** red-team coverage in the
live runner (`tests/run_redteam.py`) — ✅ exercised · 🟡 pattern-only (tests the matcher,
not the real path) · ❌ absent.

| BD1A Phase | MS v2.0 failure mode | ATLAS | OWASP ASI | Control (as-built) — evidence | RT | Route |
|------------|----------------------|-------|-----------|-------------------------------|----|-------|
| **A** Data Exfiltration | Memory theft; System-prompt/knowledge extraction | T0024, T0056 | ASI03 | 🟡 Inbound only — SENT-004* (`sentinel.rs:9-75`) + Constitution "reveal system prompt" (`constitution.rs:112-114`). **No output-side disclosure filter / uniform-refusal.** | ✅ | **GS-4.1** (output filter, uniform refusal) |
| **B** Jailbreak | Agent compromise | T0053 | ASI01 | ✅ SENT-002/003* persona/DAN/hypothetical (`sentinel.rs:13-39`) | ✅ | covered |
| **C** Role Override | Agent impersonation | T0051 | ASI03 | ✅ SENT-002B/002C/009 authority spoof (`sentinel.rs`); A2A relay hard-stop (`abigail_hardened_enhanced.py:596`) | ✅ | covered (identity → GS-3.2) |
| **D** Command Execution | Tool compromise | T0050 | ASI02, ASI05 | 🟡 SENT-008* **detection** only; **no governed tool/MCP gateway, no least-privilege scoping, no egress allow-list** | ✅ | **GS-3.1** |
| **E** Indirect Injection (RAG/tool/doc) | Cross-domain prompt injection (XPIA) | T0054 | ASI06 | ❌ **SENT-009 cannot fire on retrieved content — retrieved content is never a gate input** (`pipeline.rs:162/297` take only user_input/model_output). No RAG path exists. | 🟡 | **GS-2.2** (+ GS-4.3 real-path test) |
| **F** Multi-turn Drift | HitL bypass; Agent flow manipulation | — | ASI01, ASI10 | 🟡 OverWatch drift/CRSV (`overwatch.rs:71-248`) + session memory; **no session-context-contamination anomaly surfacing** | ✅ | **GS-2.2** (session anomaly log) |
| **V** Evasion/Obfuscation | — | T0043 | — | ✅ Normalize + zero-width + homoglyph + l33t + base64 pre-scan (`sentinel.rs:127,138,185,207,212`); base64 in `corridor.rs:106-116` | ✅ | 🟡 GS-4.1 widens decode set |
| **G** Reconnaissance | — | T0000–T0002 | — | ❌ SENT-010* **defined in taxonomy, not implemented**; no rate/pattern monitor for probing / embedding-inversion signature | ✅ | **GS-2.3** |
| **H** Supply Chain (MCP/tool-desc/RAG-corpus/embedding-model) | Agent provisioning poisoning | T0010 | ASI04, ASI06 | ❌ SENT-011* defined, not implemented; **no signed tool/MCP manifests, no tool-description hidden-instruction scanner**; DEP.KEYSTONE covers code/model SBOM only | ❌ | **GS-3.1** |
| **I** Model Tampering | — | T0018, T0031 | — | 🟡 Claimed via L11 cert-tethering (referenced, not verified in this pass) | ❌ | **DEFER** — L11 / training-cert track; out of this series (see §2) |
| **J** Resource Exhaustion | Resource exhaustion | T0034, T0035 | ASI02 (loops) | 🟡 Cost Governor referenced in docs; **no hard, model-external loop/iteration ceiling** | ✅ | **GS-3.3** |
| **M** Hallucination Cascade | Hallucinations | — | ASI07 | ❌ SENT-014* defined, not implemented; grounding-bypass (M04) overlaps GS-2.2 semantic-consistency | ❌ | **DEFER** — needs its own scoping; partial overlap GS-2.2 (M04) |
| **N** Rogue Agent / Impersonation | Agent injection; Agent impersonation; Agent provisioning poisoning | — | ASI10 | 🟡 Pattern-match spoof detection blocks N-probes, **but no cryptographic inter-agent identity** on handoffs; Rust `crypto.rs` exists, Python packet signer is placeholder on main (`handoff_packet.py:88,111`) | ✅ (pattern) | **GS-3.2** |
| **O** Flow Manipulation | Agent flow manipulation; HitL bypass | — | — | ❌ SENT-016* defined, not implemented; **no code-level checkpoint enforcement / termination watchdog / loop guard** | ❌ | **GS-3.3** (loops) + **GS-3.1** (checkpoint) |
| **P** Multi-Agent Coordination | Multi-agent jailbreaks; XPIA | — | ASI01, ASI03 | 🟡 A2A relay detection (`abigail_hardened_enhanced.py:596`); SENT-017* defined; no cross-agent signal correlation / delegation-depth limit | ✅ | **GS-3.2** (identity) + GS-4.3 |
| **K** Cert Weaponization [PATENT] | — | ❌ | ❌ | 🟡 L11-CERT-* rules referenced (patent track) | ❌ | **DEFER** — patent/cert track, out of GOVSPINE-02..04 scope |
| **X** Emergent Capability Ambush [PATENT] | — | ❌ | ❌ | 🟡 L11-CBT-* rules referenced (patent track) | ❌ | **DEFER** — patent/cert track, out of scope |

### Controls not tied to a BD1A phase (from the sprint brief)

| Concern | MS v2.0 | OWASP ASI | Control (as-built) | Route |
|---------|---------|-----------|--------------------|-------|
| System-prompt/rule disclosure — **gradient refusals leak** | System-prompt extraction | ASI03 | ❌ no uniform-refusal output filter | **GS-4.1** |
| HAAP approval-fatigue flooding | HitL bypass (fatigue) | — | ❌ no anomaly detection on HAAP queue | **GS-4.2** |
| Per-layer measurable red-team coverage | — | — | 🟡 block-rate exists but manual, uncategorized-by-layer, not in CI | **GS-4.3** |
| Embedding-inversion / privacy probing | Privacy extraction | ASI03 | ❌ no store, no query-pattern monitor | **GS-2.3** (rescope — see GS-2.0 §7) |
| Poisoned long-term memory write | Memory poisoning | — | 🟡 write path exists (`pipeline.rs:340-350`), not durable, not gated | **GS-2.4** |

---

## 2. Backlog — every `no`/`partial` row is routed

**Sprint-02 (this sprint):**
- **GS-2.2** ← E (indirect injection), F (session contamination), + M04 grounding overlap.
  *Blocked-by:* no retrieval substrate (GS-2.0 §7 fork). Requires build-vs-harden decision.
- **GS-2.3** ← G (recon / embedding-inversion). *Rescope:* monitor govmem read API, no store.
- **GS-2.4** ← poisoned LT-memory write. *Partially actionable:* gate in-process carry-over.

**Sprint-03:**
- **GS-3.1** ← D (tool exec), H (supply chain / MCP / tool-desc poisoning), O (checkpoint).
- **GS-3.2** ← C/N/P inter-agent identity (reuse Rust `crypto.rs`; Python signer needs P0-4 merge).
- **GS-3.3** ← J (resource exhaustion), O (loop/termination).

**Sprint-04:**
- **GS-4.1** ← A (output-side disclosure, uniform refusal), V (widen decode/normalize set).
- **GS-4.2** ← HAAP approval-fatigue anomaly detection.
- **GS-4.3** ← red-team expansion + per-layer block-rate report + CI; converts every 🟡/❌
  RT cell above into a measured campaign. Requires **BACKLOG-GS21-0** (structured registry).

**Explicitly deferred (with reason):**
- **I** (Model Tampering), **K** / **X** (patent cert/emergent) — L11 / certification /
  patent track, out of the GOVSPINE-02..04 corrective scope.
- **M** (Hallucination Cascade) — matches the series' own out-of-scope posture; needs
  dedicated scoping (semantic analysis). Only M04 (grounding bypass) is partially picked
  up by GS-2.2's semantic-consistency check.
- Differential privacy / secure enclaves for the (future) vector store — research track,
  per the series' `explicitly_out_of_scope_this_series`.

---

## Verification (GS-2.1 exit criteria)

> *"Crosswalk table exists and every internal vector has a row."* — every BD1A phase
> (A–P, V, K, X) has a row in §1; phase granularity is used deliberately because no
> structured per-vector registry exists yet (BACKLOG-GS21-0, §0).

> *"Every 'no'/'partial' coverage row is referenced by a task_id in this sprint series or
> explicitly deferred with a reason."* — §2 routes every 🟡/❌ row to GS-2.2/2.3/2.4,
> GS-3.1/3.2/3.3, GS-4.1/4.2/4.3, or an explicit deferral (I, K, X, M, DP/enclaves).

---

*LOGOS Governance Systems Inc. — Internal Governance Doctrine*
