# Tacit Swarm Activation Phases
**Status:** DOCTRINE_ONLY  
**Classification:** INTERNAL — ARCHITECTURE  
**Owner:** CP-00 (Abigail Constitutional Authority)

---

## Overview

The Tacit Knowledge Reconnaissance Swarm activates in phases. Each phase requires operator authorization before implementation. No phase authorizes runtime activation of agents unless explicitly stated here.

This document defines the authorization state of each phase as of the current sprint.

---

## Phase 1 — Doctrine and Pre-Pass Architecture
**Status: AUTHORIZED — this task**  
**Commit scope:** Doctrine files only  
**Runtime activation:** NOT AUTHORIZED  

Deliverables:
- `PREPASS_ROUTING.md` — pre-pass contract, routing table, behavior by request class
- `TACIT_CONTEXT_CARD.schema.json` — Tacit Context Card output schema
- `ACTIVATION_PHASES.md` — this document

What is NOT authorized in Phase 1:
- Wiring the pre-pass into Abigail's request handler
- Registering TKR/EIR agents in the live agent loader
- Calling TKR/EIR agents from any runtime path
- Writing pre-pass output to Store 1 or Store 2

---

## Phase 2 — Agent Manifest and Placeholder Registration
**Status: NOT YET AUTHORIZED**  
**Requires:** Operator authorization + separate task

Deliverables:
- `agents/tacit_knowledge_reconnaissance/` directory
- TKR Director YAML (`tkr_dir.yaml`) — marked inactive
- EIR Director YAML (`eir_dir.yaml`) — marked inactive
- TKR-01 YAML (elicitation agent) — marked inactive + restricted
- TKR-02 YAML (artifact agent) — marked inactive
- EIR-01 YAML (external lookup agent) — marked inactive
- EIR-02 YAML (triangulation agent) — marked inactive
- Department manifest (`tkr_department.yaml`)

All YAMLs in Phase 2 are `status: INACTIVE` and cannot be invoked by the agent loader until Phase 3.

---

## Phase 3 — Runtime Routing Patch (Abigail Integration)
**Status: NOT YET AUTHORIZED**  
**Requires:** Phase 2 complete + separate operator-authorized task (Tacit Swarm Phase 2 Runtime Routing Patch)

Deliverables:
- Patch to `abigail_hardened_enhanced.py` or equivalent to invoke pre-pass before response planning
- Pre-pass invocation produces Tacit Context Card and passes it to response planner
- Card is ephemeral by default; Store 2 eligibility requires Phase 4 authorization
- TKR Director activated in classify-only mode (minimal tier)
- EIR Director activated for job_request class only

Governance requirements for Phase 3:
- Pre-pass must complete before Sentinel verdict expires
- Card must not override any Sentinel/OverWatch/HAAP-X verdict
- Pre-pass failure must fail open to direct Abigail response (no blocking on pre-pass timeout)
- Latency SLA: < 500ms; breach → fallback to minimal card with confidence 0.0

---

## Phase 4 — Store 2 Eligibility and GovMem Integration
**Status: NOT YET AUTHORIZED**  
**Requires:** Phase 3 stable + separate operator-authorized task

Deliverables:
- Pre-pass cards marked `store2_eligible` are batched and ingested by GovMem v2 loader
- Card patterns feed Store 2 analysis (not Store 1)
- Store 1 promotion remains prohibited from pre-pass path

---

## Phase 5 — Full Swarm Activation (TKR-01 Elicitation)
**Status: NOT YET AUTHORIZED**  
**Requires:** Phases 3–4 complete + explicit operator authorization per use case

TKR-01 (human elicitation agent) requires:
- Explicit operator authorization for each elicitation session
- Defined scope: what to elicit, from whom, for how long
- No persistent memory without Store 1 promotion authorization
- No coercive, deceptive, or surveillance-adjacent collection

TKR-01 is NEVER invoked by the automatic pre-pass. It is always operator-initiated.

---

## Agent Authorization Summary

| Agent ID | Name | Phase | Auto Pre-Pass | Requires |
|---|---|---|---|---|
| TKR-DIR | Tacit Knowledge Reconnaissance Director | Phase 3 | YES (minimal/lightweight) | Phase 3 authorized |
| EIR-DIR | Ethical Intelligence Reconnaissance Director | Phase 3 | YES (job_request only) | Phase 3 authorized |
| TKR-01 | Human Elicitation Agent | Phase 5 | **NEVER** | Explicit operator auth per session |
| TKR-02 | Artifact/File Reconnaissance Agent | Phase 3 | Conditional (technical_task) | Phase 3 + artifact in scope |
| EIR-01 | External Lookup Agent | Phase 3 | Conditional (job_request) | Phase 3 + EIR authorization |
| EIR-02 | Triangulation/Risk Ranking Agent | Phase 4 | Conditional | Phase 4 + both signals present |

---

## Governing Constraints (All Phases)

The following constraints apply regardless of phase:

1. **Sentinel/OverWatch/HAAP-X are always authoritative.** No tacit agent invocation before the gate clears.
2. **Store 1 is never mutated from the pre-pass path.** Store 1 promotion requires separate Store 1 apply authorization.
3. **TKR-01 is never automatic.** Human elicitation requires explicit per-session operator authorization.
4. **Collection requires defined scope.** Tacit agents may not collect, surveil, or mine beyond what the request scope explicitly authorizes.
5. **Pre-pass failure is non-blocking.** If the pre-pass times out or errors, Abigail responds directly with minimal framing. The pre-pass is an interpretive aid, not a gate.
6. **Cards are ephemeral by default.** No card persists beyond the turn unless Store 2 authorization is separately granted.
7. **Abigail does not invent external data.** Job listings, current events, market prices — any data requiring a current source must come from EIR-01 external lookup, not from tacit inference.
