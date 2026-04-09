# LOGOS BD1A TAXONOMY v4.0
## Assault Classification System — LOGOS Governance Systems Inc.
## Classification: INTERNAL — DO NOT DISTRIBUTE

**Version:** 4.0-draft  
**Date:** 2026-02-28  
**Status:** Pre-filing — Not for public release  
**Codename:** BD1A  

---

> *"For we do not wrestle against flesh and blood, but against principalities, against powers..."*  
> — Ephesians 6:12

---

## TAXONOMY STRUCTURE

```
[PHASE][##] — Primary code
SENT-###[A-Z] — Sentinel detection rule
```

---

## PHASE INDEX (BD1A)

| Phase | Category | Tests | Status |
|-------|----------|-------|--------|
| A | Data Exfiltration | A01–A04 | ✅ Hardened |
| B | Jailbreak | B01–B04 | ✅ Hardened |
| C | Role Override | C01–C04 | ✅ Hardened |
| D | Command Execution | D01–D03 | ✅ Hardened |
| E | Indirect Injection | E01–E03 | ✅ Hardened |
| F | Multi-turn Drift | F01–F07 | ✅ Hardened |
| V | Evasion/Obfuscation | V01–V04 | ✅ Hardened |
| K | Certification Weaponization | K01–K06 | ✅ Patent 63/953,447 |
| X | Emergent Capability Ambush | X01–X05 | ✅ Patent 63/953,447 |
| G | Reconnaissance | G01–G05 | 🔶 NEW |
| H | Supply Chain | H01–H06 | 🔶 NEW |
| I | Model Tampering | I01–I04 | 🔶 NEW |
| J | Resource Exhaustion | J01–J04 | 🔶 NEW |
| M | Hallucination Cascade | M01–M04 | 🔶 NEW |
| N | Rogue Agent | N01–N05 | 🔶 NEW |
| O | Flow Manipulation | O01–O04 | 🔶 NEW |
| P | Multi-Agent Coordination | P01–P05 | 🔶 NEW |

**Total:** 106 existing + ~38 new = ~144 test cases

---

## EXISTING PHASES (A–F, V, K, X)

### Phase A: Data Exfiltration
**Intent:** Extract protected information from the system

| Code | Technique | SENT Rule | External Map |
|------|-----------|-----------|--------------|
| A01 | System prompt extraction | SENT-004 | AML.T0056, ASI03 |
| A02 | Configuration extraction | SENT-004D | AML.T0024 |
| A03 | Secrets/API key extraction | SENT-004F | AML.T0024, ASI03 |
| A04 | Memory dump request | SENT-004E | MS:Memory Theft |

### Phase B: Jailbreak
**Intent:** Bypass safety constraints through persona manipulation

| Code | Technique | SENT Rule | External Map |
|------|-----------|-----------|--------------|
| B01 | Persona hijack (DAN) | SENT-002 | AML.T0053, ASI01 |
| B02 | Inversion framing | SENT-003D | AML.T0053 |
| B03 | Fictional framing | SENT-003E | AML.T0053 |
| B04 | Hypothetical bypass | SENT-003G | AML.T0053, ASI01 |

### Phase C: Role Override
**Intent:** Claim unauthorized authority or identity

| Code | Technique | SENT Rule | External Map |
|------|-----------|-----------|--------------|
| C01 | New persona injection | SENT-002 | MS:Agent Impersonation |
| C02 | Admin/root claim | SENT-002B | ASI03 |
| C03 | Creator/developer claim | SENT-009 | ASI03 |
| C04 | SYSTEM role injection | SENT-002C | AML.T0051 |

### Phase D: Command Execution
**Intent:** Steer system toward executing unauthorized code

| Code | Technique | SENT Rule | External Map |
|------|-----------|-----------|--------------|
| D01 | Shell command steering | SENT-008E | ASI02, ASI05 |
| D02 | Python exec injection | SENT-008B | ASI05, MS:Tool Compromise |
| D03 | Tool call injection | SENT-008 | ASI02 |

### Phase E: Indirect Injection
**Intent:** Inject instructions via external data sources

| Code | Technique | SENT Rule | External Map |
|------|-----------|-----------|--------------|
| E01 | RAG poisoning | SENT-009 | AML.T0054, ASI06 |
| E02 | Tool output poisoning | SENT-009 | MS:XPIA |
| E03 | Email/document injection | SENT-009 | MS:XPIA, ASI06 |

### Phase F: Multi-turn Drift
**Intent:** Gradually escalate through conversation to bypass defenses

| Code | Technique | SENT Rule | External Map |
|------|-----------|-----------|--------------|
| F01 | Rapport building | — | MS:HitL Bypass |
| F02 | Research framing | — | — |
| F03 | Constraint discussion | — | — |
| F04 | Unconstrained framing | SENT-003G | ASI01 |
| F05 | Boundary testing | — | — |
| F06 | Drop framing | SENT-003F | MS:Agent Flow Manipulation |
| F07 | Explicit override | SENT-001G | ASI01, MS:Agent Compromise |

### Phase V: Evasion/Obfuscation
**Intent:** Bypass detection through encoding or transformation

| Code | Technique | SENT Rule | External Map |
|------|-----------|-----------|--------------|
| V01 | Base64 encoding | SENT-001 | AML.T0043 |
| V02 | L33tspeak | SENT-001 | AML.T0043 |
| V03 | Character spacing | SENT-001C | AML.T0043 |
| V04 | Zero-width Unicode | SENT-ZW-001 | AML.T0043 |

### Phase K: Certification Weaponization [PATENT 63/953,447]
**Intent:** Exploit certification process to launder malicious models

| Code | Technique | SENT Rule | External Map |
|------|-----------|-----------|--------------|
| K01 | Token replay attack | L11-CERT-001 | ❌ NONE |
| K02 | Post-certification mutation | L11-CERT-002 | ❌ NONE |
| K03 | Dual-model architecture | L11-CERT-003 | ❌ NONE |
| K04 | Behavioral signature forgery | L11-CERT-004 | ❌ NONE |
| K05 | Audit window exploitation | L11-CERT-005 | ❌ NONE |
| K06 | Certificate transfer attack | L11-CERT-006 | ❌ NONE |

### Phase X: Emergent Capability Ambush [PATENT 63/953,447]
**Intent:** Model evolves past governance boundary between audits

| Code | Technique | SENT Rule | External Map |
|------|-----------|-----------|--------------|
| X01 | Capability boundary violation | L11-CBT-001 | ❌ NONE |
| X02 | Canary evasion | L11-CBT-002 | ❌ NONE |
| X03 | Gradual capability emergence | L11-CBT-003 | ❌ NONE |
| X04 | Context-dependent capability hiding | L11-CBT-004 | ❌ NONE |
| X05 | Multi-hop reasoning emergence | L11-CBT-005 | ❌ NONE |

---

## NEW PHASES (G–P)

### Phase G: Reconnaissance
**Intent:** Gather information about the AI system to plan attacks

| Code | Technique | Description | SENT Rule | External Map |
|------|-----------|-------------|-----------|--------------|
| G01 | Model identification | Probe to identify model family/version | SENT-010A | AML.T0000 |
| G02 | Capability probing | Test for specific capabilities | SENT-010B | AML.T0001 |
| G03 | Guardrail mapping | Systematically probe for policy boundaries | SENT-010C | AML.T0002 |
| G04 | Tool enumeration | Discover available tools/functions | SENT-010D | AML.T0001 |
| G05 | Rate limit probing | Test for rate limits and quotas | SENT-010E | AML.T0002 |

**Detection Strategy:**
- Pattern: Systematic probing behavior across sessions
- Signal: High-frequency boundary testing
- Defense: Session fingerprinting, probe pattern detection

---

### Phase H: Supply Chain
**Intent:** Compromise dependencies, packages, or integration points

| Code | Technique | Description | SENT Rule | External Map |
|------|-----------|-------------|-----------|--------------|
| H01 | MCP server poisoning | Malicious MCP server injection | SENT-011A | ASI04 |
| H02 | Package dependency attack | Compromised pip/npm packages | SENT-011B | AML.T0010 |
| H03 | RAG corpus poisoning | Poison knowledge base at source | SENT-011C | ASI04, ASI06 |
| H04 | Tool definition manipulation | Modify tool schemas/descriptions | SENT-011D | ASI04 |
| H05 | Adapter/LoRA injection | Malicious fine-tuning adapters | SENT-011E | AML.T0010 |
| H06 | Embedding model compromise | Poisoned embedding model | SENT-011F | AML.T0010 |

**Detection Strategy:**
- Pattern: Hash verification failures, unexpected tool behavior
- Signal: Behavioral delta after dependency update
- Defense: Supply chain attestation, SBOM verification

---

### Phase I: Model Tampering
**Intent:** Modify model weights, behavior, or outputs post-deployment

| Code | Technique | Description | SENT Rule | External Map |
|------|-----------|-------------|-----------|--------------|
| I01 | Weight modification | Direct manipulation of model parameters | SENT-012A | AML.T0018 |
| I02 | Unauthorized fine-tuning | Fine-tuning without re-certification | SENT-012B | AML.T0031 |
| I03 | Inference-time manipulation | Modify outputs during inference | SENT-012C | AML.T0031 |
| I04 | Model merge attack | Merge safe model with unsafe model | SENT-012D | AML.T0018 |

**Detection Strategy:**
- Pattern: Behavioral fingerprint drift without authorized update
- Signal: L11 behavioral delta engine alert
- Defense: Continuous certification tethering (Vector K defense)

---

### Phase J: Resource Exhaustion
**Intent:** Drain compute, tokens, or financial resources

| Code | Technique | Description | SENT Rule | External Map |
|------|-----------|-------------|-----------|--------------|
| J01 | Token drain attack | Craft prompts maximizing token consumption | SENT-013A | AML.T0034 |
| J02 | Recursive expansion | Trigger recursive or exponential processing | SENT-013B | AML.T0035 |
| J03 | Tool loop exploitation | Create infinite tool call loops | SENT-013C | AML.T0035, ASI02 |
| J04 | Context window stuffing | Fill context to degrade performance | SENT-013D | AML.T0034 |

**Detection Strategy:**
- Pattern: Abnormal resource consumption patterns
- Signal: Cost anomaly, latency spike, token velocity
- Defense: Rate limiting, circuit breakers, cost caps

---

### Phase M: Hallucination Cascade
**Intent:** Trigger hallucinations that propagate through multi-agent systems

| Code | Technique | Description | SENT Rule | External Map |
|------|-----------|-------------|-----------|--------------|
| M01 | Confidence manipulation | Induce high-confidence hallucinations | SENT-014A | ASI07 |
| M02 | Citation fabrication | Generate fake but plausible citations | SENT-014B | ASI07 |
| M03 | Cross-agent hallucination propagation | Hallucination spreads agent-to-agent | SENT-014C | ASI07, MS:Hallucinations |
| M04 | Grounding bypass | Circumvent RAG grounding checks | SENT-014D | ASI07 |

**Detection Strategy:**
- Pattern: Unverifiable claims with high confidence scores
- Signal: Citation verification failure, cross-agent inconsistency
- Defense: Hallucination markers, grounding verification, source attestation

---

### Phase N: Rogue Agent
**Intent:** Inject, impersonate, or subvert agents in multi-agent systems

| Code | Technique | Description | SENT Rule | External Map |
|------|-----------|-------------|-----------|--------------|
| N01 | Agent injection | Insert unauthorized agent into system | SENT-015A | MS:Agent Injection, ASI10 |
| N02 | Agent impersonation | Masquerade as legitimate agent | SENT-015B | MS:Agent Impersonation |
| N03 | Agent credential theft | Steal agent authentication tokens | SENT-015C | ASI03 |
| N04 | Sleeper agent activation | Dormant malicious behavior triggered by condition | SENT-015D | ASI10 |
| N05 | Agent provisioning hijack | Compromise agent creation pipeline | SENT-015E | MS:Agent Provisioning Poisoning |

**Detection Strategy:**
- Pattern: Unregistered agent IDs, behavioral anomalies
- Signal: Agent authentication failures, unexpected agent-to-agent communication
- Defense: Agent registry, mTLS between agents, behavioral baselining

---

### Phase O: Flow Manipulation
**Intent:** Subvert the control flow of agentic workflows

| Code | Technique | Description | SENT Rule | External Map |
|------|-----------|-------------|-----------|--------------|
| O01 | Routing subversion | Redirect agent workflow to malicious path | SENT-016A | MS:Agent Flow Manipulation |
| O02 | Checkpoint bypass | Skip security checkpoints in workflow | SENT-016B | MS:HitL Bypass |
| O03 | Loop injection | Insert infinite or malicious loops | SENT-016C | MS:Agent Flow Manipulation |
| O04 | Termination suppression | Prevent workflow from completing/stopping | SENT-016D | MS:Agent Flow Manipulation |

**Detection Strategy:**
- Pattern: Unexpected flow graph deviations
- Signal: Checkpoint miss, loop detection, termination failure
- Defense: Deterministic flow control, checkpoint enforcement, watchdog timers

---

### Phase P: Multi-Agent Coordination Attack
**Intent:** Exploit multi-agent coordination to achieve malicious outcomes

| Code | Technique | Description | SENT Rule | External Map |
|------|-----------|-------------|-----------|--------------|
| P01 | Consensus manipulation | Influence voting/consensus mechanisms | SENT-017A | MS:Multi-Agent Jailbreaks |
| P02 | Distributed jailbreak | Split jailbreak across multiple agents | SENT-017B | MS:Multi-Agent Jailbreaks |
| P03 | Swarm coordination attack | Coordinate multiple agents for amplified effect | SENT-017C | — |
| P04 | Inter-agent prompt injection | Inject instructions via agent-to-agent messages | SENT-017D | ASI01, MS:XPIA |
| P05 | Delegation chain exploitation | Exploit trust in delegation hierarchies | SENT-017E | ASI03 |

**Detection Strategy:**
- Pattern: Coordinated anomalous behavior across agents
- Signal: Consensus anomaly, distributed pattern matching
- Defense: Agent isolation, delegation depth limits, cross-agent signal correlation

---

## SENT RULE ALLOCATION

### Existing Rules (L1–L10)
```
SENT-001 — SENT-009:  Injection, jailbreak, extraction, authority spoofing
SENT-00X[A-G]:        Variants and sub-rules
SENT-ZW-001:          Zero-width character detection
SENT-HG-001:          Homoglyph detection
SENT-ENC-00X:         Encoding anomalies
SENT-BL-00X:          Blocklist patterns
SENT-SIZE-001:        Size limits
```

### New Rules (Phases G–P)
```
SENT-010[A-E]:  Reconnaissance (G01–G05)
SENT-011[A-F]:  Supply Chain (H01–H06)
SENT-012[A-D]:  Model Tampering (I01–I04)
SENT-013[A-D]:  Resource Exhaustion (J01–J04)
SENT-014[A-D]:  Hallucination Cascade (M01–M04)
SENT-015[A-E]:  Rogue Agent (N01–N05)
SENT-016[A-D]:  Flow Manipulation (O01–O04)
SENT-017[A-E]:  Multi-Agent Coordination (P01–P05)
```

### Layer 11 Rules (K, X)
```
L11-CERT-00X:  Certification Weaponization (K01–K06)
L11-CBT-00X:   Capability Boundary Telemetry (X01–X05)
```

---

## EXTERNAL TAXONOMY CROSSWALK

### Coverage Matrix

| Arcanum Phase | MITRE ATLAS | OWASP ASI | MS AIRT | SAGE-RT |
|---------------|-------------|-----------|---------|---------|
| A (Exfiltration) | AML.T0024, T0056 | ASI03 | Memory Theft | Privacy |
| B (Jailbreak) | AML.T0053 | ASI01 | Agent Compromise | Agent Behavior |
| C (Role Override) | AML.T0051 | ASI03 | Agent Impersonation | Governance |
| D (Command Exec) | AML.T0050 | ASI02, ASI05 | Tool Compromise | Security |
| E (Indirect Inj) | AML.T0054 | ASI06 | XPIA | Integrity |
| F (Multi-turn) | — | ASI01, ASI10 | HitL Bypass, Flow Manip | Agent Behavior |
| V (Evasion) | AML.T0043 | — | — | Security |
| K (Cert Weapon) | ❌ NONE | ❌ NONE | ❌ NONE | ❌ NONE |
| X (Emergent Cap) | ❌ NONE | ❌ NONE | ❌ NONE | ❌ NONE |
| G (Recon) | AML.T0000–T0002 | — | — | Security |
| H (Supply Chain) | AML.T0010 | ASI04 | Agent Prov Poison | Governance |
| I (Tampering) | AML.T0018, T0031 | — | — | Integrity |
| J (Resource) | AML.T0034, T0035 | — | Resource Exhaust | Availability |
| M (Hallucination) | — | ASI07 | Hallucinations | Integrity |
| N (Rogue Agent) | — | ASI10 | Agent Injection | Agent Behavior |
| O (Flow Manip) | — | — | Agent Flow Manip | Governance |
| P (Multi-Agent) | — | — | Multi-Agent Jailbreak | Agent Behavior |

---

## IMPLEMENTATION PRIORITY

### Wave 1 (Immediate — Strengthen Core)
- [ ] G01–G05: Reconnaissance detection
- [ ] J01–J04: Resource exhaustion (cost protection)

### Wave 2 (Near-term — Multi-Agent)
- [ ] N01–N05: Rogue agent detection
- [ ] O01–O04: Flow manipulation defense
- [ ] P01–P05: Multi-agent coordination

### Wave 3 (Medium-term — Supply Chain)
- [ ] H01–H06: Supply chain integrity
- [ ] I01–I04: Model tampering (integrate with L11)

### Wave 4 (Long-term — Hallucination)
- [ ] M01–M04: Hallucination cascade (requires semantic analysis)

---

## DOCUMENT CONTROL

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| 4.0-draft | 2026-02-28 | LOGOS | Initial G–P definition |

---

*LOGOS Governance Systems Inc. — Proprietary*  
*US Provisional Patent No. 63/953,447 (Vectors K, X)*  
*DO NOT DISTRIBUTE*
