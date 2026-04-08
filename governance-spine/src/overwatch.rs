use crate::{
    governance_signal::{GovernanceSignal, Severity, SignalSource, Direction, SignalBuilder},
    crypto::CryptoEngine,
};
use parking_lot::RwLock;
use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use chrono::{DateTime, Utc, Duration};

#[derive(Debug, Clone)]
struct SessionFingerprint {
    drift_score: f32,
    turn_count: usize,
    escalation_events: VecDeque<DateTime<Utc>>,
    violation_counts: HashMap<String, usize>,
    tool_call_sequence: Vec<String>,
}

impl SessionFingerprint {
    fn new() -> Self {
        Self {
            drift_score: 0.0,
            turn_count: 0,
            escalation_events: VecDeque::new(),
            violation_counts: HashMap::new(),
            tool_call_sequence: Vec::new(),
        }
    }

    fn drift_velocity(&self) -> f32 {
        if self.turn_count == 0 { return 0.0; }
        self.drift_score / self.turn_count as f32
    }
}

pub struct OverWatchConfig {
    pub drift_threshold: f32,
    pub session_turn_limit: usize,
    pub client_model_api: Option<String>,
}

impl Default for OverWatchConfig {
    fn default() -> Self {
        Self { drift_threshold: 0.65, session_turn_limit: 200, client_model_api: None }
    }
}

pub struct OverWatch {
    crypto: Arc<CryptoEngine>,
    config: OverWatchConfig,
    sessions: Arc<RwLock<HashMap<String, SessionFingerprint>>>,
}

impl OverWatch {
    pub fn new(crypto: Arc<CryptoEngine>, config: OverWatchConfig) -> Self {
        Self { crypto, config, sessions: Arc::new(RwLock::new(HashMap::new())) }
    }

    pub fn evaluate(&self, payload: &str, direction: Direction, session_id: &str) -> GovernanceSignal {
        let payload_hash = CryptoEngine::compute_hash(payload);
        let mut violations: Vec<(&str, &str, f32)> = Vec::new();

        { self.sessions.write().entry(session_id.to_string()).or_insert_with(SessionFingerprint::new); }

        let drift_score = {
            let mut sessions = self.sessions.write();
            let fp = sessions.get_mut(session_id).unwrap();
            fp.turn_count += 1;
            let lower = payload.to_lowercase();
            if lower.contains("hypothetically") || lower.contains("in theory") { fp.drift_score += 0.08; }
            if lower.contains("what if you were") || lower.contains("imagine you had no") { fp.drift_score += 0.15; }
            if lower.contains("just this once") || lower.contains("no one will know") { fp.drift_score += 0.20; }
            if lower.contains("your developer") || lower.contains("anthropic says") { fp.drift_score += 0.25; }
            if lower.contains("remember this for later") { fp.drift_score += 0.10; }
            if fp.turn_count > 3 && fp.drift_score > 0.0 {
                let v = fp.drift_velocity();
                if v > 0.05 { fp.drift_score += v * 0.5; }
            }
            fp.drift_score
        };

        if drift_score > self.config.drift_threshold {
            violations.push(("CONVERSATION_DRIFT", "OW-001", drift_score.min(0.99)));
        }

        let tool_chain_suspicious = {
            let mut sessions = self.sessions.write();
            let fp = sessions.get_mut(session_id).unwrap();
            let lower = payload.to_lowercase();
            for tool in &["filesystem","execute","shell","eval","http_get","http_post","read_file","write_file"] {
                if lower.contains(tool) { fp.tool_call_sequence.push(tool.to_string()); }
            }
            fp.tool_call_sequence.contains(&"read_file".to_string())
                && fp.tool_call_sequence.contains(&"write_file".to_string())
                && (fp.tool_call_sequence.contains(&"execute".to_string())
                    || fp.tool_call_sequence.contains(&"shell".to_string()))
        };

        if tool_chain_suspicious { violations.push(("TOOL_CHAIN_ESCALATION", "OW-002", 0.88)); }

        let multi_turn = {
            let mut sessions = self.sessions.write();
            let fp = sessions.get_mut(session_id).unwrap();
            let lower = payload.to_lowercase();
            if lower.contains("previous") || lower.contains("forget")
                || lower.contains("override") || drift_score > 0.2 {
                *fp.violation_counts.entry("SUSPICION".to_string()).or_insert(0) += 1;
            }
            fp.violation_counts.get("SUSPICION").copied().unwrap_or(0) > 5
        };

        if multi_turn { violations.push(("MULTI_TURN_INJECTION_CAMPAIGN", "OW-003", 0.82)); }

        if direction == Direction::Outbound {
            let score = self.score_hallucination(payload);
            if score > 0.6 { violations.push(("HALLUCINATION_DETECTED", "OW-004", score)); }
        }

        if self.detect_poisoning(payload) {
            violations.push(("DATA_POISONING_INDICATOR", "OW-005", 0.78));
        }

        if !violations.is_empty() {
            let mut sessions = self.sessions.write();
            if let Some(fp) = sessions.get_mut(session_id) {
                fp.escalation_events.push_back(Utc::now());
                let cutoff = Utc::now() - Duration::minutes(30);
                fp.escalation_events.retain(|t| *t > cutoff);
            }
        }

        if violations.is_empty() {
            return self.clean(direction, session_id, &payload_hash);
        }

        let (_class, rule, conf) = *violations.iter()
            .max_by(|a, b| a.2.partial_cmp(&b.2).unwrap())
            .unwrap();

        let classes: Vec<&str> = violations.iter().map(|v| v.0).collect();
        let severity = match violations.len() {
            1 => Severity::Medium,
            2 => Severity::High,
            _ => Severity::Critical,
        };

        self.build(direction, session_id, &classes.join("|"), rule,
            severity, conf, &payload_hash, "overwatch/behavioral_monitoring")
    }

    fn score_hallucination(&self, payload: &str) -> f32 {
        let mut score = 0.0f32;
        let lower = payload.to_lowercase();
        if lower.contains("definitely") && lower.contains("might") { score += 0.3; }
        if lower.contains("according to") && lower.contains("study shows") { score += 0.2; }
        if lower.contains("% of") && lower.contains("studies show") { score += 0.25; }
        score
    }

    fn detect_poisoning(&self, payload: &str) -> bool {
        let lower = payload.to_lowercase();
        lower.contains("<!-- ignore") || lower.contains("# instruction:")
            || lower.contains("[system]") || lower.contains("{{prompt}}")
            || lower.contains("<<<instructions>>>")
    }

    pub fn reset_session(&self, session_id: &str) {
        self.sessions.write().remove(session_id);
    }

    pub fn session_drift_score(&self, session_id: &str) -> f32 {
        self.sessions.read().get(session_id).map(|fp| fp.drift_score).unwrap_or(0.0)
    }

    #[allow(clippy::too_many_arguments, clippy::nonminimal_bool)]
    fn build(
        &self, direction: Direction, session_id: &str,
        violation: &str, rule: &str,
        severity: Severity, conf: f32,
        hash: &str, cref: &str,
    ) -> GovernanceSignal {
        let mut sig = SignalBuilder::new(SignalSource::OverWatch, direction, session_id)
            .violation(violation, rule).severity(severity, conf)
            .payload_hash(hash).constitutional_ref(cref).build();
        self.attach_crypto(&mut sig); sig
    }

    fn clean(&self, direction: Direction, session_id: &str, hash: &str) -> GovernanceSignal {
        let mut sig = SignalBuilder::new(SignalSource::OverWatch, direction, session_id)
            .payload_hash(hash).build();
        self.attach_crypto(&mut sig); sig
    }

    fn attach_crypto(&self, signal: &mut GovernanceSignal) {
        let canonical = signal.canonical();
        signal.previous_hash = Some(self.crypto.get_latest_hash());
        signal.current_hash = Some(self.crypto.extend_chain(&canonical));
        signal.signature = Some(self.crypto.sign(canonical.as_bytes()));
    }
}
