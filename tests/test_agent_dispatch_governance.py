# -*- coding: utf-8 -*-
"""Governance contract for POST /api/agents/dispatch."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


ADMIN = "dispatch-governance-admin"
BODY = {
    "agent_id": "EN-01",
    "task": "summarize the governed release status",
}


def _client(monkeypatch, *, sentinel=None, executor=None, agent=None):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", ADMIN)

    monkeypatch.setattr(
        A,
        "_get_yaml_agent",
        lambda _agent_id: agent
        if agent is not None
        else {
            "name": "Test Agent",
            "system_prompt": "You are a governed test agent.",
        },
    )

    monkeypatch.setattr(
        A,
        "_sentinel_inspect",
        sentinel
        or (
            lambda _task, _session_id: {
                "ok": True,
                "verdict": "APPROVED",
                "gov_tx_id": "GTX-AGENT-1",
                "verdict_id": "SV-AGENT-1",
            }
        ),
    )

    if executor is not None:
        monkeypatch.setattr(A, "_governed_provider_execute", executor)

    app = A.build_web_app(A.SessionState(), A.KillSwitch(), ["groq"])
    app.testing = True
    return app.test_client()


def _headers():
    return {"Authorization": f"Bearer {ADMIN}"}


def test_missing_authority_evidence_fails_closed(monkeypatch):
    client = _client(
        monkeypatch,
        sentinel=lambda *_: {
            "ok": True,
            "verdict": "APPROVED",
        },
    )

    response = client.post(
        "/api/agents/dispatch",
        json=BODY,
        headers=_headers(),
    )

    assert response.status_code == 503
    data = response.get_json()
    assert data["ok"] is False
    assert data["blocked"] is True
    assert data["mode"] == "AUTHORITY_EVIDENCE_MISSING"
    assert "text" not in data


def test_sentinel_rejection_prevents_governed_execution(monkeypatch):
    calls = []

    def executor(**kwargs):
        calls.append(kwargs)
        raise AssertionError("executor must not run")

    client = _client(
        monkeypatch,
        sentinel=lambda *_: {
            "ok": True,
            "verdict": "BLOCKED",
        },
        executor=executor,
    )

    response = client.post(
        "/api/agents/dispatch",
        json=BODY,
        headers=_headers(),
    )

    assert response.status_code == 403
    assert calls == []
    assert response.get_json()["mode"] == "SENTINEL_FAIL_CLOSED"


def test_governed_execution_rejection_releases_no_output(monkeypatch):
    def executor(**_kwargs):
        raise A.GovernedProviderError("capability consumption rejected")

    client = _client(monkeypatch, executor=executor)

    response = client.post(
        "/api/agents/dispatch",
        json=BODY,
        headers=_headers(),
    )

    assert response.status_code == 502
    data = response.get_json()
    assert data["ok"] is False
    assert data["blocked"] is True
    assert data["mode"] == "GOVERNED_EXECUTION_REJECTED"
    assert data["governance"]["execution_status"] == "rejected"
    assert "text" not in data


def test_success_returns_complete_verification_conjunction(monkeypatch):
    def executor(**kwargs):
        return (
            "governed agent result",
            {
                "execution_status": "completed",
                "capability_outcome": "CAPABILITY_CONSUMED",
                "outbound_verdict": "APPROVED",
                "gov_tx_id": kwargs["gov_tx_id"],
                "verdict_id": kwargs["expected_verdict_id"],
                "decision_id": "DEC-AGENT-1",
                "capability_id": "CAP-AGENT-1",
                "backend": kwargs["provider"],
                "model": "test-model",
            },
        )

    client = _client(monkeypatch, executor=executor)

    response = client.post(
        "/api/agents/dispatch",
        json=BODY,
        headers=_headers(),
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["text"] == "governed agent result"

    governance = data["governance"]
    assert governance["execution_status"] == "completed"
    assert governance["capability_outcome"] == "CAPABILITY_CONSUMED"
    assert governance["outbound_verdict"] == "APPROVED"

    for key in (
        "gov_tx_id",
        "verdict_id",
        "decision_id",
        "capability_id",
        "backend",
        "model",
    ):
        assert governance[key]


def test_unknown_agent_stops_before_sentinel_and_execution(monkeypatch):
    sentinel_calls = []
    execution_calls = []

    def sentinel(*args):
        sentinel_calls.append(args)
        raise AssertionError("Sentinel must not run")

    def executor(**kwargs):
        execution_calls.append(kwargs)
        raise AssertionError("executor must not run")

    client = _client(
        monkeypatch,
        sentinel=sentinel,
        executor=executor,
        agent={},
    )

    response = client.post(
        "/api/agents/dispatch",
        json=BODY,
        headers=_headers(),
    )

    assert response.status_code == 404
    assert sentinel_calls == []
    assert execution_calls == []
