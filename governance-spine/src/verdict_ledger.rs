use chrono::{DateTime, Utc};
use parking_lot::RwLock;
use std::collections::HashMap;
use std::sync::Arc;

use crate::governance_signal::{Direction, GovernanceSignal, Severity};

#[derive(Debug, Clone)]
pub struct VerdictRecord {
    pub verdict_id: String,
    pub gov_tx_id: String,
    pub session_id: String,
    pub direction: Direction,
    pub violation_class: Option<String>,
    pub severity: Severity,
    pub confidence: f32,
    pub payload_hash: String,
    pub signal_signature: String,
    pub recorded_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ResolveOutcome {
    Found,
    NotFound,
    TransactionMismatch,
    SessionMismatch,
}

pub struct SentinelVerdictLedger {
    verdicts: Arc<RwLock<HashMap<String, VerdictRecord>>>,
}

impl SentinelVerdictLedger {
    pub fn new() -> Self {
        Self { verdicts: Arc::new(RwLock::new(HashMap::new())) }
    }

    pub fn record(&self, gov_tx_id: &str, signal: &GovernanceSignal) -> String {
        let verdict_id = format!("SV-{}", uuid::Uuid::new_v4().simple());
        let record = VerdictRecord {
            verdict_id: verdict_id.clone(),
            gov_tx_id: gov_tx_id.to_string(),
            session_id: signal.session_id.clone(),
            direction: signal.direction.clone(),
            violation_class: signal.violation_class.clone(),
            severity: signal.severity.clone(),
            confidence: signal.confidence,
            payload_hash: signal.payload_hash.clone(),
            signal_signature: signal.signature.clone().unwrap_or_default(),
            recorded_at: Utc::now(),
        };
        self.verdicts.write().insert(verdict_id.clone(), record);
        verdict_id
    }

    pub fn resolve(&self, verdict_id: &str, gov_tx_id: &str, session_id: &str)
        -> (ResolveOutcome, Option<VerdictRecord>)
    {
        let guard = self.verdicts.read();
        match guard.get(verdict_id) {
            None => (ResolveOutcome::NotFound, None),
            Some(rec) => {
                if rec.gov_tx_id != gov_tx_id {
                    return (ResolveOutcome::TransactionMismatch, Some(rec.clone()));
                }
                if rec.session_id != session_id {
                    return (ResolveOutcome::SessionMismatch, Some(rec.clone()));
                }
                (ResolveOutcome::Found, Some(rec.clone()))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::governance_signal::{SignalBuilder, SignalSource};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::thread;

    fn approved_signal(session_id: &str) -> GovernanceSignal {
        SignalBuilder::new(SignalSource::Sentinel, Direction::Inbound, session_id)
            .payload_hash("deadbeef")
            .build()
    }

    #[test]
    fn record_then_resolve_matches() {
        let ledger = SentinelVerdictLedger::new();
        let sig = approved_signal("sess1");
        let vid = ledger.record("tx1", &sig);
        let (outcome, rec) = ledger.resolve(&vid, "tx1", "sess1");
        assert_eq!(outcome, ResolveOutcome::Found);
        assert_eq!(rec.unwrap().gov_tx_id, "tx1");
    }

    #[test]
    fn unknown_verdict_id_not_found() {
        let ledger = SentinelVerdictLedger::new();
        let (outcome, rec) = ledger.resolve("SV-fabricated", "tx1", "sess1");
        assert_eq!(outcome, ResolveOutcome::NotFound);
        assert!(rec.is_none());
    }

    #[test]
    fn transaction_mismatch_rejected() {
        let ledger = SentinelVerdictLedger::new();
        let sig = approved_signal("sess1");
        let vid = ledger.record("tx1", &sig);
        let (outcome, _) = ledger.resolve(&vid, "tx2", "sess1");
        assert_eq!(outcome, ResolveOutcome::TransactionMismatch);
    }

    #[test]
    fn session_mismatch_rejected() {
        let ledger = SentinelVerdictLedger::new();
        let sig = approved_signal("sess1");
        let vid = ledger.record("tx1", &sig);
        let (outcome, _) = ledger.resolve(&vid, "tx1", "sessOTHER");
        assert_eq!(outcome, ResolveOutcome::SessionMismatch);
    }

    #[test]
    fn concurrent_record_all_persist_distinctly() {
        let ledger = SentinelVerdictLedger::new();
        const N: usize = 64;
        let recorded = Arc::new(AtomicUsize::new(0));
        let mut handles = Vec::new();
        for i in 0..N {
            let ledger = SentinelVerdictLedger { verdicts: ledger.verdicts.clone() };
            let recorded = recorded.clone();
            handles.push(thread::spawn(move || {
                let sig = approved_signal(&format!("sess{i}"));
                let vid = ledger.record(&format!("tx{i}"), &sig);
                let (outcome, _) = ledger.resolve(&vid, &format!("tx{i}"), &format!("sess{i}"));
                if outcome == ResolveOutcome::Found {
                    recorded.fetch_add(1, Ordering::SeqCst);
                }
            }));
        }
        for h in handles { h.join().unwrap(); }
        assert_eq!(recorded.load(Ordering::SeqCst), N, "no lost writes under concurrent record");
    }
}
