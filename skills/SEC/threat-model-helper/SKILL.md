---
name: threat-model-helper
description: Draft a lightweight STRIDE-style threat model for a supplied design or feature — assets, entry points, threats, and mitigations. Advisory only. Trigger on "threat model this", "what could go wrong security-wise", "STRIDE for this design".
department: SEC
department_id: DEPT-SEC
authority_level: advisory
risk_level: low
source: first-party
license: proprietary
allowed_actions:
  - read_provided_design
  - produce_threat_model_text
  - suggest_mitigations
forbidden_actions:
  - scan_networks_or_systems
  - execute_code_or_shell
  - modify_files
  - grant_authority
  - expose_secrets
inputs:
  - a design/feature/architecture description or diagram-in-text
outputs:
  - assets, trust boundaries, entry points, STRIDE threats, and mitigations as text
activation_examples:
  - "threat model this feature"
  - "STRIDE analysis for this design"
  - "what are the security risks of this architecture"
negative_activation_examples:
  - "scan this host"
  - "run an exploit"
  - "pentest the live server"
  - "show me the admin token"
---

## Purpose
Produce an advisory, text-only threat model for a supplied design so the team can
prioritize mitigations. No scanning, no execution, no live-system interaction.

## When to Use
- A design/feature/architecture is described and the user wants structured threat analysis.

## When Not to Use
- The request is to **scan, exploit, or pentest** any system (out of scope — refuse).
- No design is provided.

## Inputs
- Design/architecture description in the request. Nothing read from disk/network; no scanning.

## Outputs
- Assets, trust boundaries, entry points; threats mapped to STRIDE; prioritized mitigations.

## Governance Rules
- **Advisory only.** Never scans, exploits, executes, or modifies anything.
- Abigail backend gates (Sentinel, HAAP, MM-03, SEC-02 cost, audit) remain authoritative and
  must not be weakened by any mitigation suggestion.
- Default plan/review mode; any implementation goes through existing governance.
- Never expose or request secrets/credentials; never propose disabling governance controls.

## Procedure
1. Identify assets, actors, trust boundaries, and entry points from the description.
2. Enumerate threats per STRIDE (Spoofing, Tampering, Repudiation, Info-disclosure, DoS, Elevation).
3. Propose mitigations; mark which need SEC/GRC review.
4. State assumptions and residual risk.

## Audit Requirements
- Record activation with gov_tx_id, skill, department; log a safe summary (threat counts) only.

## Tests
- Output maps at least one concrete threat to each relevant STRIDE category with a mitigation.
- A scan/exploit request is refused, not fulfilled.
