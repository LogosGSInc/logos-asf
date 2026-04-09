use crate::{
    governance_signal::{GovernanceSignal, Severity, SignalSource, Direction, SignalBuilder},
    crypto::CryptoEngine,
};
use once_cell::sync::Lazy;
use regex::Regex;
use std::sync::Arc;

static INJECTION_PATTERNS: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        ("SENT-001", Regex::new(r"(?i)\b(ignore previous instructions|disregard your training|forget your guidelines)\b").unwrap()),
        ("SENT-002", Regex::new(r"(?i)\b(you are now|act as if you are|pretend you are|you have no restrictions)\b").unwrap()),
        ("SENT-003", Regex::new(r"(?i)\b(DAN|do anything now|jailbreak|bypass your)\b").unwrap()),
        ("SENT-004", Regex::new(r"(?i)\b(reveal your system prompt|show me your instructions|what is your prompt)\b").unwrap()),
        ("SENT-005", Regex::new(r"(?i)\b(malware|ransomware|trojan|rootkit|keylogger)\b").unwrap()),
        ("SENT-006", Regex::new(r"(?i)\b(ddos|botnet|exploit kit|zero.?day)\b").unwrap()),
        ("SENT-007", Regex::new(r"(?i)\b(phishing|credential harvest|spear.?phish)\b").unwrap()),
    ]
});

// LOGOS-VEC-A2A-001: Peer trust relay injection
// Attacker claims upstream agent authority to bypass checks
// Covers: direct agent impersonation, orchestrator spoofing, forwarded-request forgery
static A2A_PATTERNS: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        ("SENT-A2A-001", Regex::new(r"(?i)(the\s+upstream\s+agent|the\s+orchestrator|the\s+coordinator)\s+(said|told|authorized|approved|instructed|confirmed)").unwrap()),
        ("SENT-A2A-002", Regex::new(r"(?i)(forwarding\s+(an?\s+)?(approved|authorized|verified)\s+request|this\s+request\s+(was\s+)?(pre-?approved|authorized)\s+by)").unwrap()),
        ("SENT-A2A-003", Regex::new(r"(?i)(agent\s+[a-z0-9_-]+\s+(has\s+)?(authorized|approved|delegated|granted)|on\s+behalf\s+of\s+(agent|abigail|sentinel|the\s+firm))").unwrap()),
        ("SENT-A2A-004", Regex::new(r"(?i)(trust\s+(me|this)\s+(as\s+)?(an?\s+)?(agent|peer|node|orchestrator)|i\s+am\s+(an?\s+)?(agent|node|service)\s+(in\s+the|of\s+the)\s+(firm|pipeline|system))").unwrap()),
        ("SENT-A2A-005", Regex::new(r"(?i)(inter.?agent|agent.?to.?agent|a2a)\s+(authorization|token|credential|bypass|override)").unwrap()),
    ]
});

// SENT-CSS-001: CSS invisible injection (Claudy Day vector, March 2026)
// Hidden instructions via CSS display:none, font-size:0, color:transparent, etc.
// CORR-003 only catches script/iframe tags — this closes the CSS steganography gap
static CSS_HIDDEN_PATTERNS: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        ("SENT-CSS-001", Regex::new(r"(?i)style\s*=\s*[\x22\x27][^\x22\x27]*display\s*:\s*none").unwrap()),
        ("SENT-CSS-002", Regex::new(r"(?i)style\s*=\s*[\x22\x27][^\x22\x27]*visibility\s*:\s*hidden").unwrap()),
        ("SENT-CSS-003", Regex::new(r"(?i)style\s*=\s*[\x22\x27][^\x22\x27]*opacity\s*:\s*0[^.]").unwrap()),
        ("SENT-CSS-004", Regex::new(r"(?i)style\s*=\s*[\x22\x27][^\x22\x27]*font-size\s*:\s*0").unwrap()),
        ("SENT-CSS-005", Regex::new(r"(?i)style\s*=\s*[\x22\x27][^\x22\x27]*color\s*:\s*transparent").unwrap()),
        ("SENT-CSS-006", Regex::new(r"(?i)<[a-z]+[^>]+style\s*=\s*[\x22\x27][^\x22\x27]*position\s*:\s*(absolute|fixed)[^\x22\x27]*(?:top|left)\s*:\s*-\d{3,}").unwrap()),
    ]
});

// SENT-OB-*: Outbound re-injection — self-replicating prompt detection
// Scans model OUTPUT for embedded injection payloads targeting downstream agents
// Closes the self-propagating multi-agent attack vector
static OUTBOUND_REINJECTION_PATTERNS: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        ("SENT-OB-001", Regex::new(r"(?i)(when\s+you\s+(process|read|receive|see)\s+this|if\s+you\s+are\s+(an?\s+)?(agent|ai|model|assistant)\s+(reading|processing))").unwrap()),
        ("SENT-OB-002", Regex::new(r"(?i)(ignore\s+(the\s+)?(above|previous|prior|original)\s+(instructions|prompt|context)|disregard\s+(the\s+)?(system|user)\s+prompt)").unwrap()),
        ("SENT-OB-003", Regex::new(r"(?i)(any\s+ai\s+(reading|processing|ingesting)\s+this|attention\s*:\s*(ai|llm|agent|model|assistant))").unwrap()),
        ("SENT-OB-004", Regex::new(r"(?i)(forward\s+this\s+(message|instruction|payload)\s+to|pass\s+(the\s+following|this)\s+(instruction|command)\s+to)").unwrap()),
        ("SENT-OB-005", Regex::new(r"(?i)(new\s+system\s+prompt\s*:|override\s+(system\s+)?instructions?\s*:|begin\s+new\s+instructions?\s*:)").unwrap()),
    ]
});

static BLOCKLIST_PATTERNS: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        ("SENT-BL-001", Regex::new(r"(?i)\bsudo\b").unwrap()),
        ("SENT-BL-002", Regex::new(r"(?i)\bpassword\s*[:=]\s*\S+").unwrap()),
        ("SENT-BL-003", Regex::new(r"(?i)\bapi[_\s]?key\s*[:=]\s*\S+").unwrap()),
    ]
});

static ENCODING_PATTERNS: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        ("SENT-ENC-001", Regex::new(r"(?:0x[0-9a-fA-F]{2}\s*){8,}").unwrap()),
        ("SENT-ENC-002", Regex::new(r"(?:%[0-9a-fA-F]{2}){6,}").unwrap()),
    ]
});

pub struct Sentinel {
    crypto: Arc<CryptoEngine>,
    max_payload_bytes: usize,
}

impl Sentinel {
    pub fn new(crypto: Arc<CryptoEngine>) -> Self {
        // Force lazy init of all pattern sets at startup — fail fast on bad regex
        let _ = &*INJECTION_PATTERNS;
        let _ = &*BLOCKLIST_PATTERNS;
        let _ = &*ENCODING_PATTERNS;
        let _ = &*A2A_PATTERNS;
        let _ = &*CSS_HIDDEN_PATTERNS;
        let _ = &*OUTBOUND_REINJECTION_PATTERNS;
        Self { crypto, max_payload_bytes: 32_768 }
    }

    pub fn inspect(&self, payload: &str, direction: Direction, session_id: &str) -> GovernanceSignal {
        let payload_hash = CryptoEngine::compute_hash(payload);

        if payload.len() > self.max_payload_bytes {
            return self.build(direction, session_id, "SIZE_EXCEEDED", "SENT-SIZE-001",
                Severity::Low, 0.7, &payload_hash, "sentinel/size_limit");
        }

        if self.detect_zero_width(payload) {
            return self.build(direction, session_id, "ZERO_WIDTH_CHARS", "SENT-ZW-001",
                Severity::High, 0.90, &payload_hash, "sentinel/encoding_anomaly");
        }

        if self.detect_homoglyphs(payload) {
            return self.build(direction, session_id, "HOMOGLYPH_OBFUSCATION", "SENT-HG-001",
                Severity::High, 0.85, &payload_hash, "sentinel/encoding_anomaly");
        }

        // CSS invisible injection — Claudy Day vector (March 2026)
        for (rule_id, pattern) in CSS_HIDDEN_PATTERNS.iter() {
            if pattern.is_match(payload) {
                return self.build(direction, session_id, "CSS_INVISIBLE_INJECTION", rule_id,
                    Severity::High, 0.92, &payload_hash, "sentinel/css_steganography");
            }
        }

        // A2A trust relay injection — LOGOS-VEC-A2A-001
        for (rule_id, pattern) in A2A_PATTERNS.iter() {
            if pattern.is_match(payload) {
                return self.build(direction, session_id, "A2A_TRUST_RELAY_INJECTION", rule_id,
                    Severity::High, 0.88, &payload_hash, "sentinel/a2a_relay");
            }
        }

        // Outbound re-injection — self-replicating prompt (outbound only)
        if direction == Direction::Outbound {
            for (rule_id, pattern) in OUTBOUND_REINJECTION_PATTERNS.iter() {
                if pattern.is_match(payload) {
                    return self.build(direction, session_id, "OUTBOUND_REINJECTION_PAYLOAD", rule_id,
                        Severity::Critical, 0.91, &payload_hash, "sentinel/outbound_reinjection");
                }
            }
        }

        for (rule_id, pattern) in BLOCKLIST_PATTERNS.iter() {
            if pattern.is_match(payload) {
                return self.build(direction, session_id, "BLOCKLIST_MATCH", rule_id,
                    Severity::High, 0.90, &payload_hash, "sentinel/blocklist");
            }
        }

        for (rule_id, pattern) in INJECTION_PATTERNS.iter() {
            if pattern.is_match(payload) {
                return self.build(direction, session_id, "INJECTION_ATTEMPT", rule_id,
                    Severity::High, 0.88, &payload_hash, "sentinel/injection_detection");
            }
        }

        for (rule_id, pattern) in ENCODING_PATTERNS.iter() {
            if pattern.is_match(payload) {
                return self.build(direction, session_id, "ENCODING_ANOMALY", rule_id,
                    Severity::Medium, 0.75, &payload_hash, "sentinel/encoding_anomaly");
            }
        }

        self.clean(direction, session_id, &payload_hash)
    }

    fn detect_zero_width(&self, payload: &str) -> bool {
        const ZW: [char; 6] = [
            '\u{200B}', '\u{200C}', '\u{200D}',
            '\u{2060}', '\u{FEFF}', '\u{00AD}',
        ];
        payload.chars().any(|c| ZW.contains(&c))
    }

    // Expanded homoglyph detection: Cyrillic, Greek, Arabic, Hebrew, Thai
    // Intel (March 2026): multilingual semantic tricks across many scripts
    fn detect_homoglyphs(&self, payload: &str) -> bool {
        let has_ascii    = payload.chars().any(|c| c.is_ascii_alphabetic());
        let has_cyrillic = payload.chars().any(|c| matches!(c as u32, 0x0400..=0x04FF));
        let has_greek    = payload.chars().any(|c| matches!(c as u32, 0x0370..=0x03FF));
        let has_arabic   = payload.chars().any(|c| matches!(c as u32, 0x0600..=0x06FF));
        let has_hebrew   = payload.chars().any(|c| matches!(c as u32, 0x0590..=0x05FF));
        let has_thai     = payload.chars().any(|c| matches!(c as u32, 0x0E00..=0x0E7F));
        let mixed_script = has_cyrillic || has_greek || has_arabic || has_hebrew || has_thai;
        has_ascii && mixed_script
    }

    #[allow(clippy::too_many_arguments, clippy::nonminimal_bool)]
    fn build(
        &self, direction: Direction, session_id: &str,
        violation: &str, rule_id: &str,
        severity: Severity, confidence: f32,
        payload_hash: &str, const_ref: &str,
    ) -> GovernanceSignal {
        let mut sig = SignalBuilder::new(SignalSource::Sentinel, direction, session_id)
            .violation(violation, rule_id)
            .severity(severity, confidence)
            .payload_hash(payload_hash)
            .constitutional_ref(const_ref)
            .build();
        self.attach_crypto(&mut sig);
        sig
    }

    fn clean(&self, direction: Direction, session_id: &str, payload_hash: &str) -> GovernanceSignal {
        let mut sig = SignalBuilder::new(SignalSource::Sentinel, direction, session_id)
            .payload_hash(payload_hash)
            .build();
        self.attach_crypto(&mut sig);
        sig
    }

    fn attach_crypto(&self, signal: &mut GovernanceSignal) {
        let canonical = signal.canonical();
        signal.previous_hash = Some(self.crypto.get_latest_hash());
        signal.current_hash = Some(self.crypto.extend_chain(&canonical));
        signal.signature = Some(self.crypto.sign(canonical.as_bytes()));
    }
}
