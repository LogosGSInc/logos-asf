//! LOGOS Governance Systems Inc. — Provider Execution Capability (v3)
//!
//! v3 closes the seven self-contained defects the authority-model review found
//! in v2. All are properties v2's tests did not encode, therefore did not prove:
//!
//!   1. principal + authority now CHECKED at consume (v2 signed them, never
//!      verified the presenter — a capability-theft hole).
//!   2. max_uses now SIGNED (v2 left an authority field outside the signature).
//!   3. expiry uses >= (v2's > left the token valid at exactly expires_at).
//!   4. record_decision is FALLIBLE -> Result (v2's String could not express
//!      persistence failure, so "recorded iff authorized" was unfalsifiable).
//!   5. decision IDEMPOTENCY per (gov_tx_id, authority): identical retry returns
//!      the existing decision; conflicting scope errors (v2 minted two).
//!   6. issuance is ONE-LOCK atomic across decision-mark + capability-insert
//!      (v2 used two guards; a panic between them stranded state).
//!   7. field VALIDATION rejects empties and non-positive TTL (v2 signed empties).
//!
//! record_decision is pub(crate): only in-crate authority (HAAP) may write the
//! ledger. External holders of a CapabilityStore cannot manufacture decisions.

use chrono::{DateTime, Duration, Utc};
use parking_lot::RwLock;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;

use crate::crypto::CryptoEngine;

pub const AUTHORITY_PROVIDER_EXECUTE: &str = "provider.execute";

// ═══ ERRORS ════════════════════════════════════════════════════════════════

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CapabilityError {
    /// A required field was empty. Carries the field name.
    EmptyField(&'static str),
    /// TTL configured <= 0.
    InvalidTtl,
    /// Same gov_tx_id + authority already has a decision with DIFFERENT scope.
    TransactionScopeConflict,
    /// Authority string was not the expected provider.execute.
    WrongAuthority,
}

// ═══ DECISION LEDGER ═══════════════════════════════════════════════════════

/// Input to record_decision. A struct (not positional args) so scope is named,
/// validated as a unit, and extensible without churning call sites.
#[derive(Debug, Clone)]
pub struct DecisionRequest {
    pub gov_tx_id: String,
    pub session_id: String,
    pub principal_fingerprint: String,
    pub authority: String,
    pub backend: String,
    pub model: String,
    pub action_class: String,
    pub sentinel_verdict_id: String,
    pub policy_hash: String,
    /// Which authorization path produced this (e.g. "BelowRiskThreshold",
    /// "IntentTokenVerified"). Persisted so provenance is auditable; the
    /// wrapper fills it from the HaapVerdict.
    pub authorization_basis: String,
    pub agency: String,
    pub drs: u8,
}

impl DecisionRequest {
    fn validate(&self) -> Result<(), CapabilityError> {
        macro_rules! nonempty {
            ($f:expr, $name:literal) => {
                if $f.trim().is_empty() { return Err(CapabilityError::EmptyField($name)); }
            };
        }
        nonempty!(self.gov_tx_id, "gov_tx_id");
        nonempty!(self.session_id, "session_id");
        nonempty!(self.principal_fingerprint, "principal_fingerprint");
        nonempty!(self.backend, "backend");
        nonempty!(self.model, "model");
        nonempty!(self.action_class, "action_class");
        nonempty!(self.sentinel_verdict_id, "sentinel_verdict_id");
        nonempty!(self.policy_hash, "policy_hash");
        if self.authority != AUTHORITY_PROVIDER_EXECUTE {
            return Err(CapabilityError::WrongAuthority);
        }
        Ok(())
    }
    /// The scope that must match for an idempotent retry to be accepted.
    fn same_scope(&self, d: &Decision) -> bool {
        d.session_id == self.session_id
            && d.principal_fingerprint == self.principal_fingerprint
            && d.backend == self.backend
            && d.model == self.model
            && d.action_class == self.action_class
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Decision {
    pub decision_id: String,
    pub gov_tx_id: String,
    pub session_id: String,
    pub principal_fingerprint: String,
    pub authority: String,
    pub backend: String,
    pub model: String,
    pub action_class: String,
    pub sentinel_verdict_id: String,
    pub policy_hash: String,
    pub authorization_basis: String,
    pub agency: String,
    pub drs: u8,
    pub authorized_at: DateTime<Utc>,
    pub issued: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IssueOutcome {
    Issued(CapabilityToken),
    DecisionNotFound,
    AlreadyIssued,
}

// ═══ CAPABILITY TOKEN ══════════════════════════════════════════════════════

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityToken {
    pub token_id: String,
    pub haap_decision_id: String,
    pub gov_tx_id: String,
    pub session_id: String,
    pub principal_fingerprint: String,
    pub authority: String,
    pub backend: String,
    pub model: String,
    pub action_class: String,
    pub sentinel_verdict_id: String,
    pub policy_hash: String,
    pub issued_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
    pub max_uses: u32,
    pub use_count: u32,
    pub signature: String,
}

impl CapabilityToken {
    /// Canonical signed form. Every authority-bearing field is present —
    /// INCLUDING max_uses (changing it changes authority). use_count is the
    /// only mutable field and is deliberately excluded.
    pub fn canonical(&self) -> String {
        format!(
            "{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
            self.token_id,
            self.haap_decision_id,
            self.gov_tx_id,
            self.session_id,
            self.principal_fingerprint,
            self.authority,
            self.backend,
            self.model,
            self.action_class,
            self.sentinel_verdict_id,
            self.policy_hash,
            self.issued_at.timestamp(),
            self.expires_at.timestamp(),
            self.max_uses,
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConsumeOutcome {
    Authorized,
    NotFound,
    SignatureInvalid,
    AlreadyConsumed,
    Expired,
    TransactionMismatch,
    SessionMismatch,
    PrincipalMismatch,
    AuthorityMismatch,
    BackendMismatch,
    ModelMismatch,
}

impl ConsumeOutcome {
    pub fn authorized(&self) -> bool { matches!(self, ConsumeOutcome::Authorized) }
    pub fn as_audit_str(&self) -> &'static str {
        match self {
            ConsumeOutcome::Authorized          => "CAPABILITY_CONSUMED",
            ConsumeOutcome::NotFound            => "CAPABILITY_NOT_FOUND",
            ConsumeOutcome::SignatureInvalid    => "CAPABILITY_SIGNATURE_INVALID",
            ConsumeOutcome::AlreadyConsumed     => "CAPABILITY_REPLAY_REJECTED",
            ConsumeOutcome::Expired             => "CAPABILITY_EXPIRED",
            ConsumeOutcome::TransactionMismatch => "CAPABILITY_TX_MISMATCH",
            ConsumeOutcome::SessionMismatch     => "CAPABILITY_SESSION_MISMATCH",
            ConsumeOutcome::PrincipalMismatch   => "CAPABILITY_PRINCIPAL_MISMATCH",
            ConsumeOutcome::AuthorityMismatch   => "CAPABILITY_AUTHORITY_MISMATCH",
            ConsumeOutcome::BackendMismatch     => "CAPABILITY_BACKEND_MISMATCH",
            ConsumeOutcome::ModelMismatch       => "CAPABILITY_MODEL_MISMATCH",
        }
    }
}

/// What the adapter presents at consume. Now includes principal + authority so
/// consume verifies WHO is presenting, not just what scope is claimed.
pub struct PresentedBinding<'a> {
    pub token_id: &'a str,
    pub gov_tx_id: &'a str,
    pub session_id: &'a str,
    pub principal_fingerprint: &'a str,
    pub authority: &'a str,
    pub backend: &'a str,
    pub model: &'a str,
}

// ═══ STORE — one lock over all three maps ══════════════════════════════════

struct CapabilityState {
    decisions: HashMap<String, Decision>,
    capabilities: HashMap<String, CapabilityToken>,
    /// (gov_tx_id|authority) -> decision_id, for idempotency + conflict.
    decision_by_tx: HashMap<String, String>,
}

#[derive(Clone)]
pub struct CapabilityStore {
    state: Arc<RwLock<CapabilityState>>,
    crypto: Arc<CryptoEngine>,
    default_ttl_secs: i64,
}

fn tx_key(gov_tx_id: &str, authority: &str) -> String {
    format!("{}|{}", gov_tx_id, authority)
}

impl CapabilityStore {
    pub fn new(crypto: Arc<CryptoEngine>) -> Self {
        Self {
            state: Arc::new(RwLock::new(CapabilityState {
                decisions: HashMap::new(),
                capabilities: HashMap::new(),
                decision_by_tx: HashMap::new(),
            })),
            crypto,
            default_ttl_secs: 30,
        }
    }

    /// TTL must be positive. Fallible so a misconfiguration fails loud.
    pub fn with_ttl_secs(mut self, ttl: i64) -> Result<Self, CapabilityError> {
        if ttl <= 0 { return Err(CapabilityError::InvalidTtl); }
        self.default_ttl_secs = ttl;
        Ok(self)
    }

    /// Persist an authorized decision. pub(crate): only in-crate authority may
    /// write the ledger. Fallible, validated, idempotent per (gov_tx_id,authority).
    ///
    ///   - identical retry (same scope)      -> Ok(existing decision_id)
    ///   - same tx+authority, different scope -> Err(TransactionScopeConflict)
    ///   - empty field / wrong authority      -> Err(...)
    pub(crate) fn record_decision(&self, req: DecisionRequest)
        -> Result<String, CapabilityError>
    {
        req.validate()?;
        let key = tx_key(&req.gov_tx_id, &req.authority);

        let mut st = self.state.write();

        if let Some(existing_id) = st.decision_by_tx.get(&key).cloned() {
            let existing = st.decisions.get(&existing_id)
                .expect("index/decision invariant");
            if req.same_scope(existing) {
                return Ok(existing_id); // idempotent retry
            }
            return Err(CapabilityError::TransactionScopeConflict);
        }

        let decision_id = format!("DEC-{}", uuid::Uuid::new_v4().simple());
        let decision = Decision {
            decision_id: decision_id.clone(),
            gov_tx_id: req.gov_tx_id,
            session_id: req.session_id,
            principal_fingerprint: req.principal_fingerprint,
            authority: req.authority,
            backend: req.backend,
            model: req.model,
            action_class: req.action_class,
            sentinel_verdict_id: req.sentinel_verdict_id,
            policy_hash: req.policy_hash,
            authorization_basis: req.authorization_basis,
            agency: req.agency,
            drs: req.drs,
            authorized_at: Utc::now(),
            issued: false,
        };
        st.decisions.insert(decision_id.clone(), decision);
        st.decision_by_tx.insert(key, decision_id.clone());
        Ok(decision_id)
    }

    /// Issue a capability FROM a decision. Scope read from the decision; caller
    /// scope never consulted. Decision-mark + capability-insert under ONE guard.
    pub fn issue_after_authorization(&self, decision_id: &str) -> IssueOutcome {
        let mut st = self.state.write();

        let decision = match st.decisions.get(decision_id) {
            Some(d) => d.clone(),
            None => return IssueOutcome::DecisionNotFound,
        };
        if decision.issued {
            return IssueOutcome::AlreadyIssued;
        }

        let token_id = format!("CAP-{}", uuid::Uuid::new_v4().simple());
        let issued_at = Utc::now();
        let expires_at = issued_at + Duration::seconds(self.default_ttl_secs);

        let mut token = CapabilityToken {
            token_id: token_id.clone(),
            haap_decision_id: decision.decision_id.clone(),
            gov_tx_id: decision.gov_tx_id.clone(),
            session_id: decision.session_id.clone(),
            principal_fingerprint: decision.principal_fingerprint.clone(),
            authority: decision.authority.clone(),
            backend: decision.backend.clone(),
            model: decision.model.clone(),
            action_class: decision.action_class.clone(),
            sentinel_verdict_id: decision.sentinel_verdict_id.clone(),
            policy_hash: decision.policy_hash.clone(),
            issued_at,
            expires_at,
            max_uses: 1,
            use_count: 0,
            signature: String::new(),
        };
        token.signature = self.crypto.sign(token.canonical().as_bytes());

        // Both writes under the same guard: mark issued AND insert capability.
        st.decisions.get_mut(decision_id).unwrap().issued = true;
        st.capabilities.insert(token_id, token.clone());
        IssueOutcome::Issued(token)
    }

    /// Atomic verify-and-burn. One write guard over the whole check-then-mark.
    pub fn consume(&self, p: &PresentedBinding) -> ConsumeOutcome {
        let mut st = self.state.write();
        let token = match st.capabilities.get_mut(p.token_id) {
            Some(t) => t,
            None => return ConsumeOutcome::NotFound,
        };

        // Authenticity first — over the STORED canonical form (covers max_uses).
        let canonical = token.canonical();
        if !self.crypto.verify(canonical.as_bytes(), &token.signature).unwrap_or(false) {
            return ConsumeOutcome::SignatureInvalid;
        }

        // Exhaustion (replay) before mutation.
        if token.use_count >= token.max_uses { return ConsumeOutcome::AlreadyConsumed; }
        // Expiry: valid strictly before expires_at.
        if Utc::now() >= token.expires_at { return ConsumeOutcome::Expired; }

        // Authority + WHO, then scope.
        if token.authority != AUTHORITY_PROVIDER_EXECUTE
            || token.authority != p.authority {
            return ConsumeOutcome::AuthorityMismatch;
        }
        if token.principal_fingerprint != p.principal_fingerprint {
            return ConsumeOutcome::PrincipalMismatch;
        }
        if token.gov_tx_id  != p.gov_tx_id  { return ConsumeOutcome::TransactionMismatch; }
        if token.session_id != p.session_id { return ConsumeOutcome::SessionMismatch; }
        if token.backend    != p.backend    { return ConsumeOutcome::BackendMismatch; }
        if token.model      != p.model      { return ConsumeOutcome::ModelMismatch; }

        token.use_count += 1;
        ConsumeOutcome::Authorized
    }

    pub fn prune_expired(&self) -> usize {
        let mut st = self.state.write();
        let before = st.capabilities.len();
        st.capabilities.retain(|_, t| Utc::now() < t.expires_at);
        before - st.capabilities.len()
    }

    // ── test-only introspection/tampering, to prove signed-field integrity ──
    #[cfg(test)]
    pub(crate) fn mutate_stored_token(&self, token_id: &str,
                                      f: impl FnOnce(&mut CapabilityToken)) {
        let mut st = self.state.write();
        if let Some(t) = st.capabilities.get_mut(token_id) { f(t); }
    }
}

// ═══ TESTS ═════════════════════════════════════════════════════════════════
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::thread;

    fn store() -> CapabilityStore {
        CapabilityStore::new(Arc::new(CryptoEngine::new("logos_capability_test_seed")))
    }

    fn req(tx: &str) -> DecisionRequest {
        DecisionRequest {
            gov_tx_id: tx.into(),
            session_id: "sess1".into(),
            principal_fingerprint: "fpADMIN00000000".into(),
            authority: AUTHORITY_PROVIDER_EXECUTE.into(),
            backend: "groq".into(),
            model: "llama-3.3-70b-versatile".into(),
            action_class: "chat".into(),
            sentinel_verdict_id: "sv1".into(),
            policy_hash: "policy_v1".into(),
            authorization_basis: "BelowRiskThreshold".into(),
            agency: "L2".into(),
            drs: 20,
        }
    }

    fn cap(s: &CapabilityStore) -> CapabilityToken {
        let did = s.record_decision(req("tx1")).expect("record");
        match s.issue_after_authorization(&did) {
            IssueOutcome::Issued(c) => c,
            o => panic!("expected Issued, got {:?}", o),
        }
    }

    fn good_binding<'a>(t: &'a CapabilityToken) -> PresentedBinding<'a> {
        PresentedBinding {
            token_id: &t.token_id, gov_tx_id: &t.gov_tx_id,
            session_id: &t.session_id, principal_fingerprint: &t.principal_fingerprint,
            authority: &t.authority, backend: &t.backend, model: &t.model,
        }
    }

    // ── existing properties, retained ──
    #[test] fn happy_path_consumes_once() {
        let s = store(); let c = cap(&s);
        assert_eq!(s.consume(&good_binding(&c)), ConsumeOutcome::Authorized);
    }
    #[test] fn replay_rejected() {
        let s = store(); let c = cap(&s);
        assert_eq!(s.consume(&good_binding(&c)), ConsumeOutcome::Authorized);
        assert_eq!(s.consume(&good_binding(&c)), ConsumeOutcome::AlreadyConsumed);
    }
    #[test] fn backend_mismatch() {
        let s = store(); let c = cap(&s);
        let mut b = good_binding(&c); b.backend = "anthropic";
        assert_eq!(s.consume(&b), ConsumeOutcome::BackendMismatch);
    }
    #[test] fn model_mismatch() {
        let s = store(); let c = cap(&s);
        let mut b = good_binding(&c); b.model = "gpt-4o";
        assert_eq!(s.consume(&b), ConsumeOutcome::ModelMismatch);
    }
    #[test] fn transaction_mismatch() {
        let s = store(); let c = cap(&s);
        let mut b = good_binding(&c); b.gov_tx_id = "tx2";
        assert_eq!(s.consume(&b), ConsumeOutcome::TransactionMismatch);
    }
    #[test] fn issuance_requires_real_decision() {
        assert_eq!(store().issue_after_authorization("DEC-nope"),
                   IssueOutcome::DecisionNotFound);
    }
    #[test] fn scope_from_decision_not_caller() {
        let s = store(); let c = cap(&s);
        assert_eq!(c.backend, "groq");
        assert_eq!(c.model, "llama-3.3-70b-versatile");
        assert!(!c.haap_decision_id.is_empty());
    }

    // ── NEW: session mismatch ──
    #[test] fn session_mismatch() {
        let s = store(); let c = cap(&s);
        let mut b = good_binding(&c); b.session_id = "sessX";
        assert_eq!(s.consume(&b), ConsumeOutcome::SessionMismatch);
    }

    // ── NEW: principal mismatch (the capability-theft fix) ──
    #[test] fn principal_mismatch_rejected() {
        let s = store(); let c = cap(&s);
        let mut b = good_binding(&c); b.principal_fingerprint = "fpATTACKER00000";
        assert_eq!(s.consume(&b), ConsumeOutcome::PrincipalMismatch);
    }

    // ── NEW: authority mismatch ──
    #[test] fn authority_mismatch_rejected() {
        let s = store(); let c = cap(&s);
        let mut b = good_binding(&c); b.authority = "provider.admin";
        assert_eq!(s.consume(&b), ConsumeOutcome::AuthorityMismatch);
    }

    // ── NEW: signature corruption ──
    #[test] fn corrupted_signature_rejected() {
        let s = store(); let c = cap(&s);
        s.mutate_stored_token(&c.token_id, |t| t.signature = "deadbeef".into());
        assert_eq!(s.consume(&good_binding(&c)), ConsumeOutcome::SignatureInvalid);
    }

    // ── NEW: max_uses tampering is caught because max_uses is signed ──
    #[test] fn max_uses_tampering_rejected() {
        let s = store(); let c = cap(&s);
        // Inflate stored max_uses without re-signing. canonical() now differs
        // from what was signed -> signature verification must fail.
        s.mutate_stored_token(&c.token_id, |t| t.max_uses = 1000);
        assert_eq!(s.consume(&good_binding(&c)), ConsumeOutcome::SignatureInvalid);
    }

    // ── NEW: expiry uses >= ──
    #[test] fn expired_token_rejected() {
        let s = store(); let c = cap(&s);
        s.mutate_stored_token(&c.token_id, |t| {
            t.expires_at = Utc::now() - Duration::seconds(1);
            // re-sign so it's the EXPIRY, not the signature, that rejects
            t.signature = s.crypto.sign(t.canonical().as_bytes());
        });
        assert_eq!(s.consume(&good_binding(&c)), ConsumeOutcome::Expired);
    }

    // ── NEW: TTL validation ──
    #[test] fn nonpositive_ttl_rejected() {
        let c = Arc::new(CryptoEngine::new("logos_capability_test_seed"));
        assert_eq!(CapabilityStore::new(c.clone()).with_ttl_secs(0).err(),
                   Some(CapabilityError::InvalidTtl));
        assert_eq!(CapabilityStore::new(c).with_ttl_secs(-5).err(),
                   Some(CapabilityError::InvalidTtl));
    }

    // ── NEW: field validation ──
    #[test] fn empty_fields_rejected() {
        let s = store();
        let mut r = req("tx1"); r.model = "".into();
        assert_eq!(s.record_decision(r).err(), Some(CapabilityError::EmptyField("model")));
        let mut r2 = req("tx1"); r2.gov_tx_id = "  ".into();
        assert_eq!(s.record_decision(r2).err(), Some(CapabilityError::EmptyField("gov_tx_id")));
    }
    #[test] fn wrong_authority_rejected() {
        let s = store();
        let mut r = req("tx1"); r.authority = "provider.admin".into();
        assert_eq!(s.record_decision(r).err(), Some(CapabilityError::WrongAuthority));
    }

    // ── NEW: decision idempotency ──
    #[test] fn identical_retry_returns_same_decision() {
        let s = store();
        let a = s.record_decision(req("tx1")).unwrap();
        let b = s.record_decision(req("tx1")).unwrap(); // identical scope
        assert_eq!(a, b, "identical retry must be idempotent");
    }
    #[test] fn conflicting_backend_same_tx_errors() {
        let s = store();
        s.record_decision(req("tx1")).unwrap();
        let mut r = req("tx1"); r.backend = "openai".into(); r.model = "gpt-4o".into();
        assert_eq!(s.record_decision(r).err(),
                   Some(CapabilityError::TransactionScopeConflict));
    }
    #[test] fn conflicting_session_same_tx_errors() {
        let s = store();
        s.record_decision(req("tx1")).unwrap();
        let mut r = req("tx1"); r.session_id = "sessOTHER".into();
        assert_eq!(s.record_decision(r).err(),
                   Some(CapabilityError::TransactionScopeConflict));
    }

    // ── retained: the primary concurrency proofs ──
    #[test] fn concurrent_consume_is_single_use() {
        let s = store(); let c = cap(&s);
        const N: usize = 64;
        let ok = Arc::new(AtomicUsize::new(0));
        let rej = Arc::new(AtomicUsize::new(0));
        let mut h = Vec::new();
        for _ in 0..N {
            let (s, c, ok, rej) = (s.clone(), c.clone(), ok.clone(), rej.clone());
            h.push(thread::spawn(move || {
                let b = PresentedBinding {
                    token_id: &c.token_id, gov_tx_id: &c.gov_tx_id,
                    session_id: &c.session_id, principal_fingerprint: &c.principal_fingerprint,
                    authority: &c.authority, backend: &c.backend, model: &c.model,
                };
                match s.consume(&b) {
                    ConsumeOutcome::Authorized => { ok.fetch_add(1, Ordering::SeqCst); }
                    _ => { rej.fetch_add(1, Ordering::SeqCst); }
                }
            }));
        }
        for x in h { x.join().unwrap(); }
        assert_eq!(ok.load(Ordering::SeqCst), 1);
        assert_eq!(rej.load(Ordering::SeqCst), N - 1);
    }
    #[test] fn concurrent_issuance_is_single_capability() {
        let s = store();
        let did = s.record_decision(req("tx1")).unwrap();
        const N: usize = 64;
        let iss = Arc::new(AtomicUsize::new(0));
        let den = Arc::new(AtomicUsize::new(0));
        let mut h = Vec::new();
        for _ in 0..N {
            let (s, did, iss, den) = (s.clone(), did.clone(), iss.clone(), den.clone());
            h.push(thread::spawn(move || {
                match s.issue_after_authorization(&did) {
                    IssueOutcome::Issued(_) => { iss.fetch_add(1, Ordering::SeqCst); }
                    _ => { den.fetch_add(1, Ordering::SeqCst); }
                }
            }));
        }
        for x in h { x.join().unwrap(); }
        assert_eq!(iss.load(Ordering::SeqCst), 1);
        assert_eq!(den.load(Ordering::SeqCst), N - 1);
    }

    // ── NEW: concurrent idempotent record — one decision under contention ──
    #[test] fn concurrent_identical_record_is_single_decision() {
        let s = store();
        const N: usize = 64;
        let mut h = Vec::new();
        for _ in 0..N {
            let s = s.clone();
            h.push(thread::spawn(move || s.record_decision(req("tx1")).unwrap()));
        }
        let ids: std::collections::HashSet<String> =
            h.into_iter().map(|x| x.join().unwrap()).collect();
        assert_eq!(ids.len(), 1, "all identical retries must collapse to one decision");
    }
}
