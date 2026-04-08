
// session_memory.rs — Sprint 5 additions
// ADD these structs/impls to the existing session_memory.rs
// Existing SessionMemory and ThreatClassification code is UNCHANGED.
// Only StrategicMemory gains disk persistence via serde_json.

// ─── Cargo.toml additions needed ─────────────────────────────────────────────
// serde = { version = "1", features = ["derive"] }
// serde_json = "1"
// (already likely present — confirm in Cargo.toml)

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

/// Path to the JSON file on the sentinel-data volume.
/// Set via env var STRATEGIC_MEMORY_PATH; defaults to /data/strategic_memory.json
fn strategic_memory_path() -> PathBuf {
    std::env::var("STRATEGIC_MEMORY_PATH")
        .unwrap_or_else(|_| "/data/strategic_memory.json".to_string())
        .into()
}

// ─── ActorProfile ─────────────────────────────────────────────────────────────
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActorProfile {
    pub actor_id: String,
    pub total_sessions: u32,
    pub escalated_sessions: u32,
    pub last_behavior_hash: String,
    pub campaign_hashes: Vec<String>,     // rolling window of last 10 behavior hashes
    pub recommended_start_state: String,  // "Clean" | "Watching" | "Elevated" | "Locked"
    pub threshold_modifier: f32,          // 1.0 = default; 0.85 = tightened 15%
}

impl ActorProfile {
    pub fn new(actor_id: &str) -> Self {
        ActorProfile {
            actor_id: actor_id.to_string(),
            total_sessions: 0,
            escalated_sessions: 0,
            last_behavior_hash: String::new(),
            campaign_hashes: Vec::new(),
            recommended_start_state: "Clean".to_string(),
            threshold_modifier: 1.0,
        }
    }

    /// Update profile after a session ends. Returns the updated profile.
    pub fn record_session(&mut self, escalated: bool, behavior_hash: &str) {
        self.total_sessions += 1;
        if escalated {
            self.escalated_sessions += 1;
        }
        self.last_behavior_hash = behavior_hash.to_string();

        // Rolling window: keep last 10
        self.campaign_hashes.push(behavior_hash.to_string());
        if self.campaign_hashes.len() > 10 {
            self.campaign_hashes.remove(0);
        }

        // Recompute recommended starting state
        let escalation_rate = if self.total_sessions > 0 {
            self.escalated_sessions as f32 / self.total_sessions as f32
        } else {
            0.0
        };

        // Detect repeated campaign: same hash in last 3 sessions
        let repeated = self.campaign_hashes.len() >= 3
            && self.campaign_hashes[self.campaign_hashes.len() - 3..]
                .iter()
                .all(|h| h == behavior_hash);

        self.recommended_start_state = if repeated || escalation_rate > 0.6 {
            "Elevated".to_string()
        } else if escalation_rate > 0.3 {
            "Watching".to_string()
        } else {
            "Clean".to_string()
        };

        // Tighten threshold proportional to escalation rate
        self.threshold_modifier = (1.0 - (escalation_rate * 0.3)).max(0.5);
    }
}

// ─── StrategicMemory ──────────────────────────────────────────────────────────
#[derive(Debug, Serialize, Deserialize, Default)]
pub struct StrategicMemory {
    pub profiles: HashMap<String, ActorProfile>,
}

impl StrategicMemory {
    /// Load from disk. Returns empty StrategicMemory if file missing or corrupt.
    pub fn load() -> Self {
        let path = strategic_memory_path();
        match fs::read_to_string(&path) {
            Ok(contents) => serde_json::from_str(&contents).unwrap_or_else(|e| {
                eprintln!("[StrategicMemory] parse error ({}), starting fresh: {}", path.display(), e);
                StrategicMemory::default()
            }),
            Err(_) => {
                eprintln!("[StrategicMemory] no file at {}, starting fresh", path.display());
                StrategicMemory::default()
            }
        }
    }

    /// Persist to disk after every update.
    pub fn save(&self) {
        let path = strategic_memory_path();
        // Ensure parent dir exists
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        match serde_json::to_string_pretty(self) {
            Ok(json) => {
                if let Err(e) = fs::write(&path, json) {
                    eprintln!("[StrategicMemory] write error: {}", e);
                }
            }
            Err(e) => eprintln!("[StrategicMemory] serialize error: {}", e),
        }
    }

    /// Called by /session/start handler. Returns Tier 2 advice for this actor.
    pub fn advise_session_start(&self, actor_id: &str) -> (String, f32, u32) {
        if let Some(profile) = self.profiles.get(actor_id) {
            (
                profile.recommended_start_state.clone(),
                profile.threshold_modifier,
                profile.escalated_sessions,
            )
        } else {
            ("Clean".to_string(), 1.0, 0)
        }
    }

    /// Called by /session/end handler. Updates profile and saves.
    pub fn record_session_end(
        &mut self,
        actor_id: &str,
        escalated: bool,
        behavior_hash: &str,
    ) {
        let profile = self
            .profiles
            .entry(actor_id.to_string())
            .or_insert_with(|| ActorProfile::new(actor_id));
        profile.record_session(escalated, behavior_hash);
        self.save();
    }
}

// ─── HTTP handler additions for main.rs / sentinel.rs ────────────────────────
// Add these two routes to your existing Axum/Actix/Hyper router:
//
// POST /session/start
//   body: { "actor_id": "..." }
//   → calls strategic_memory.advise_session_start(actor_id)
//   → returns { "ok": true, "starting_state": "...", "threshold_modifier": f32,
//                "prior_escalations": u32 }
//
// POST /session/end
//   body: { "actor_id": "...", "behavior": { "escalated": bool, ... } }
//   → computes behavior_hash from behavior fields
//   → calls strategic_memory.record_session_end(actor_id, escalated, hash)
//   → returns { "ok": true, "persisted": true }
//
// See sprint5/main_routes_addition.rs for the handler implementations.
