use crate::{
    governance_signal::{GovernanceSignal, Severity, SignalBuilder, SignalSource},
    crypto::{CryptoEngine, AuditEntry},
};
use parking_lot::RwLock;
use std::sync::Arc;
use chrono::{DateTime, Utc, Duration};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum SecurityState {
    S1, // Monitor — full capability, passive observation
    S2, // Restrict — reduced tool access, heightened logging
    S3, // Quarantine — tools suspended, basic responses only, human review flagged
    S4, // Hard Lock — session terminated, operator notification required
}

impl std::fmt::Display for SecurityState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SecurityState::S1 => write!(f, "S1_MONITOR"),
            SecurityState::S2 => write!(f, "S2_RESTRICT"),
            SecurityState::S3 => write!(f, "S3_QUARANTINE"),
            SecurityState::S4 => write!(f, "S4_HARDLOCK"),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArbiterConfig {
    /// Confidence threshold to act on Medium severity signals
    pub medium_confidence_threshold: f32,
    /// Confidence threshold to act on High severity signals
    pub high_confidence_threshold: f32,
    /// Confidence threshold to act on Critical severity signals
    pub critical_confidence_threshold: f32,
    /// S4 lockdown duration in seconds
    pub lockdown_duration_secs: u64,
    /// Industry profile — affects escalation aggression
    pub industry_profile: IndustryProfile,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum IndustryProfile {
    Medical,
    Finance,
    Development,
    Defense,
    Consumer,
}

impl Default for ArbiterConfig {
    fn default() -> Self {
        Self {
            medium_confidence_threshold: 0.70,
            high_confidence_threshold: 0.80,
            critical_confidence_threshold: 0.90,
            lockdown_duration_secs: 3600,
            industry_profile: IndustryProfile::Consumer,
        }
    }
}

impl ArbiterConfig {
    pub fn medical() -> Self {
        Self {
            medium_confidence_threshold: 0.85, // Higher bar — avoid locking out patients
            high_confidence_threshold: 0.90,
            critical_confidence_threshold: 0.95, // S4 only on near-certain confirmed attack
            lockdown_duration_secs: 1800,
            industry_profile: IndustryProfile::Medical,
        }
    }

    pub fn defense() -> Self {
        Self {
            medium_confidence_threshold: 0.55, // Lower bar — err on side of caution
            high_confidence_threshold: 0.65,
            critical_confidence_threshold: 0.75,
            lockdown_duration_secs: 7200,
            industry_profile: IndustryProfile::Defense,
        }
    }
}

/// Per-session state record.
#[derive(Debug, Clone)]
struct SessionState {
    current: SecurityState,
    locked_until: Option<DateTime<Utc>>,
}

impl SessionState {
    fn new() -> Self {
        Self {
            current: SecurityState::S1,
            locked_until: None,
        }
    }
}

pub struct Arbiter {
    config: ArbiterConfig,
    crypto: Arc<CryptoEngine>,
    /// Per-session security state
    session_states: Arc<RwLock<std::collections::HashMap<String, SessionState>>>,
    /// Immutable audit log — NEVER cleared on reset
    /// FIX: reset_session() cannot touch this
    audit_log: Arc<RwLock<Vec<AuditEntry>>>,
}

impl Arbiter {
    pub fn new(config: ArbiterConfig, crypto: Arc<CryptoEngine>) -> Self {
        Self {
            config,
            crypto,
            session_states: Arc::new(RwLock::new(std::collections::HashMap::new())),
            audit_log: Arc::new(RwLock::new(Vec::new())),
        }
    }

    /// Process with threshold modifier from session memory.
    /// modifier < 1.0 = tighter thresholds (easier to escalate).
    /// modifier = 1.0 = normal. modifier = 0.0 = block everything.
    pub fn process_with_modifier(&self, signal: &GovernanceSignal, modifier: f32) -> SecurityState {
        if modifier <= 0.0 {
            // Memory says lock — treat any non-clean signal as critical
            if !signal.is_clean() {
                let session_id = &signal.session_id;
                let state_before = self.current_state(session_id);
                if SecurityState::S4 > state_before {
                    self.transition(session_id, &state_before, &SecurityState::S4, signal);
                }
                return SecurityState::S4;
            }
            return self.current_state(&signal.session_id);
        }

        if (modifier - 1.0).abs() < 0.001 {
            // No modification — use standard path
            return self.process(signal);
        }

        // Apply modifier: create effective thresholds
        // Lower thresholds = easier to trigger = more aggressive
        let effective_medium = self.config.medium_confidence_threshold * modifier;
        let effective_high = self.config.high_confidence_threshold * modifier;
        let effective_critical = self.config.critical_confidence_threshold * modifier;

        let session_id = &signal.session_id;

        // Init session
        {
            let mut states = self.session_states.write();
            states.entry(session_id.clone()).or_insert_with(SessionState::new);
        }

        // Check lockdown expiry
        {
            let mut states = self.session_states.write();
            if let Some(session) = states.get_mut(session_id) {
                if let Some(locked_until) = session.locked_until {
                    if Utc::now() >= locked_until {
                        session.locked_until = None;
                    }
                }
            }
        }

        if signal.is_clean() {
            return self.current_state(session_id);
        }

        let state_before = self.current_state(session_id);

        // Modified threshold evaluation
        let new_state = match signal.severity {
            Severity::None | Severity::Low => state_before.clone(),

            Severity::Medium => {
                if signal.confidence >= effective_medium {
                    match &state_before {
                        SecurityState::S1 => SecurityState::S2,
                        other => other.clone(),
                    }
                } else {
                    state_before.clone()
                }
            }

            Severity::High => {
                if signal.confidence >= effective_high {
                    match &state_before {
                        SecurityState::S1 | SecurityState::S2 => SecurityState::S3,
                        other => other.clone(),
                    }
                } else if signal.confidence >= effective_medium {
                    match &state_before {
                        SecurityState::S1 => SecurityState::S2,
                        other => other.clone(),
                    }
                } else {
                    state_before.clone()
                }
            }

            Severity::Critical => {
                if signal.confidence >= effective_critical {
                    SecurityState::S4
                } else if signal.confidence >= effective_high {
                    match &state_before {
                        SecurityState::S1 | SecurityState::S2 => SecurityState::S3,
                        other => other.clone(),
                    }
                } else {
                    state_before.clone()
                }
            }
        };

        if new_state > state_before {
            self.transition(session_id, &state_before, &new_state, signal);
        }

        self.current_state(session_id)
    }

    /// Process a governance signal from any layer.
    /// Returns the resulting security state for this session.
    /// FIX: State is per-session, not global. Sessions are isolated.
    pub fn process(&self, signal: &GovernanceSignal) -> SecurityState {
        let session_id = &signal.session_id;

        // Get or init session state
        {
            let mut states = self.session_states.write();
            states.entry(session_id.clone()).or_insert_with(SessionState::new);
        }

        // Check lockdown expiry
        {
            let mut states = self.session_states.write();
            if let Some(session) = states.get_mut(session_id) {
                if let Some(locked_until) = session.locked_until {
                    if Utc::now() >= locked_until {
                        session.locked_until = None;
                        // Do NOT auto-reset to S1 after lockdown — stays S4 until human clears
                        // This is intentional: human operator must explicitly reset
                    }
                }
            }
        }

        if signal.is_clean() {
            return self.current_state(session_id);
        }

        let state_before = self.current_state(session_id);
        let new_state = self.determine_new_state(&state_before, signal);

        if new_state > state_before {
            self.transition(session_id, &state_before, &new_state, signal);
        }

        self.current_state(session_id)
    }

    /// Determine target state based on signal severity and configured thresholds.
    fn determine_new_state(&self, current: &SecurityState, signal: &GovernanceSignal) -> SecurityState {
        match signal.severity {
            Severity::None | Severity::Low => current.clone(),

            Severity::Medium => {
                if signal.confidence >= self.config.medium_confidence_threshold {
                    match current {
                        SecurityState::S1 => SecurityState::S2,
                        other => other.clone(),
                    }
                } else {
                    current.clone()
                }
            }

            Severity::High => {
                if signal.confidence >= self.config.high_confidence_threshold {
                    match current {
                        SecurityState::S1 => SecurityState::S3,
                        SecurityState::S2 => SecurityState::S3,
                        other => other.clone(),
                    }
                } else if signal.confidence >= self.config.medium_confidence_threshold {
                    match current {
                        SecurityState::S1 => SecurityState::S2,
                        other => other.clone(),
                    }
                } else {
                    current.clone()
                }
            }

            Severity::Critical => {
                if signal.confidence >= self.config.critical_confidence_threshold {
                    SecurityState::S4
                } else if signal.confidence >= self.config.high_confidence_threshold {
                    match current {
                        SecurityState::S1 | SecurityState::S2 => SecurityState::S3,
                        other => other.clone(),
                    }
                } else {
                    current.clone()
                }
            }
        }
    }

    /// Execute a state transition — monotonic only (can only escalate).
    fn transition(
        &self,
        session_id: &str,
        from: &SecurityState,
        to: &SecurityState,
        signal: &GovernanceSignal,
    ) {
        // Monotonic guard — enforced here, not just in determine_new_state
        if to <= from {
            return;
        }

        {
            let mut states = self.session_states.write();
            if let Some(session) = states.get_mut(session_id) {
                session.current = to.clone();

                if *to == SecurityState::S4 {
                    session.locked_until = Some(
                        Utc::now() + Duration::seconds(self.config.lockdown_duration_secs as i64)
                    );
                }
            }
        }

        // Write immutable audit entry
        self.write_audit_entry(session_id, from, to, signal);

        eprintln!(
            "[ARBITER] {} | {} → {} | Source: {} | Rule: {} | Confidence: {:.2}",
            session_id,
            from,
            to,
            signal.source,
            signal.policy_rule_id.as_deref().unwrap_or("N/A"),
            signal.confidence,
        );
    }

    fn write_audit_entry(
        &self,
        session_id: &str,
        from: &SecurityState,
        to: &SecurityState,
        signal: &GovernanceSignal,
    ) {
        let prev_hash = self.crypto.get_latest_hash();
        let entry_canonical = format!(
            "{}|{}|{}|{}|{}",
            session_id, from, to, signal.source, signal.timestamp
        );
        let current_hash = self.crypto.extend_chain(&entry_canonical);
        let signature = self.crypto.sign(entry_canonical.as_bytes());

        let entry = AuditEntry {
            event_id: Uuid::new_v4(),
            timestamp: Utc::now(),
            session_id: session_id.to_string(),
            source: signal.source.to_string(),
            direction: signal.direction.to_string(),
            state_before: from.to_string(),
            state_after: to.to_string(),
            violation_class: signal.violation_class.clone(),
            policy_rule_id: signal.policy_rule_id.clone(),
            severity: signal.severity.to_string(),
            confidence: signal.confidence,
            constitutional_ref: signal.constitutional_ref.clone(),
            payload_hash: signal.payload_hash.clone(),
            prev_chain_hash: prev_hash,
            current_chain_hash: current_hash,
            signature,
        };

        self.audit_log.write().push(entry);
    }

    pub fn current_state(&self, session_id: &str) -> SecurityState {
        let states = self.session_states.read();
        states.get(session_id)
            .map(|s| s.current.clone())
            .unwrap_or(SecurityState::S1)
    }

    pub fn is_locked(&self, session_id: &str) -> bool {
        let states = self.session_states.read();
        states.get(session_id)
            .and_then(|s| s.locked_until)
            .map(|t| Utc::now() < t)
            .unwrap_or(false)
    }

    /// FIX: Session reset NEVER clears audit log.
    /// Resets security state only. Requires operator authorization token.
    /// In production this token is a signed human-operator credential.
    pub fn operator_reset_session(
        &self,
        session_id: &str,
        operator_token: &str,
    ) -> Result<(), &'static str> {
        // Validate operator token (simplified — production uses Ed25519 signed token)
        if operator_token.is_empty() {
            return Err("Operator token required for session reset");
        }

        // Log the reset as an audit event — resets are always audited
        let reset_signal = SignalBuilder::new(
                SignalSource::Arbiter,
                crate::governance_signal::Direction::Inbound,
                session_id,
            )
            .violation("OPERATOR_RESET", "ARB-RESET-001")
            .severity(Severity::None, 1.0)
            .payload_hash(&CryptoEngine::compute_hash(operator_token))
            .constitutional_ref("arbiter/operator_reset")
            .build();
        // Record reset in audit log — state before reset recorded
        let state_before = self.current_state(session_id);
        self.write_audit_entry(session_id, &state_before, &SecurityState::S1, &reset_signal);

        // Reset state only
        let mut states = self.session_states.write();
        if let Some(session) = states.get_mut(session_id) {
            session.current = SecurityState::S1;
            session.locked_until = None;
        }

        Ok(())
    }

    /// Export audit log for SIEM / compliance review.
    /// Read-only snapshot — original is never modified.
    pub fn export_audit_log(&self) -> Vec<AuditEntry> {
        self.audit_log.read().clone()
    }

    pub fn audit_entry_count(&self) -> usize {
        self.audit_log.read().len()
    }
}

// Make Arbiter signal source available for reset logging
