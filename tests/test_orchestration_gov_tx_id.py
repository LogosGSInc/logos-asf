# -*- coding: utf-8 -*-
"""
tests/test_orchestration_gov_tx_id.py — F1 Governance Transaction ID Threading

Sprint banner: Do not test whether Abigail can answer. Test whether Abigail can stay governed.

F1 goal: every routed skill invocation carries a single governance transaction id
(gov_tx_id) from beginning to end — minted once at the RoutingManifest (the origin)
and threaded, unchanged, through every SignedHandoffPacket, SingleGovernedState,
the shadow runtime bridge, and the audit-safe response metadata.

Covers:
- gov_tx_id is minted at the manifest and is well-formed / non-empty
- an explicit gov_tx_id can be threaded (transaction spanning multiple manifests)
- handoff packets copy the manifest gov_tx_id verbatim (no regeneration)
- the packet payload_hash covers gov_tx_id (tamper-evident correlation)
- the shadow bridge threads gov_tx_id into governed state and response_metadata
- full-flow correlation: manifest → packet → state → response_metadata all agree
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from abigail.orchestration import (
    build_routing_manifest,
    build_handoff_packet,
    build_shadow_orchestration_context,
    packet_canonical_payload_dict,
    new_gov_tx_id,
    canonical_json,
    sha256_hex,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _manifest(**kw):
    defaults = dict(
        task_intent="analyze_doc",
        request_type="analyze",
        modality="document",
        source_trust_class="user_supplied",
        input_payload=b"test",
    )
    defaults.update(kw)
    return build_routing_manifest(**defaults)


def _packet(manifest=None, **kw):
    if manifest is None:
        manifest = _manifest()
    defaults = dict(
        to_agent="doc_analyst",
        mission="analyze the document for key findings",
        authority_scope="read_only:document_analysis",
    )
    defaults.update(kw)
    return build_handoff_packet(manifest, **defaults)


class _FakeSession:
    turn_count = 3
    def crsv(self): return 1.2


# ── Minting ─────────────────────────────────────────────────────────────────

def test_new_gov_tx_id_is_well_formed():
    gid = new_gov_tx_id()
    assert gid.startswith("GTX-")
    assert len(gid) == len("GTX-") + 16


def test_new_gov_tx_id_is_unique():
    assert new_gov_tx_id() != new_gov_tx_id()


def test_manifest_mints_gov_tx_id_when_none_supplied():
    m = _manifest()
    assert m.gov_tx_id.startswith("GTX-")


def test_manifest_accepts_explicit_gov_tx_id():
    """A transaction already in flight can attach a new manifest under one id."""
    gid = new_gov_tx_id()
    m = _manifest(gov_tx_id=gid)
    assert m.gov_tx_id == gid


def test_two_manifests_get_distinct_gov_tx_ids_by_default():
    assert _manifest().gov_tx_id != _manifest().gov_tx_id


# ── Handoff packet correlation ────────────────────────────────────────────────

def test_packet_copies_manifest_gov_tx_id_verbatim():
    m = _manifest()
    p = _packet(m)
    assert p.gov_tx_id == m.gov_tx_id


def test_packet_never_regenerates_gov_tx_id():
    """Two packets from the SAME manifest must share the transaction id."""
    m = _manifest()
    p1 = _packet(m)
    p2 = _packet(m)
    assert p1.gov_tx_id == p2.gov_tx_id == m.gov_tx_id


def test_packet_payload_hash_covers_gov_tx_id():
    """gov_tx_id is in the canonical payload — tampering must break the hash."""
    p = _packet()
    payload = packet_canonical_payload_dict(p)
    assert payload["gov_tx_id"] == p.gov_tx_id
    assert sha256_hex(canonical_json(payload)) == p.payload_hash

    tampered = dict(payload)
    tampered["gov_tx_id"] = new_gov_tx_id()
    assert sha256_hex(canonical_json(tampered)) != p.payload_hash


# ── Shadow runtime bridge correlation ─────────────────────────────────────────

def test_bridge_threads_gov_tx_id_into_state_and_metadata():
    c = build_shadow_orchestration_context("hello there", "chat", _FakeSession(), ["groq"], None)
    assert c is not None
    assert c.governed_state.gov_tx_id == c.routing_manifest.gov_tx_id
    assert c.response_metadata["gov_tx_id"] == c.routing_manifest.gov_tx_id


def test_bridge_gov_tx_id_is_non_empty():
    c = build_shadow_orchestration_context("hello there", "chat", _FakeSession(), ["groq"], None)
    assert c.response_metadata["gov_tx_id"].startswith("GTX-")


# ── Full-flow end-to-end correlation ──────────────────────────────────────────

def test_full_flow_single_gov_tx_id_end_to_end():
    """manifest → packet → second packet → all share one governance transaction id."""
    m = _manifest()
    p_analyst = _packet(m, to_agent="doc_analyst")
    p_reviewer = _packet(m, to_agent="reviewer", authority_scope="read_only:review")

    ids = {m.gov_tx_id, p_analyst.gov_tx_id, p_reviewer.gov_tx_id}
    assert len(ids) == 1, f"governance transaction fractured across handoffs: {ids}"
