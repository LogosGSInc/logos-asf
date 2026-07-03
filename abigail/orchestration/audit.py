# -*- coding: utf-8 -*-
"""
audit.py — LOGOS Governance Systems Inc. — Abigail CP-00 Orchestration Audit Primitives

Canonical JSON serialization, SHA-256 hashing, and ID generation.
No imports from other orchestration modules — safe as a base dependency.
No provider calls. No network calls. No secrets.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone


def canonical_json(obj: dict) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 safe."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha256_hex(data) -> str:
    """SHA-256 hex digest of str (UTF-8 encoded) or bytes."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def canonical_hash(obj: dict) -> str:
    """SHA-256 over canonical_json(obj)."""
    return sha256_hex(canonical_json(obj))


def hash_input(raw) -> str:
    """SHA-256 of raw bytes or str input. Used for input_hash field — never stores raw content."""
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def now_utc() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def new_manifest_id() -> str:
    return f"MANIFEST-{uuid.uuid4().hex[:12].upper()}"


def new_packet_id() -> str:
    return f"PACKET-{uuid.uuid4().hex[:12].upper()}"


def new_state_id() -> str:
    return f"STATE-{uuid.uuid4().hex[:12].upper()}"
