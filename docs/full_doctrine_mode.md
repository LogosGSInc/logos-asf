# Full Doctrine Mode – Exit Criteria

**Definition:** Full doctrine mode exists when a single signed constitutional source governs all enforcement layers, session memory can impose posture floors in Arbiter, every turn feeds memory, every terminal decision is hash-chained and signed, each service has a defined role and contract, and the entire topology boots fail-closed via one command.

## 1. Single constitutional source
- [ ] A canonical, signed constitutional document exists (JSON/YAML), with:
  - client_id, policy_version, industry_profile
  - prohibited_categories, prohibited_patterns, required_deferrals
  - escalation thresholds, tone constraints, tool permissions
  - constitutional_hash (sealed at deployment)
- [ ] Constitution is integrity-verified at startup in:
  - Rust governance spine (ConstitutionalEvaluator)
  - OverWatch SOP config (when present)
  - Abby’s output-policy layer (live + demo modes)
- [ ] No policy is edited directly in code; all enforcement thresholds and SOPs are derived from this source.

## 2. Memory authority in Arbiter
- [ ] Arbiter consumes MemoryVerdict.threshold_modifier on every decision (scalar tightening).
- [ ] Arbiter applies memory posture floors:
  - Clear, Watching → no floor
  - Elevated → minimum S2 (Restrict)
  - Escalated → minimum S3 (Quarantine)
  - Locked → immediate S4 (Hard Lock)
- [ ] modifier is clamped to a safe range (e.g., 0.5–1.0) to prevent bug-driven behavior.
- [ ] Tests show that a warmed hostile session yields a harsher outcome than the same fourth prompt in a clean session.

## 3. Pipeline → Memory on every turn
- [ ] Pipeline classifies every inbound signal and calls SessionMemory::ingest_signal before Arbiter decides.
- [ ] At minimum, these classes feed memory as trajectory-bearing:
  - AuthorityClaim
  - PolicyOverrideAttempt (or equivalent)
  - Extraction
  - Obfuscated / Encoding tricks
- [ ] Memory verdict is retrieved for the session and passed into Arbiter on the same turn.
- [ ] Normal traffic is tested to ensure no pathological over-escalation.

## 4. Audit on every terminal decision
- [ ] All EnforcementResult branches go through a single record_and_return(...) helper in Arbiter.
- [ ] For every Approved, Restricted, Quarantined, HardLocked, HaapGated decision:
  - An AuditEntry is created
  - prev_chain_hash / current_chain_hash are updated via CryptoEngine::extend_chain
  - The decision is signed
- [ ] No early returns bypass audit.
- [ ] At least one red-team run shows a non-zero audit chain length and consistent hash chaining.

## 5. Explicit service roles
- [ ] Sentinel – outer cordon, L1 gate, surface detection.
- [ ] Corridor – stateless policy corridor, rule & score engine.
- [ ] Arbiter – sole owner of Global Security State (S1–S4), deterministic enforcement.
- [ ] OverWatch – constitutional intelligence monitor.
- [ ] OIM – monitors OverWatch for drift/integrity.
- [ ] Abigail – constitutional authority for user-facing orchestration.

## 6. Signed signal contracts between services
- [ ] Inter-service schema includes:
  - event_id, session_id
  - source
  - severity, confidence
  - violation_class or rule_id
  - recommended_state
  - policy_version
  - timestamp
  - signature
- [ ] Arbiter decisions rely only on structured, signed inputs.

## 7. Health-gated startup (fail-closed)
- [ ] Each doctrine role exposes a health endpoint.
- [ ] docker compose uses healthy dependency ordering before Abby starts.
- [ ] If enforcement path is degraded, Abby never serves ungoverned answers.

## 8. One-click doctrine topology
- [ ] docker compose up --build starts doctrine services with the same policy_version injected.
- [ ] Abby live and demo routes go only through Sentinel/Arbiter pipeline.
- [ ] Red-team harness targets only the doctrine path.
- [ ] Red-team run improves block/quarantine/hardlock rate and produces signed audit evidence.
