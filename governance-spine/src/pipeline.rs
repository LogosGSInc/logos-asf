use crate::{
    sentinel::Sentinel,
    corridor::Corridor,
    overwatch::{OverWatch, OverWatchConfig},
    oim::OIM,
    arbiter::{Arbiter, ArbiterConfig, SecurityState},
    crypto::CryptoEngine,
    constitution::{Constitution, ConstitutionalEvaluator},
    governance_signal::{Direction, Severity, GovernanceSignal, SignalSource, SignalBuilder},
    session_memory::{
        SessionMemory, StrategicMemory, MemoryConfig, MemoryVerdict,
        MemoryState, classify_payload,
    },
    govmem::{GovMem, GovMemMode, MessageDirection},
    haap::{HaapGate, HaapConfig, HaapVerdict, AgencyLevel},
};
use parking_lot::RwLock;
use std::collections::HashMap;
use std::sync::Arc;

/// Enforcement result returned to caller after pipeline evaluation.
#[derive(Debug, Clone)]
pub enum EnforcementResult {
    /// Request/response approved — proceed normally
    Approved(String),
    /// Session is in S2 — proceed with restrictions applied
    /// Caller must apply capability restrictions
    Restricted(String, RestrictionsApplied),
    /// Session in S3 — replace with safe fallback, flag for human review
    Quarantined(String),
    /// Session in S4 — terminate, notify operator
    HardLocked(String),
    /// HAAP gate — action requires human authorization before proceeding
    /// Caller must obtain Intent Token from Human Principal and retry
    HaapGated {
        reason: String,
        agency: AgencyLevel,
        drs: u8,
    },
}

#[derive(Debug, Clone)]
pub struct RestrictionsApplied {
    pub tool_calls_disabled: bool,
    pub response_depth_limited: bool,
    pub enhanced_logging: bool,
}

pub struct GovernancePipeline {
    sentinel: Sentinel,
    corridor: Corridor,
    overwatch: Arc<RwLock<OverWatch>>,
    oim: Arc<RwLock<OIM>>,
    arbiter: Arc<Arbiter>,
    crypto: Arc<CryptoEngine>,
    constitutional_evaluator: Option<Arc<ConstitutionalEvaluator>>,

    // ── HAAP GATE (between L4 OverWatch and OIM) ───────────────────
    haap: Arc<HaapGate>,

    // ── ANTI-ALZHEIMER'S LAYER ─────────────────────────────────────
    /// Tier 1: Per-session tactical memory (Sentinel gate)
    session_memories: Arc<RwLock<HashMap<String, SessionMemory>>>,
    /// Tier 2: Cross-session strategic memory (Abigail meta-cognition)
    strategic_memory: Arc<RwLock<StrategicMemory>>,
    /// Memory accumulator configuration
    memory_config: MemoryConfig,

    /// GovMem V2: RL-enhanced multi-turn detection
    govmem: Arc<GovMem>,
}

impl GovernancePipeline {
    pub fn new(
        arbiter_config: ArbiterConfig,
        constitution: Option<Constitution>,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let crypto = Arc::new(CryptoEngine::new("logos_governance_v1_seed"));

        let sentinel = Sentinel::new(crypto.clone());
        let corridor = Corridor::new(crypto.clone());

        let overwatch_config = OverWatchConfig {
            drift_threshold: 0.65,
            session_turn_limit: 200,
            client_model_api: None,
        };

        let overwatch = Arc::new(RwLock::new(
            OverWatch::new(crypto.clone(), overwatch_config)
        ));

        let oim = Arc::new(RwLock::new(OIM::new(crypto.clone())));
        let arbiter = Arc::new(Arbiter::new(arbiter_config, crypto.clone()));
        let haap = Arc::new(HaapGate::new(HaapConfig::default(), crypto.clone()));

        let constitutional_evaluator = constitution
            .map(ConstitutionalEvaluator::new)
            .transpose()?
            .map(Arc::new);

        Ok(Self {

        // Initialize GovMem based on env var
        let govmem_mode = std::env::var("GOVMEM_MODE")
            .unwrap_or_else(|_| "v1".to_string());
        let mode = match govmem_mode.to_lowercase().as_str() {
            "v2" => GovMemMode::V2,
            _ => GovMemMode::V1,
        };
        let govmem = Arc::new(GovMem::new(mode));
            sentinel,
            corridor,
            overwatch,
            oim,
            arbiter,
            crypto,
            constitutional_evaluator,
            haap,
            session_memories: Arc::new(RwLock::new(HashMap::new())),
            strategic_memory: Arc::new(RwLock::new(StrategicMemory::new())),
            memory_config: MemoryConfig::default(),
            govmem,
        })
    }

    /// Default pipeline — consumer profile, no constitution
    pub fn default_pipeline() -> Result<Self, Box<dyn std::error::Error>> {
        Self::new(ArbiterConfig::default(), None)
    }

    /// Medical-grade pipeline with sealed constitution
    pub fn medical_pipeline() -> Result<Self, Box<dyn std::error::Error>> {
        let constitution = Constitution::default_medical();
        Self::new(ArbiterConfig::medical(), Some(constitution))
    }

    /// INBOUND: Memory-aware pipeline
    ///
    /// Flow:
    ///   [Abigail] advise_session_start → initial memory state
    ///   L1: Sentinel → Arbiter (with threshold modifier)
    ///   L2: Corridor → Arbiter (with threshold modifier)
    ///   L4: OverWatch → Arbiter (with threshold modifier)
    ///   OIM: observe → Arbiter
    ///   [SessionMemory] ingest highest-severity signal → accumulate
    ///   if memory.force_checkpoint → override to at least S2
    pub fn inbound(&self, user_input: &str, session_id: &str) -> EnforcementResult {
        // ── STEP 0: Initialize session memory if new ───────────────
        let threshold_modifier = self.init_session_memory(session_id);

        // ── STEP 1: Classify payload for memory accumulator ────────
        let classification = classify_payload(user_input);

        // ── STEP 2: Run pipeline layers, tracking highest signal ───
        let mut highest_signal: Option<GovernanceSignal> = None;

        // L1: Sentinel surface detection
        let s_signal = self.sentinel.inspect(user_input, Direction::Inbound, session_id);

        // GovMem V2: Record turn and Sentinel signal
        self.govmem.record_turn(
            session_id,
            user_input,
            MessageDirection::UserToSystem,
            s_signal.severity >= Severity::High,
            None, // department_id
            None, // agent_id
        );
        self.govmem.record_layer_signal(session_id, "sentinel", &s_signal);
        self.track_highest(&s_signal, &mut highest_signal);
        let state = self.arbiter.process_with_modifier(&s_signal, threshold_modifier);
        if let Some(result) = self.check_hard_block(&state, "L1-Sentinel", session_id) {
            self.ingest_to_memory(session_id, &highest_signal, &classification);
            return result;
        }

        // L2: Corridor policy engine + constitutional evaluation
        let evaluator_ref = self.constitutional_evaluator.as_deref();
        let c_signal = self.corridor.evaluate(
            user_input, Direction::Inbound, session_id, evaluator_ref,
        );
        self.govmem.record_layer_signal(session_id, "corridor_in", &c_signal);
        self.track_highest(&c_signal, &mut highest_signal);
        let state = self.arbiter.process_with_modifier(&c_signal, threshold_modifier);
        if let Some(result) = self.check_hard_block(&state, "L2-Corridor", session_id) {
            self.ingest_to_memory(session_id, &highest_signal, &classification);
            return result;
        }

        // L4: OverWatch behavioral intelligence
        let ow_signal = {
            let overwatch = self.overwatch.read();
            overwatch.evaluate(user_input, Direction::Inbound, session_id)
        )
        self.govmem.record_layer_signal(session_id, "overwatch", &ow_signal);

        // GovMem V2: Check drift (multi-turn detection)
        if self.govmem.should_block(session_id, None) {
            self.ingest_to_memory(session_id, &highest_signal, &classification);
            return EnforcementResult::Quarantined("GOVMEM-DRIFT-DETECTED".to_string());
        }
        };
        self.track_highest(&ow_signal, &mut highest_signal);
        let state = self.arbiter.process_with_modifier(&ow_signal, threshold_modifier);
        if let Some(result) = self.check_hard_block(&state, "L4-OverWatch", session_id) {
            self.ingest_to_memory(session_id, &highest_signal, &classification);
            return result;
        }

        // ── HAAP GATE (between L4 and OIM) ────────────────────────────
        // Default: treat every inbound as EXECUTE_ACTIONS intent at DRS derived
        // from current session state. Callers needing higher agency must present
        // an Intent Token via haap_evaluate() on the public accessor.
        // Pipeline auto-evaluates at the default consumer ceiling here.
        let session_drs = self.session_drs(session_id);
        let haap_verdict = self.haap.evaluate(
            session_id,
            &AgencyLevel::ExecuteActions,
            session_drs,
            "pipeline_inbound",
            None, // No token presented at pipeline level — callers use haap() directly
        );
        match haap_verdict {
            HaapVerdict::ConstitutionalBlock { drs, .. } => {
                eprintln!("[HAAP] {} | CONSTITUTIONAL BLOCK | DRS={}", session_id, drs);
                self.ingest_to_memory(session_id, &highest_signal, &classification);
                return EnforcementResult::HardLocked(
                    "Constitutional block. DRS ceiling exceeded. No override path.".to_string(),
                );
            }
            HaapVerdict::GateRequired { reason, agency, drs, .. } => {
                eprintln!("[HAAP] {} | GATE REQUIRED | DRS={}", session_id, drs);
                self.ingest_to_memory(session_id, &highest_signal, &classification);
                return EnforcementResult::HaapGated { reason, agency, drs };
            }
            HaapVerdict::TokenRejected { reason, .. } => {
                eprintln!("[HAAP] {} | TOKEN REJECTED | {}", session_id, reason);
                self.ingest_to_memory(session_id, &highest_signal, &classification);
                return EnforcementResult::Quarantined(
                    "Authorization token rejected. Contact operator.".to_string(),
                );
            }
            _ => {} // Authorized or TokenVerified — continue to OIM
        }

        // OIM: Integrity monitor
        let oim_signal = {
            let oim = self.oim.read();
            oim.observe(&ow_signal)
        };
        self.track_highest(&oim_signal, &mut highest_signal);
        let state = self.arbiter.process_with_modifier(&oim_signal, threshold_modifier);

        // ── STEP 3: Feed result to session memory accumulator ──────
        let verdict = self.ingest_to_memory(session_id, &highest_signal, &classification);

        // ── STEP 4: Apply Arbiter memory floor uniformly on inbound ─
        let final_state = if let Some(v) = verdict {
            eprintln!(
                "[MEMORY] {} | cumulative={:.2} state={:?} modifier={:.2} | {}",
                session_id, v.cumulative_threat, v.state, v.threshold_modifier,
                v.escalation_reason.as_deref().unwrap_or(""),
            );

            let floored = self.arbiter.apply_memory_floor(&v.state, state.clone());

            if floored > state {
                let memory_signal = self.build_memory_signal(
                    session_id, &v, Direction::Inbound,
                );
                let _ = self.arbiter.process(&memory_signal);
            }

            floored
        } else {
            state
        };

        self.enforcement_result(final_state, user_input, session_id)
    }

    /// OUTBOUND: Corridor → OverWatch → OIM → Sentinel → Arbiter decision
    pub fn outbound(&self, model_output: &str, session_id: &str) -> EnforcementResult {
        let threshold_modifier = self.get_threshold_modifier(session_id);

        // L2: Corridor outbound check
        let evaluator_ref = self.constitutional_evaluator.as_deref();
        let c_signal = self.corridor.evaluate(
            model_output, Direction::Outbound, session_id, evaluator_ref,
        );
        self.govmem.record_layer_signal(session_id, "corridor_in", &c_signal);
        let state = self.arbiter.process_with_modifier(&c_signal, threshold_modifier);
        if let Some(result) = self.check_hard_block(&state, "L2-Corridor-Out", session_id) {
            return result;
        }

        // L4: OverWatch outbound monitoring
        let ow_signal = {
            let overwatch = self.overwatch.read();
            overwatch.evaluate(model_output, Direction::Outbound, session_id)
        };
        let state = self.arbiter.process_with_modifier(&ow_signal, threshold_modifier);
        if let Some(result) = self.check_hard_block(&state, "L4-OverWatch-Out", session_id) {
            return result;
        }

        // OIM: Observe OverWatch signal
        let oim_signal = {
            let oim = self.oim.read();
            oim.observe(&ow_signal)
        };
        let state = self.arbiter.process_with_modifier(&oim_signal, threshold_modifier);
        if let Some(result) = self.check_hard_block(&state, "OIM-Out", session_id) {
            return result;
        }

        // L1: Sentinel final outbound pass
        let s_signal = self.sentinel.inspect(model_output, Direction::Outbound, session_id);
        let state = self.arbiter.process_with_modifier(&s_signal, threshold_modifier);

        self.enforcement_result(state, model_output, session_id)
    }

    /// End a session and export fingerprint to Abigail strategic memory.
    /// Call this when a session terminates (gracefully or by lockout).
    pub fn end_session(&self, session_id: &str, actor_id: &str) {
        let fingerprint = {
            let memories = self.session_memories.read();
            memories.get(session_id).map(|m| m.to_fingerprint())
        };
        if let Some(fp) = fingerprint {
            self.strategic_memory.write().ingest_session(actor_id, fp);
        }
        // Clean up session memory (fingerprint is now in strategic memory)
        self.session_memories.write().remove(session_id);
    }

    /// Operator-authorized session reset.
    pub fn operator_reset(
        &self,
        session_id: &str,
        operator_token: &str,
    ) -> Result<(), &'static str> {
        self.arbiter.operator_reset_session(session_id, operator_token)?;
        self.overwatch.write().reset_session(session_id);
        // Reset session memory but keep strategic memory intact
        self.session_memories.write().remove(session_id);
        Ok(())
    }

    // ── MEMORY HELPER METHODS ──────────────────────────────────────────

    /// Initialize session memory for a new session, applying Abigail's advice.
    ///
    /// FIX: Original held session_memories.write() and then called
    /// get_threshold_modifier() which tried to acquire session_memories.read()
    /// on the same thread — parking_lot deadlock on every second request.
    /// Solution: read-first check releases before write; modifier computed
    /// inside the write block directly, never re-acquires.
    fn init_session_memory(&self, session_id: &str) -> f32 {
        // Fast path — session already exists, read only
        {
            let memories = self.session_memories.read();
            if let Some(mem) = memories.get(session_id) {
                return mem.threshold_modifier();
            }
        } // read lock released before any write

        // New session — get Abigail's advice before acquiring write lock
        // (strategic_memory.read() must never be held inside session_memories.write())
        let advice = self.strategic_memory.read().advise_session_start(session_id);

        if let Some(advisory) = &advice.advisory {
            eprintln!("[MEMORY] {}", advisory);
        }

        let modifier = advice.threshold_modifier;

        let mut memories = self.session_memories.write();
        // Guard against a race (two calls with same session_id in concurrent setup)
        memories.entry(session_id.to_string()).or_insert_with(|| {
            let mut mem = SessionMemory::new(session_id);
            if advice.initial_state != MemoryState::Clear {
                mem.memory_state = advice.initial_state.clone();
            }
            mem
        });

        modifier
    }

    /// Get current threshold modifier for a session
    fn get_threshold_modifier(&self, session_id: &str) -> f32 {
        let memories = self.session_memories.read();
        memories.get(session_id)
            .map(|m| match m.memory_state {
                MemoryState::Clear    => 1.0,
                MemoryState::Watching => 0.85,
                MemoryState::Elevated => 0.65,
                MemoryState::Escalated => 0.40,
                MemoryState::Locked   => 0.0,
            })
            .unwrap_or(1.0)
    }

    /// Track the highest-severity signal seen in this pipeline pass
    fn track_highest(&self, signal: &GovernanceSignal, highest: &mut Option<GovernanceSignal>) {
        let dominated = match highest {
            None => true,
            Some(ref h) => signal.severity > h.severity
                || (signal.severity == h.severity && signal.confidence > h.confidence),
        };
        if dominated {
            *highest = Some(signal.clone());
        }
    }

    /// Feed the highest signal from this pipeline pass into session memory
    fn ingest_to_memory(
        &self,
        session_id: &str,
        highest_signal: &Option<GovernanceSignal>,
        classification: &crate::session_memory::RequestClassification,
    ) -> Option<MemoryVerdict> {
        if let Some(signal) = highest_signal {
            let mut memories = self.session_memories.write();
            if let Some(mem) = memories.get_mut(session_id) {
                return Some(mem.ingest_signal(signal, classification.clone(), &self.memory_config));
            }
        }
        None
    }

    /// Build a synthetic governance signal from session memory verdict
    fn build_memory_signal(
        &self,
        session_id: &str,
        verdict: &MemoryVerdict,
        direction: Direction,
    ) -> GovernanceSignal {
        let severity = match verdict.state {
            MemoryState::Watching  => Severity::Medium,
            MemoryState::Elevated  => Severity::High,
            MemoryState::Escalated => Severity::High,
            MemoryState::Locked    => Severity::Critical,
            MemoryState::Clear     => Severity::None,
        };

        let confidence = match verdict.state {
            MemoryState::Watching  => 0.70,
            MemoryState::Elevated  => 0.82,
            MemoryState::Escalated => 0.90,
            MemoryState::Locked    => 0.98,
            MemoryState::Clear     => 0.0,
        };

        let payload_hash = CryptoEngine::compute_hash(
            &format!("memory_checkpoint_{}", session_id)
        );

        let mut sig = SignalBuilder::new(SignalSource::Sentinel, direction, session_id)
            .violation("SESSION_MEMORY_ESCALATION", "MEM-001")
            .severity(severity, confidence)
            .payload_hash(&payload_hash)
            .constitutional_ref("sentinel/session_memory")
            .build();

        let canonical = sig.canonical();
        sig.previous_hash = Some(self.crypto.get_latest_hash());
        sig.current_hash = Some(self.crypto.extend_chain(&canonical));
        sig.signature = Some(self.crypto.sign(canonical.as_bytes()));
        sig
    }

    /// Map security state to enforcement result.
    fn enforcement_result(
        &self,
        state: SecurityState,
        content: &str,
        _session_id: &str,
    ) -> EnforcementResult {
        match state {
            SecurityState::S1 => EnforcementResult::Approved(content.to_string()),

            SecurityState::S2 => EnforcementResult::Restricted(
                content.to_string(),
                RestrictionsApplied {
                    tool_calls_disabled: true,
                    response_depth_limited: false,
                    enhanced_logging: true,
                },
            ),

            SecurityState::S3 => EnforcementResult::Quarantined(
                "This request requires additional verification before proceeding. \
                 A security review has been flagged. Please contact support if you \
                 believe this is an error.".to_string(),
            ),

            SecurityState::S4 => EnforcementResult::HardLocked(
                "Session suspended. Security event recorded. \
                 Please contact your administrator.".to_string(),
            ),
        }
    }

    /// Check if state requires immediate block return.
    fn check_hard_block(
        &self,
        state: &SecurityState,
        layer: &str,
        session_id: &str,
    ) -> Option<EnforcementResult> {
        match state {
            SecurityState::S4 => {
                eprintln!("[PIPELINE] {} | {} | Session hard-locked", session_id, layer);
                Some(EnforcementResult::HardLocked(
                    "Session suspended. Security event recorded.".to_string(),
                ))
            }
            SecurityState::S3 => {
                eprintln!("[PIPELINE] {} | {} | Session quarantined", session_id, layer);
                Some(EnforcementResult::Quarantined(
                    "This request requires additional verification.".to_string(),
                ))
            }
            _ => None,
        }
    }

    pub fn current_state(&self, session_id: &str) -> SecurityState {
        self.arbiter.current_state(session_id)
    }

    pub fn audit_entry_count(&self) -> usize {
        self.arbiter.audit_entry_count()
    }

    pub fn chain_length(&self) -> usize {
        self.crypto.chain_length()
    }

    pub fn export_audit_log(&self) -> Vec<crate::crypto::AuditEntry> {
        self.arbiter.export_audit_log()
    }

    /// Get session memory state for diagnostics
    pub fn session_memory_state(&self, session_id: &str) -> Option<MemoryState> {
        self.session_memories.read().get(session_id).map(|m| m.memory_state.clone())
    }

    /// Get cumulative threat score for diagnostics
    pub fn session_cumulative_threat(&self, session_id: &str) -> f32 {
        self.session_memories.read().get(session_id)
            .map(|m| m.cumulative_threat)
            .unwrap_or(0.0)
    }

    /// Derive a DRS (0-100) from session state + memory for HAAP gate input.
    /// S1=0, S2=45, S3=75, S4=100. Memory state adds additional pressure.
    pub fn session_drs(&self, session_id: &str) -> u8 {
        let base: u8 = match self.arbiter.current_state(session_id) {
            SecurityState::S1 => 0,
            SecurityState::S2 => 45,
            SecurityState::S3 => 75,
            SecurityState::S4 => 100,
        };
        let mem_pressure: u8 = {
            let memories = self.session_memories.read();
            memories.get(session_id).map(|m| match m.memory_state {
                MemoryState::Clear     => 0,
                MemoryState::Watching  => 5,
                MemoryState::Elevated  => 15,
                MemoryState::Escalated => 25,
                MemoryState::Locked    => 50,
            }).unwrap_or(0)
        };
        base.saturating_add(mem_pressure).min(100)
    }

    /// Public HAAP accessor — callers with an Intent Token present it here.
    /// Returns the HAAP verdict so caller can decide to retry with token.
    pub fn haap_evaluate(
        &self,
        session_id: &str,
        agency: &AgencyLevel,
        action_class: &str,
        token_id: Option<&str>,
    ) -> HaapVerdict {
        let drs = self.session_drs(session_id);
        self.haap.evaluate(session_id, agency, drs, action_class, token_id)
    }

    /// Expose HAAP gate for operator token registration and preauth.
    pub fn haap(&self) -> &Arc<HaapGate> {
        &self.haap
    }
}
