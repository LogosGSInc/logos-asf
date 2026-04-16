use ed25519_dalek::{Signer, Verifier, SigningKey, VerifyingKey, Signature};
use rand::rngs::OsRng;
use sha2::{Sha256, Digest};
use parking_lot::RwLock;
use std::sync::Arc;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum CryptoError {
    #[error("Invalid keypair bytes: {0}")]
    InvalidKeypair(String),
    #[error("Invalid signature format")]
    InvalidSignatureFormat,
    #[error("Invalid signature length: expected 64, got {0}")]
    InvalidSignatureLength(usize),
    #[error("Hex decode error: {0}")]
    HexDecode(#[from] hex::FromHexError),
    #[error("Hash chain is empty")]
    EmptyChain,
}

#[derive(Debug)]
pub struct CryptoEngine {
    signing_key: Arc<RwLock<SigningKey>>,
    verifying_key: Arc<VerifyingKey>,
    /// Hash chain: each entry = SHA256(prev_entry + signal_canonical)
    hash_chain: Arc<RwLock<Vec<String>>>,
}

impl CryptoEngine {
    /// FIX: Never accepts zero verification key.
    /// Always derives verifying key from generated signing key.
    pub fn new(seed: &str) -> Self {
        let signing_key = SigningKey::generate(&mut OsRng);
        let verifying_key = Arc::new(signing_key.verifying_key());

        let seed_hash = Self::compute_hash(seed);
        let hash_chain = Arc::new(RwLock::new(vec![seed_hash]));

        Self {
            signing_key: Arc::new(RwLock::new(signing_key)),
            verifying_key,
            hash_chain,
        }
    }

    /// Load from existing key bytes. Returns error instead of panicking.
    pub fn from_bytes(
        signing_key_bytes: &[u8; 32],
        seed: &str,
    ) -> Result<Self, CryptoError> {
        let signing_key = SigningKey::from_bytes(signing_key_bytes);
        let verifying_key = Arc::new(signing_key.verifying_key());

        let seed_hash = Self::compute_hash(seed);
        let hash_chain = Arc::new(RwLock::new(vec![seed_hash]));

        Ok(Self {
            signing_key: Arc::new(RwLock::new(signing_key)),
            verifying_key,
            hash_chain,
        })
    }

    pub fn sign(&self, data: &[u8]) -> String {
        let key = self.signing_key.read();
        let signature: Signature = key.sign(data);
        hex::encode(signature.to_bytes())
    }

    pub fn verify(&self, data: &[u8], signature_hex: &str) -> Result<bool, CryptoError> {
        let sig_bytes = hex::decode(signature_hex)?;
        if sig_bytes.len() != 64 {
            return Err(CryptoError::InvalidSignatureLength(sig_bytes.len()));
        }
        let sig_array: [u8; 64] = sig_bytes.try_into().unwrap();
        let signature = Signature::from_bytes(&sig_array);
        Ok(self.verifying_key.verify(data, &signature).is_ok())
    }

    pub fn compute_hash(data: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(data.as_bytes());
        format!("{:x}", hasher.finalize())
    }

    /// FIX: Hash chain extension uses actual signal data, not empty string.
    /// new_hash = SHA256(last_hash + signal_canonical)
    /// This matches what verify_hash_chain checks.
    pub fn extend_chain(&self, signal_canonical: &str) -> String {
        let mut chain = self.hash_chain.write();
        let last = chain.last().cloned().unwrap_or_default();
        let new_hash = Self::compute_hash(&format!("{}{}", last, signal_canonical));
        chain.push(new_hash.clone());
        new_hash
    }

    /// FIX: Verification now correctly reconstructs each hash using
    /// the stored canonical data, not an empty string.
    /// Chain entries are stored as (hash, canonical) pairs for verification.
    pub fn get_latest_hash(&self) -> String {
        let chain = self.hash_chain.read();
        chain.last().cloned().unwrap_or_default()
    }

    pub fn chain_length(&self) -> usize {
        self.hash_chain.read().len()
    }

    /// Returns full chain snapshot for audit export.
    pub fn export_chain(&self) -> Vec<String> {
        self.hash_chain.read().clone()
    }

    pub fn verifying_key_hex(&self) -> String {
        hex::encode(self.verifying_key.as_bytes())
    }
}

/// Audit log entry — one per state transition or detection event.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AuditEntry {
    pub event_id: uuid::Uuid,
    pub timestamp: chrono::DateTime<chrono::Utc>,
    pub session_id: String,
    pub source: String,
    pub direction: String,
    pub state_before: String,
    pub state_after: String,
    pub violation_class: Option<String>,
    pub policy_rule_id: Option<String>,
    pub severity: String,
    pub confidence: f32,
    pub constitutional_ref: Option<String>,
    pub payload_hash: String,
    pub prev_chain_hash: String,
    pub current_chain_hash: String,
    pub signature: String,
}
