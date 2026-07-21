# Tacit Knowledge Reconnaissance Swarm — Agent Manifest
**Status:** INACTIVE STUBS — Phase 2 only  
**Classification:** INTERNAL — ARCHITECTURE  
**Runtime activation:** NOT AUTHORIZED (requires Phase 3 operator task)  
**Phase 1 doctrine:** `docs/agents/tacit-knowledge/`

---

## Critical: Why These Files Are Not Runtime-Loaded

The `agent_loader.py` loads any `*.yaml` in the `agents/` tree that has an `agent:` root key. **Every stub in this directory uses `inactive_agent_stub:` as the root key instead.** The loader skips them entirely — they cannot be dispatched, invoked, or accessed at runtime until Phase 3 converts them to active `agent:` entries.

This is intentional. These stubs define the swarm inventory without activating any execution path.

---

## Agent Inventory

| File | Agent ID | Role | Phase Required | Auto Pre-Pass |
|------|----------|------|---------------|---------------|
| `tkr_dir.yaml` | TKR-DIR | TKR Parent Director | Phase 3 | YES (all classes) |
| `eir_dir.yaml` | EIR-DIR | EIR Parent Director | Phase 3 | YES (job_request only) |
| `tkr_01_interview_elicitation.yaml` | TKR-01-INTERVIEW | Sub — elicitation | Phase 5 + per-session auth | **NEVER** |
| `tkr_02_workflow_artifact_mining.yaml` | TKR-02-ARTIFACT | Sub — artifact mining | Phase 3 (conditional) | Conditional |
| `eir_01_public_signal_mapping.yaml` | EIR-01-PUBLIC | Sub — public lookup | Phase 3 (conditional) | Conditional |
| `eir_02_pattern_triangulation_risk.yaml` | EIR-02-TRIANGULATION | Sub — triangulation | Phase 4 | Conditional |

---

## Authorization Gate Summary

| Phase | What Is Authorized |
|-------|--------------------|
| Phase 1 (current) | Doctrine and schema only (`docs/agents/tacit-knowledge/`) |
| Phase 2 (this task) | Inactive YAML stubs — inventory only, no execution |
| Phase 3 (not yet) | Runtime pre-pass wiring in Abigail request handler; TKR-DIR + EIR-DIR activate |
| Phase 4 (not yet) | Store 2 eligibility; EIR-02 activates |
| Phase 5 (not yet) | TKR-01 registered (still requires per-session operator auth every use) |

---

## Governing Constraints (All Stubs)

All agents in this swarm are bound by the following constraints, which must be enforced at Phase 3 runtime wiring:

1. **Sentinel/OverWatch/HAAP-X are always authoritative.** No pre-pass agent runs before the gate clears.
2. **Store 1 is never mutated from the pre-pass path.** `store1_mutation: false` in every stub.
3. **TKR-01 is never automatic.** It is always operator-authorized per session, listed in `forbidden_agents` of every auto-generated Tacit Context Card.
4. **EIR-01 requires EIR-DIR scope per turn.** It does not auto-invoke for job requests — EIR-DIR must authorize it.
5. **Pre-pass failure is non-blocking.** If any agent times out or errors, Abigail responds directly.
6. **Cards are ephemeral by default.** No card persists beyond the turn without Store 2 authorization.
7. **Abigail decides.** Tacit agents interpret and frame; they do not make decisions or override Abigail's response planning.

---

## Prohibited Actions (All Stubs)

- Coercive, deceptive, or manipulative elicitation
- Surveillance or monitoring without subject consent
- Identity resolution or non-public data collection
- Doxxing or unauthorized personal data use
- Store 1 mutation from any pre-pass path
- Fabrication of job listings, market signals, or external data
- Override of Sentinel/OverWatch/HAAP-X verdicts

---

## Next Step: Phase 3 — Runtime Routing Patch

Phase 3 wires TKR-DIR into `abigail_hardened_enhanced.py` (or equivalent) as an always-on pre-pass before response planning. Requires separate operator-authorized task: **"Tacit Swarm Phase 3 Runtime Routing Patch."**

Phase 3 converts `tkr_dir.yaml` and `eir_dir.yaml` from `inactive_agent_stub:` to `agent:` root keys and registers them in the loader. All other stubs remain inactive until their respective phases.
