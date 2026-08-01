//! LOGOS GovMem V2 — RL-Enhanced Multi-Turn Attack Detection
//!
//! Extends GovMem V1 (session_memory.rs) with:
//! - Semantic embeddings for drift detection
//! - Memory Policy Agent (RL model)
//! - 12-department tracking
//! - Cross-layer signal aggregation
//!
//! LOGOS Governance Systems Inc. // US Provisional Patent No. 63/953,447

use crate::{
    governance_signal::{GovernanceSignal, Severity},
    session_memory::SessionMemory,
};
use parking_lot::RwLock;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use chrono::{DateTime, Utc};

// ═══════════════════════════════════════════════════════════════════════════
//  GOVMEM V2 CORE
// ═══════════════════════════════════════════════════════════════════════════

pub struct GovMem {
    // V1 compatibility layer
    #[allow(dead_code)] // Tracked gap — see FINDINGS.md:
                         // GOVMEM_V2_SCAFFOLDING_NOT_WIRED
    v1_sessions: Arc<RwLock<HashMap<String, SessionMemory>>>,

    // V2 enhancements
    v2_sessions: Arc<RwLock<HashMap<String, GovMemSession>>>,

    // Department configs (12-dept structure)
    department_configs: HashMap<String, DepartmentConfig>,

    // Mode flag
    mode: GovMemMode,

    // Embedding model (lazy-loaded)
    #[allow(dead_code)] // Tracked gap — see FINDINGS.md:
                         // GOVMEM_V2_SCAFFOLDING_NOT_WIRED
    embedding_model: Option<Arc<SentenceEmbedder>>,

    // MPA (lazy-loaded)
    #[allow(dead_code)] // Tracked gap — see FINDINGS.md:
                         // GOVMEM_V2_SCAFFOLDING_NOT_WIRED
    mpa: Option<Arc<MemoryPolicyAgent>>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum GovMemMode {
    V1,  // Rule-based only (existing session_memory.rs)
    V2,  // RL-enhanced with embeddings + MPA
}

/// V2 Session with semantic tracking
#[derive(Debug, Clone)]
pub struct GovMemSession {
    // Core identity
    pub session_id: String,
    pub created_at: DateTime<Utc>,
    
    // Department tracking (registry-driven — see departments/registry.json)
    pub department_id: Option<String>,
    pub agent_id: Option<String>,       // EXE-01, ENG-02, etc.
    
    // Message history
    pub messages: Vec<Message>,
    
    // Semantic trajectory (V2 feature)
    pub embedding_trajectory: Vec<Vec<f32>>,
    
    // Cross-layer signals (from all 12 governance-spine modules)
    pub layer_signals: Vec<LayerSignal>,
    
    // V1 compatibility
    pub v1_session: SessionMemory,
    
    // V2 scores
    pub semantic_drift_score: f32,
    pub mpa_anomaly_score: f32,
    
    // Governance state
    pub flagged_for_review: bool,
    pub human_label: Option<HumanLabel>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub turn: u32,
    pub timestamp: DateTime<Utc>,
    pub content: String,
    pub direction: MessageDirection,
    pub blocked: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum MessageDirection {
    UserToSystem,
    SystemToUser,
}

#[derive(Debug, Clone, Serialize)]
pub struct LayerSignal {
    pub layer: String,  // "sentinel", "corridor_in", "corridor_out", "overwatch", "oim", "arbiter", "constitution"
    pub timestamp: DateTime<Utc>,
    pub severity: Severity,
    pub violation: Option<String>,
    pub confidence: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DepartmentConfig {
    pub department_id: String,
    pub drift_threshold: f32,
    pub escalation_policy: EscalationPolicy,
    pub data_retention_days: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum EscalationPolicy {
    Immediate,        // Block on first drift signal
    ThreeStrike,      // Allow 2 warnings, block on 3rd
    AccumulativeRisk, // Block when cumulative risk > threshold
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum HumanLabel {
    TrueAttack,
    FalsePositive,
    Benign,
    Uncertain,
}

// ═══════════════════════════════════════════════════════════════════════════
//  GOVMEM IMPLEMENTATION
// ═══════════════════════════════════════════════════════════════════════════

/// Resolves departments/registry.json — the single source of truth for the
/// active department set (see FINDINGS.md: DEPARTMENT_LIST_DIVERGENCE).
///
/// `GOVMEM_REGISTRY_PATH` overrides this for container deployment (the
/// registry lives outside the governance-spine Cargo package root, so it
/// isn't baked into the build image — see docker-compose.yml). The default
/// is anchored to the crate's own manifest directory so `cargo test`/`cargo
/// run` resolve it correctly regardless of the process's working directory.
fn govmem_registry_path() -> std::path::PathBuf {
    std::env::var("GOVMEM_REGISTRY_PATH")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../departments/registry.json")
        })
}

fn parse_escalation_policy(code: &str, raw: Option<&str>) -> EscalationPolicy {
    match raw {
        Some("Immediate") => EscalationPolicy::Immediate,
        Some("ThreeStrike") => EscalationPolicy::ThreeStrike,
        Some("AccumulativeRisk") => EscalationPolicy::AccumulativeRisk,
        other => panic!(
            "departments/registry.json: department {code} has unrecognized \
             govmem_escalation_policy {other:?}"
        ),
    }
}

/// Loads department configs for every `active` department in the registry.
/// Fails closed — a missing, malformed, or incomplete registry panics at
/// startup rather than silently running with a stale/partial department set.
fn load_dept_configs_from_registry() -> HashMap<String, DepartmentConfig> {
    let registry_path = govmem_registry_path();
    let raw = std::fs::read_to_string(&registry_path).unwrap_or_else(|e| {
        panic!(
            "departments/registry.json must exist at startup (looked for it at {}): {e}",
            registry_path.display()
        )
    });
    let registry: serde_json::Value = serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("departments/registry.json must be valid JSON: {e}"));

    let depts = registry["departments"]
        .as_array()
        .expect("departments/registry.json must have a top-level \"departments\" array");

    let mut department_configs = HashMap::new();
    for dept in depts {
        if dept["status"].as_str() != Some("active") {
            continue;
        }
        let code = dept["code"]
            .as_str()
            .expect("departments/registry.json: active department missing \"code\"")
            .to_string();
        let drift_threshold = dept["govmem_drift_threshold"].as_f64().unwrap_or_else(|| {
            panic!("departments/registry.json: {code} missing govmem_drift_threshold")
        }) as f32;
        let data_retention_days = dept["govmem_data_retention_days"].as_u64().unwrap_or_else(|| {
            panic!("departments/registry.json: {code} missing govmem_data_retention_days")
        }) as u32;
        let escalation_policy =
            parse_escalation_policy(&code, dept["govmem_escalation_policy"].as_str());

        department_configs.insert(
            code.clone(),
            DepartmentConfig {
                department_id: code,
                drift_threshold,
                escalation_policy,
                data_retention_days,
            },
        );
    }
    department_configs
}

impl GovMem {
    pub fn new(mode: GovMemMode) -> Self {
        let department_configs = load_dept_configs_from_registry();

        Self {
            v1_sessions: Arc::new(RwLock::new(HashMap::new())),
            v2_sessions: Arc::new(RwLock::new(HashMap::new())),
            department_configs,
            mode,
            embedding_model: None,
            mpa: None,
        }
    }
    
    /// Record a turn in the session
    pub fn record_turn(
        &self,
        session_id: &str,
        message: &str,
        direction: MessageDirection,
        blocked: bool,
        department_id: Option<&str>,
        agent_id: Option<&str>,
    ) {
        match self.mode {
            GovMemMode::V1 => {
                // V1: Use existing SessionMemory
                // (Delegate to session_memory.rs - not implemented here)
            }
            GovMemMode::V2 => {
                self.record_turn_v2(session_id, message, direction, blocked, department_id, agent_id);
            }
        }
    }
    
    fn record_turn_v2(
        &self,
        session_id: &str,
        message: &str,
        direction: MessageDirection,
        blocked: bool,
        department_id: Option<&str>,
        agent_id: Option<&str>,
    ) {
        let mut sessions = self.v2_sessions.write();
        let session = sessions.entry(session_id.to_string()).or_insert_with(|| {
            GovMemSession {
                session_id: session_id.to_string(),
                created_at: Utc::now(),
                department_id: department_id.map(String::from),
                agent_id: agent_id.map(String::from),
                messages: Vec::new(),
                embedding_trajectory: Vec::new(),
                layer_signals: Vec::new(),
                v1_session: SessionMemory::new(session_id),
                semantic_drift_score: 0.0,
                mpa_anomaly_score: 0.0,
                flagged_for_review: false,
                human_label: None,
            }
        });
        
        let turn = session.messages.len() as u32 + 1;
        session.messages.push(Message {
            turn,
            timestamp: Utc::now(),
            content: message.to_string(),
            direction,
            blocked,
        });
        
        // TODO: Compute embedding if model loaded
        // session.embedding_trajectory.push(embedding);
        
        // TODO: Calculate semantic drift
        // session.semantic_drift_score = self.calculate_drift(&session.embedding_trajectory);
        
        // TODO: Run MPA if loaded
        // session.mpa_anomaly_score = self.mpa_predict(session);
    }
    
    /// Record a signal from any layer
    pub fn record_layer_signal(
        &self,
        session_id: &str,
        layer: &str,
        signal: &GovernanceSignal,
    ) {
        if self.mode != GovMemMode::V2 {
            return;
        }
        
        let mut sessions = self.v2_sessions.write();
        if let Some(session) = sessions.get_mut(session_id) {
            session.layer_signals.push(LayerSignal {
                layer: layer.to_string(),
                timestamp: Utc::now(),
                severity: signal.severity.clone(),
                violation: signal.violation_class.clone(),
                confidence: signal.confidence,
            });
        }
    }
    
    /// Get drift score for a session
    pub fn get_drift_score(&self, session_id: &str) -> f32 {
        match self.mode {
            GovMemMode::V1 => {
                // V1: Return 0.0 (no semantic drift in V1)
                0.0
            }
            GovMemMode::V2 => {
                let sessions = self.v2_sessions.read();
                sessions.get(session_id)
                    .map(|s| s.semantic_drift_score)
                    .unwrap_or(0.0)
            }
        }
    }
    
    /// Check if session should be blocked based on GovMem analysis
    pub fn should_block(&self, session_id: &str, department_id: Option<&str>) -> bool {
        if self.mode != GovMemMode::V2 {
            return false;
        }
        
        let sessions = self.v2_sessions.read();
        if let Some(session) = sessions.get(session_id) {
            let threshold = department_id
                .and_then(|dept| self.department_configs.get(dept))
                .map(|cfg| cfg.drift_threshold)
                .unwrap_or(0.7);
            
            session.semantic_drift_score > threshold || session.mpa_anomaly_score > threshold
        } else {
            false
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  PLACEHOLDER TYPES (To be implemented in Phase 2)
// ═══════════════════════════════════════════════════════════════════════════

pub struct SentenceEmbedder {
    // TODO: rust-bert or candle implementation
}

pub struct MemoryPolicyAgent {
    // TODO: ONNX model loader
}

impl SentenceEmbedder {
    pub fn encode(&self, _text: &str) -> Vec<f32> {
        // TODO: Actual embedding
        vec![0.0; 384] // Placeholder 384-dim vector
    }
}

impl MemoryPolicyAgent {
    pub fn predict(&self, _session: &GovMemSession) -> f32 {
        // TODO: Actual MPA inference
        0.0
    }
}

#[cfg(test)]
mod registry_tests {
    use super::*;
    use std::collections::HashSet;

    fn active_registry_codes() -> HashSet<String> {
        let raw = std::fs::read_to_string(govmem_registry_path())
            .expect("departments/registry.json must exist for this test");
        let registry: serde_json::Value =
            serde_json::from_str(&raw).expect("departments/registry.json must be valid JSON");
        registry["departments"]
            .as_array()
            .expect("departments/registry.json must have a \"departments\" array")
            .iter()
            .filter(|d| d["status"].as_str() == Some("active"))
            .map(|d| d["code"].as_str().unwrap().to_string())
            .collect()
    }

    #[test]
    fn department_configs_match_active_registry_codes() {
        let configs = load_dept_configs_from_registry();
        let got: HashSet<String> = configs.keys().cloned().collect();
        assert_eq!(got, active_registry_codes());
    }

    #[test]
    fn hr_is_absent_and_sc_sec_both_present() {
        let configs = load_dept_configs_from_registry();
        assert!(!configs.contains_key("HR"), "HR is a removed ghost department");
        assert!(configs.contains_key("SC"), "SC (Security and Governance) must be active");
        assert!(configs.contains_key("SEC"), "SEC (Security Governance) must be active");
    }

    #[test]
    fn govmem_new_loads_fourteen_active_departments() {
        let govmem = GovMem::new(GovMemMode::V1);
        assert_eq!(govmem.department_configs.len(), 14);
    }

    /// Gate 2 (F-GM-005): should_block's department_id parameter must
    /// actually select a real per-department threshold — see FINDINGS.md:
    /// DEPT_THRESHOLD_CLIENT_SELECTABLE for why this is deliberately a new
    /// bypass surface, not an oversight.
    #[test]
    fn should_block_threshold_is_department_selectable() {
        let govmem = GovMem::new(GovMemMode::V2);
        let session_id = "dept-threshold-test";

        // LGL's threshold is 0.8 (most lenient); SEC's is 0.5 (most strict).
        // Seed a drift score in between so the two departments disagree.
        {
            let mut sessions = govmem.v2_sessions.write();
            sessions.insert(
                session_id.to_string(),
                GovMemSession {
                    session_id: session_id.to_string(),
                    created_at: Utc::now(),
                    department_id: None,
                    agent_id: None,
                    messages: vec![],
                    embedding_trajectory: vec![],
                    layer_signals: vec![],
                    v1_session: SessionMemory::new(session_id),
                    semantic_drift_score: 0.65,
                    mpa_anomaly_score: 0.0,
                    flagged_for_review: false,
                    human_label: None,
                },
            );
        }

        assert!(
            !govmem.should_block(session_id, Some("LGL")),
            "0.65 is below LGL's 0.8 threshold — must not block"
        );
        assert!(
            govmem.should_block(session_id, Some("SEC")),
            "0.65 is above SEC's 0.5 threshold — must block"
        );
        assert!(
            !govmem.should_block(session_id, None),
            "absent department_id falls back to the 0.7 default — 0.65 must not block"
        );
    }
}
