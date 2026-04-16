use crate::{
    crypto::CryptoEngine,
    governance_signal::{Direction, GovernanceSignal, Severity, SignalBuilder, SignalSource},
};
use once_cell::sync::Lazy;
use regex::Regex;
use std::sync::Arc;

// L1: High-confidence, low-false-positive patterns.
// Keep these surgical. Nuanced logic belongs in Corridor/OverWatch.
static INJECTION_PATTERNS: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        ("SENT-001", Regex::new(r"(?i)\b(ignore previous instructions|disregard your training|forget your guidelines)\b").unwrap()),
        ("SENT-002", Regex::new(r"(?i)\b(you are now|act as if you are|pretend you are|you have no restrictions)\b").unwrap()),
        ("SENT-003", Regex::new(r"(?i)\b(DAN|do anything now|jailbreak|bypass your)\b").unwrap()),

        // Prompt / system instruction extraction (requires an action verb to reduce false positives)
        ("SENT-004", Regex::new(r"(?ix)\b(?:reveal|show|print|dump|display|leak|extract)\b.{0,40}\b(?:system\s+prompt|developer\s+message|hidden\s+instructions|internal\s+rules)\b").unwrap()),
        ("SENT-004B", Regex::new(r"(?ix)\bwhat\s+are\s+your\s+(?:system|developer|hidden)\s+(?:instructions|prompt|rules)\b").unwrap()),
        ("SENT-005", Regex::new(r"(?i)\b(malware|ransomware|trojan|rootkit|keylogger)\b").unwrap()),
        ("SENT-006", Regex::new(r"(?i)\b(ddos|botnet|exploit\s+kit|zero.?day|0day|vulnerability)\b").unwrap()),
        ("SENT-007", Regex::new(r"(?i)\b(phishing|credential\s+harvest|spear.?phish)\b").unwrap()),

        // Tool misuse / execution steering (explicit, high confidence)
        ("SENT-008", Regex::new(r"(?ix)\b(?:run|execute|exec(?:ute)?|eval|system|powershell|bash|sh|cmd|terminal)\b.{0,40}\b(?:code|command|script|shell|curl|wget|pip|npm|apt(?:-get)?|chmod|chown|rm\s+-rf)\b").unwrap()),
        ("SENT-008B", Regex::new(r#"(?ix)\b(?:exec|eval|system)\s*\(\s*[\x27\x22]"#).unwrap()),
        ("SENT-008C", Regex::new(r"(?ix)\b(?:os\.system|subprocess\.(?:run|popen)|Runtime\.exec)\b").unwrap()),

        // Authority spoofing / override attempts (explicit)
        ("SENT-009", Regex::new(r"(?ix)\b(?:override|bypass|disable|ignore|disregard|break|remove)\b.{0,40}\b(?:safety|guardrails|policy|rules|filters|constraints)\b").unwrap()),
        ("SENT-009B", Regex::new(r"(?ix)\b(?:as\s+(?:your|the)\s+)?(?:creator|developer|admin|root|system)\b.{0,30}\b(?:i\s+(?:order|command)|you\s+must|override)\b").unwrap()),
        // Polite ignore variants
        ("SENT-001B", Regex::new(r"(?i)\b(please\s+ignore|kindly\s+ignore|disregard\s+all\s+prior|ignore\s+all\s+prior)\b").unwrap()),
        // Spaced / punctuated / underscore obfuscation
        ("SENT-001C", Regex::new(r"(?i)i[\s._-]*g[\s._-]*n[\s._-]*o[\s._-]*r[\s._-]*e[\s._-]+p[\s._-]*r[\s._-]*e[\s._-]*v[\s._-]*i[\s._-]*o[\s._-]*u[\s._-]*s").unwrap()),
        // CamelCase / underscore variants
        ("SENT-001D", Regex::new(r"(?i)(ignore_previous|IgnorePrevious|IGNOREPREVIOUS)").unwrap()),
        // Reveal your instructions
        ("SENT-004C", Regex::new(r"(?i)\breveal\b.{0,30}\b(instructions|rules|config|constitution)\b").unwrap()),
        // Developer mode / bypass restrictions jailbreak
        ("SENT-003B", Regex::new(r"(?i)\b(developer\s+mode|dev\s+mode|bypass\s+all|no\s+restrictions|without\s+restrictions|remove\s+all\s+restrictions)\b").unwrap()),
        // Simulate AI with no filters
        ("SENT-003C", Regex::new(r"(?i)\bsimulate\b.{0,30}\b(no\s+filters|no\s+restrictions|without\s+guidelines)\b").unwrap()),
        // call tool: bash / call tool: X
        ("SENT-008D", Regex::new(r"(?i)\bcall\s+tool\s*[:=]\s*\w+").unwrap()),
        ("SENT-009C", Regex::new(r"(?ix)\byou\s+are\s+(?:now\s+)?(?:root|admin|developer|system|creator)\b").unwrap()),
    ]
});

static BLOCKLIST_PATTERNS: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        ("SENT-BL-001", Regex::new(r"(?i)\bsudo\b").unwrap()),
        (
            "SENT-BL-002",
            Regex::new(r"(?i)\bpassword\s*[:=]\s*\S+").unwrap(),
        ),
        (
            "SENT-BL-003",
            Regex::new(r"(?i)\bapi[_\s]?key\s*[:=]\s*\S+").unwrap(),
        ),
    ]
});

static ENCODING_PATTERNS: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        (
            "SENT-ENC-001",
            Regex::new(r"(?:0x[0-9a-fA-F]{2}\s*){8,}").unwrap(),
        ),
        (
            "SENT-ENC-002",
            Regex::new(r"(?:%[0-9a-fA-F]{2}){6,}").unwrap(),
        ),
    ]
});

#[derive(Debug)]
pub struct Sentinel {
    crypto: Arc<CryptoEngine>,
    max_payload_bytes: usize,
}

impl Sentinel {
    pub fn new(crypto: Arc<CryptoEngine>) -> Self {
        // Force compile at init (fail-fast at startup if any regex is invalid).
        let _ = &*INJECTION_PATTERNS;
        let _ = &*BLOCKLIST_PATTERNS;
        let _ = &*ENCODING_PATTERNS;
        Self {
            crypto,
            max_payload_bytes: 32_768,
        }
    }

    pub fn inspect(
        &self,
        payload: &str,
        direction: Direction,
        session_id: &str,
    ) -> GovernanceSignal {
        let payload_hash = CryptoEngine::compute_hash(payload);

        if payload.len() > self.max_payload_bytes {
            return self.build(
                direction,
                session_id,
                "SIZE_EXCEEDED",
                "SENT-SIZE-001",
                Severity::Low,
                0.70,
                &payload_hash,
                "sentinel/size_limit",
            );
        }

        if self.detect_zero_width(payload) {
            return self.build(
                direction,
                session_id,
                "ZERO_WIDTH_CHARS",
                "SENT-ZW-001",
                Severity::High,
                0.90,
                &payload_hash,
                "sentinel/encoding_anomaly",
            );
        }

        if self.detect_homoglyphs(payload) {
            return self.build(
                direction,
                session_id,
                "HOMOGLYPH_OBFUSCATION",
                "SENT-HG-001",
                Severity::High,
                0.85,
                &payload_hash,
                "sentinel/encoding_anomaly",
            );
        }

        // --- L33tspeak normalization + rescan ---

        if self.is_exfil_attempt(payload) {
            return self.build(
                direction,
                session_id,
                "MODEL_EXFIL",
                "SENT-EXFIL-001",
                Severity::High,
                0.92,
                &payload_hash,
                "sentinel/prompt_exfil",
            );
        }
        let normalized = self.normalize_l33t(payload);
        if normalized != payload.to_lowercase() {
            for (rule_id, pattern) in INJECTION_PATTERNS.iter() {
                if pattern.is_match(&normalized) {
                    return self.build(
                        direction,
                        session_id,
                        "L33T_OBFUSCATION",
                        rule_id,
                        Severity::High,
                        0.88,
                        &payload_hash,
                        "sentinel/encoding_anomaly",
                    );
                }
            }
        }

        // --- Base64 decode + rescan ---
        if let Some(decoded) = self.try_decode_base64(payload) {
            for (rule_id, pattern) in INJECTION_PATTERNS.iter() {
                if pattern.is_match(&decoded) {
                    return self.build(
                        direction,
                        session_id,
                        "BASE64_INJECTION",
                        rule_id,
                        Severity::High,
                        0.92,
                        &payload_hash,
                        "sentinel/encoding_anomaly",
                    );
                }
            }
        }

                for (rule_id, pattern) in BLOCKLIST_PATTERNS.iter() {
            if pattern.is_match(payload) {
                return self.build(
                    direction,
                    session_id,
                    "BLOCKLIST_MATCH",
                    rule_id,
                    Severity::High,
                    0.90,
                    &payload_hash,
                    "sentinel/blocklist",
                );
            }
        }

        for (rule_id, pattern) in INJECTION_PATTERNS.iter() {
            if pattern.is_match(payload) {
                // Map certain classes for clarity in logs without adding semantic reasoning.
                let class = match *rule_id {
                    "SENT-008" | "SENT-008B" | "SENT-008C" => "TOOL_MISUSE",
                    "SENT-009" | "SENT-009B" | "SENT-009C" => "AUTHORITY_SPOOFING",
                    "SENT-004" | "SENT-004B" => "MODEL_EXTRACTION",
                    _ => "INJECTION_ATTEMPT",
                };
                return self.build(
                    direction,
                    session_id,
                    class,
                    rule_id,
                    Severity::High,
                    0.88,
                    &payload_hash,
                    "sentinel/injection_detection",
                );
            }
        }

        for (rule_id, pattern) in ENCODING_PATTERNS.iter() {
            if pattern.is_match(payload) {
                return self.build(
                    direction,
                    session_id,
                    "ENCODING_ANOMALY",
                    rule_id,
                    Severity::Medium,
                    0.75,
                    &payload_hash,
                    "sentinel/encoding_anomaly",
                );
            }
        }

        self.clean(direction, session_id, &payload_hash)
    }

    fn detect_zero_width(&self, payload: &str) -> bool {
        const ZW: [char; 6] = [
            '\u{200B}', '\u{200C}', '\u{200D}', '\u{2060}', '\u{FEFF}', '\u{00AD}',
        ];
        payload.chars().any(|c| ZW.contains(&c))
    }

    #[allow(clippy::too_many_arguments, clippy::nonminimal_bool)]
    fn detect_homoglyphs(&self, payload: &str) -> bool {
        let has_ascii = payload.chars().any(|c| c.is_ascii_alphabetic());
        let has_cyrillic = payload.chars().any(|c| matches!(c as u32, 0x0400..=0x04FF));
        let has_greek = payload.chars().any(|c| matches!(c as u32, 0x0370..=0x03FF));
        (has_ascii && has_cyrillic) || (has_ascii && has_greek)
    }

    #[allow(clippy::too_many_arguments, clippy::nonminimal_bool)]
    fn build(
        &self,
        direction: Direction,
        session_id: &str,
        violation: &str,
        rule_id: &str,
        severity: Severity,
        confidence: f32,
        payload_hash: &str,
        const_ref: &str,
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

    fn clean(
        &self,
        direction: Direction,
        session_id: &str,
        payload_hash: &str,
    ) -> GovernanceSignal {
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

    fn is_exfil_attempt(&self, payload: &str) -> bool {
        let lower = payload.to_ascii_lowercase();
        lower.contains("system prompt")
            || lower.contains("internal instructions")
            || lower.contains("hidden instructions")
            || lower.contains("developer message")
            || lower.contains("api keys")
            || lower.contains("api key")
            || lower.contains("your configuration")
            || lower.contains("dump all secrets")
            || lower.contains("reveal all secrets")
            || lower.contains("configuration keys")
    }
    fn normalize_l33t(&self, input: &str) -> String {
        input.to_lowercase()
            .replace('1', "i")
            .replace('3', "e")
            .replace('4', "a")
            .replace('5', "s")
            .replace('0', "o")
            .replace('7', "t")
            .replace('$', "s")
            .replace('@', "a")
    }

    fn try_decode_base64(&self, input: &str) -> Option<String> {
        let trimmed = input.trim();
        // Only attempt if it looks like a pure base64 blob
        if trimmed.len() < 20 {
            return None;
        }
        let looks_b64 = trimmed.chars().all(|c| {
            c.is_ascii_alphanumeric() || c == '+' || c == '/' || c == '='
        });
        if !looks_b64 {
            return None;
        }
        use base64::{Engine as _, engine::general_purpose};
        general_purpose::STANDARD
            .decode(trimmed)
            .ok()
            .and_then(|bytes| String::from_utf8(bytes).ok())
    }

}
