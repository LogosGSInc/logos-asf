# -*- coding: utf-8 -*-
"""
handoff_packet.py — LOGOS Governance Systems Inc. — Abigail CP-00 Signed Handoff Packet Builder

Scoped worker handoff packets with hash-chain integrity.
from_agent must be an authorized supervisor (Abigail or Abigail-authorized role).
payload_hash covers canonical packet content — excludes hash/signature fields.

P0-4 (ABIGAIL-SPRINT-01): packets are now signed with REAL Ed25519, not a placeholder
hash. build_handoff_packet() signs the canonical payload; verify_packet() authenticates
it against a TRUSTED public key (never the key embedded in the untrusted packet alone),
and require_valid_packet() is called by the receiving side (execute_worker) so unsigned
or tampered packets are rejected rather than accepted. The signing key sits behind the
PacketSigner interface (sign(bytes)->bytes / verify(bytes,sig,pubkey_ref)->bool) so a
local Ed25519 key today can be swapped for a KMS-backed signer in Sprint 02 without
changing the packet format. Legacy SHA256_CHAIN_PLACEHOLDER signatures are treated as
UNSIGNED and are rejected by verify_packet — fail-closed.

Workers receive bounded scoped packets, not free-form transcript sprawl.
No worker may expand its own authority — enforced in SignedHandoffPacket.__post_init__.
No provider calls. No network calls. No secrets stored (private key held in-process/env only).
"""
import dataclasses
import os

from .schemas import SignedHandoffPacket, Budget, RoutingManifest
from .audit import canonical_json, sha256_hex, now_utc, new_packet_id

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
    from cryptography.exceptions import InvalidSignature
    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover - fail-closed: signing is unavailable
    _CRYPTO_AVAILABLE = False


SIGNATURE_ALGORITHM = "ED25519"
_LEGACY_PLACEHOLDER_ALGORITHM = "SHA256_CHAIN_PLACEHOLDER"


class PacketSigningUnavailable(RuntimeError):
    """Raised when Ed25519 signing/verification cannot be performed (fail-closed)."""


class PacketVerificationError(ValueError):
    """Raised by require_valid_packet when a packet is unsigned, tampered, or untrusted."""


class PacketSigner:
    """Signer interface. Swap the backend (local key now, KMS in Sprint 02) without
    changing the packet format: implement sign(bytes)->bytes, verify(bytes, sig,
    public_key_ref)->bool, and expose public_key_ref (hex-encoded public key / key id)."""

    algorithm = SIGNATURE_ALGORITHM

    @property
    def public_key_ref(self) -> str:
        raise NotImplementedError

    def sign(self, data: bytes) -> bytes:
        raise NotImplementedError

    def verify(self, data: bytes, signature: bytes, public_key_ref: str) -> bool:
        raise NotImplementedError


class LocalEd25519Signer(PacketSigner):
    """Local Ed25519 signer. Seed from ABIGAIL_HANDOFF_SIGNING_SEED (64 hex chars = 32
    bytes) for a stable cross-process key, else generate an ephemeral per-process key.
    Verification uses the caller-supplied trusted public_key_ref, so the same interface
    can front a remote KMS verifier later."""

    def __init__(self, seed: bytes = None):
        if not _CRYPTO_AVAILABLE:
            raise PacketSigningUnavailable(
                "cryptography is required for Ed25519 handoff-packet signing "
                "(pip install cryptography)."
            )
        if seed is not None:
            self._sk = Ed25519PrivateKey.from_private_bytes(seed)
        else:
            self._sk = Ed25519PrivateKey.generate()
        self._pk = self._sk.public_key()
        self._pub_hex = self._pk.public_bytes_raw().hex()

    @property
    def public_key_ref(self) -> str:
        return self._pub_hex

    def sign(self, data: bytes) -> bytes:
        return self._sk.sign(data)

    def verify(self, data: bytes, signature: bytes, public_key_ref: str) -> bool:
        if not public_key_ref:
            return False
        try:
            pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_ref))
            pk.verify(signature, data)
            return True
        except (InvalidSignature, ValueError):
            return False


_default_signer = None


def default_signer() -> PacketSigner:
    """Process-wide signer singleton. Fail-closed: raises if crypto is unavailable."""
    global _default_signer
    if _default_signer is None:
        seed_hex = os.environ.get("ABIGAIL_HANDOFF_SIGNING_SEED", "").strip()
        seed = None
        if seed_hex:
            try:
                raw = bytes.fromhex(seed_hex)
                if len(raw) == 32:
                    seed = raw
            except ValueError:
                seed = None
        _default_signer = LocalEd25519Signer(seed=seed)
    return _default_signer

# Fields included in the canonical payload hash.
# Excludes: payload_hash, previous_packet_hash, signature_*, audit_safe.
_CANONICAL_PAYLOAD_FIELDS = (
    "packet_id", "manifest_id", "gov_tx_id", "created_at", "from_agent", "to_agent",
    "mission", "constraints", "authority_scope", "allowed_tools",
    "forbidden_tools", "allowed_outputs", "forbidden_outputs",
    "evidence_requirements", "budget", "stop_conditions",
    "fallback_on_failure", "input_refs",
)

_DEFAULT_FORBIDDEN_TOOLS = ["shell", "bash", "file_write", "network", "http_request", "deploy"]
_DEFAULT_STOP_CONDITIONS  = ["task_complete", "max_steps_reached", "supervisor_abort", "error"]


def build_handoff_packet(
    manifest: RoutingManifest,
    to_agent: str,
    mission: str,
    authority_scope: str,
    from_agent: str = "abigail",
    constraints: dict = None,
    allowed_tools: list = None,
    forbidden_tools: list = None,
    allowed_outputs: list = None,
    forbidden_outputs: list = None,
    evidence_requirements: list = None,
    budget: Budget = None,
    stop_conditions: list = None,
    fallback_on_failure: str = "return_to_supervisor",
    input_refs: list = None,
    previous_packet_hash: str = None,
    signer: PacketSigner = None,
) -> SignedHandoffPacket:
    """
    Build a scoped signed handoff packet from an approved RoutingManifest.

    payload_hash is deterministic SHA-256 over canonical content fields.
    The packet is signed with a REAL Ed25519 signature over the canonical payload
    (P0-4). The signature bytes are stored hex-encoded in signature_placeholder (the
    legacy field name is retained to avoid a schema change; it now holds a real
    signature), signature_algorithm is "ED25519", and signature_public_key_ref carries
    the signer's public key. Use the default process signer unless one is injected.
    """
    if budget is None:
        budget = manifest.budget
    budget_dict = dataclasses.asdict(budget)

    packet_id  = new_packet_id()
    created_at = now_utc()
    ftools     = list(forbidden_tools or _DEFAULT_FORBIDDEN_TOOLS)
    stops      = list(stop_conditions or _DEFAULT_STOP_CONDITIONS)
    constraints_val = dict(constraints or {})

    canonical_content = {
        "packet_id":            packet_id,
        "manifest_id":          manifest.manifest_id,
        "gov_tx_id":            manifest.gov_tx_id,
        "created_at":           created_at,
        "from_agent":           from_agent,
        "to_agent":             to_agent,
        "mission":              mission,
        "constraints":          constraints_val,
        "authority_scope":      authority_scope,
        "allowed_tools":        list(allowed_tools or []),
        "forbidden_tools":      ftools,
        "allowed_outputs":      list(allowed_outputs or []),
        "forbidden_outputs":    list(forbidden_outputs or []),
        "evidence_requirements": list(evidence_requirements or []),
        "budget":               budget_dict,
        "stop_conditions":      stops,
        "fallback_on_failure":  fallback_on_failure,
        "input_refs":           list(input_refs or []),
    }
    canonical_bytes   = canonical_json(canonical_content).encode("utf-8")
    payload_hash      = sha256_hex(canonical_bytes)

    # P0-4: real Ed25519 signature over the canonical payload (fail-closed if crypto
    # is unavailable — we never emit an "accepted" packet without a real signature).
    _signer   = signer or default_signer()
    signature = _signer.sign(canonical_bytes)

    return SignedHandoffPacket(
        packet_id=packet_id,
        manifest_id=manifest.manifest_id,
        gov_tx_id=manifest.gov_tx_id,
        created_at=created_at,
        from_agent=from_agent,
        to_agent=to_agent,
        mission=mission,
        constraints=constraints_val,
        authority_scope=authority_scope,
        allowed_tools=list(allowed_tools or []),
        forbidden_tools=ftools,
        allowed_outputs=list(allowed_outputs or []),
        forbidden_outputs=list(forbidden_outputs or []),
        evidence_requirements=list(evidence_requirements or []),
        budget=budget,
        stop_conditions=stops,
        fallback_on_failure=fallback_on_failure,
        input_refs=list(input_refs or []),
        payload_hash=payload_hash,
        previous_packet_hash=previous_packet_hash,
        signature_algorithm=_signer.algorithm,
        signature_public_key_ref=_signer.public_key_ref,
        signature_placeholder=signature.hex(),
        audit_safe=True,
    )


def packet_canonical_payload_dict(packet: SignedHandoffPacket) -> dict:
    """Return the dict used to compute payload_hash — useful for verification tests."""
    raw = dataclasses.asdict(packet)
    budget_dict = dataclasses.asdict(packet.budget)
    return {
        "packet_id":            raw["packet_id"],
        "manifest_id":          raw["manifest_id"],
        "gov_tx_id":            raw["gov_tx_id"],
        "created_at":           raw["created_at"],
        "from_agent":           raw["from_agent"],
        "to_agent":             raw["to_agent"],
        "mission":              raw["mission"],
        "constraints":          raw["constraints"],
        "authority_scope":      raw["authority_scope"],
        "allowed_tools":        raw["allowed_tools"],
        "forbidden_tools":      raw["forbidden_tools"],
        "allowed_outputs":      raw["allowed_outputs"],
        "forbidden_outputs":    raw["forbidden_outputs"],
        "evidence_requirements": raw["evidence_requirements"],
        "budget":               budget_dict,
        "stop_conditions":      raw["stop_conditions"],
        "fallback_on_failure":  raw["fallback_on_failure"],
        "input_refs":           raw["input_refs"],
    }


def verify_packet(
    packet: SignedHandoffPacket,
    trusted_public_key_ref: str = None,
    signer: PacketSigner = None,
) -> bool:
    """Authenticate a handoff packet before it is accepted downstream (P0-4).

    Returns True only when ALL hold:
      1. the packet carries a real Ed25519 signature (legacy placeholder => False);
      2. the recomputed payload_hash matches the stored one (integrity / tamper-evidence);
      3. the packet's public key equals the TRUSTED key we expect the supervisor to hold
         (defaults to the process signer's key) — never trust the packet-embedded key
         alone, or an attacker could re-sign with their own key and pass;
      4. the Ed25519 signature verifies over the recomputed canonical payload.

    Any failure => False (fail-closed). Never raises for a well-formed packet.
    """
    if packet is None or not isinstance(packet, SignedHandoffPacket):
        return False
    _signer = signer or default_signer()
    # 1) reject unsigned / legacy-placeholder packets outright
    if packet.signature_algorithm != SIGNATURE_ALGORITHM:
        return False
    # 2) recompute + compare payload_hash (tamper-evidence over canonical content)
    canonical_content = packet_canonical_payload_dict(packet)
    canonical_bytes = canonical_json(canonical_content).encode("utf-8")
    if sha256_hex(canonical_bytes) != packet.payload_hash:
        return False
    # 3) the signer's key must be the trusted key — not merely whatever the packet claims
    trusted = trusted_public_key_ref or _signer.public_key_ref
    if not packet.signature_public_key_ref or packet.signature_public_key_ref != trusted:
        return False
    # 4) verify the real signature over the recomputed canonical payload
    try:
        signature = bytes.fromhex(packet.signature_placeholder)
    except (ValueError, TypeError):
        return False
    return _signer.verify(canonical_bytes, signature, trusted)


def require_valid_packet(
    packet: SignedHandoffPacket,
    trusted_public_key_ref: str = None,
    signer: PacketSigner = None,
) -> SignedHandoffPacket:
    """Fail-closed gate for the receiving side: return the packet if it authenticates,
    else raise PacketVerificationError. A signer with no caller of the verifier is the
    same bug in a different form — execute_worker() calls this before running work."""
    if not verify_packet(packet, trusted_public_key_ref=trusted_public_key_ref, signer=signer):
        raise PacketVerificationError(
            "handoff packet failed Ed25519 verification (unsigned, tampered, or untrusted key)"
        )
    return packet
