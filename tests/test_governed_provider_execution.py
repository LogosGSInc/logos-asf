import pytest

import abigail_hardened_enhanced as R


SESSION_ID = "session-test-001"
GOV_TX_ID = "gov-tx-test-001"
VERDICT_ID = "verdict-test-001"
MODEL = "llama-3.3-70b-versatile"


def _authorization():
    return {
        "ok": True,
        "decision_id": "decision-test-001",
        "capability_id": "capability-test-001",
        "gov_tx_id": GOV_TX_ID,
        "session_id": SESSION_ID,
        "backend": "groq",
        "model": MODEL,
        "verdict_id": VERDICT_ID,
    }


def _execute():
    return R._governed_provider_execute(
        provider="groq",
        messages=[{"role": "user", "content": "hello"}],
        system="test system",
        sentinel_session_id=SESSION_ID,
        gov_tx_id=GOV_TX_ID,
        expected_verdict_id=VERDICT_ID,
    )


def test_authorize_rejection_prevents_provider_call(monkeypatch):
    provider_calls = []

    monkeypatch.setattr(
        R,
        "_resolve_provider_model",
        lambda _provider: MODEL,
    )

    def reject_authorization(**_kwargs):
        raise R.GovernedProviderError("authorization rejected")

    monkeypatch.setattr(
        R,
        "_sentinel_provider_authorize",
        reject_authorization,
    )
    monkeypatch.setitem(
        R.BACKEND_DISPATCH,
        "groq",
        lambda **kwargs: provider_calls.append(kwargs) or "must not run",
    )

    with pytest.raises(
        R.GovernedProviderError,
        match="authorization rejected",
    ):
        _execute()

    assert provider_calls == []


def test_consume_rejection_prevents_provider_call(monkeypatch):
    provider_calls = []

    monkeypatch.setattr(
        R,
        "_resolve_provider_model",
        lambda _provider: MODEL,
    )
    monkeypatch.setattr(
        R,
        "_sentinel_provider_authorize",
        lambda **_kwargs: _authorization(),
    )

    def reject_consumption(**_kwargs):
        raise R.GovernedProviderError("consume rejected")

    monkeypatch.setattr(
        R,
        "_sentinel_provider_consume",
        reject_consumption,
    )
    monkeypatch.setitem(
        R.BACKEND_DISPATCH,
        "groq",
        lambda **kwargs: provider_calls.append(kwargs) or "must not run",
    )

    with pytest.raises(
        R.GovernedProviderError,
        match="consume rejected",
    ):
        _execute()

    assert provider_calls == []


def test_provider_failure_occurs_after_capability_burn_and_blocks_outbound(
    monkeypatch,
):
    events = []

    monkeypatch.setattr(
        R,
        "_resolve_provider_model",
        lambda _provider: MODEL,
    )
    monkeypatch.setattr(
        R,
        "_sentinel_provider_authorize",
        lambda **_kwargs: events.append("authorize") or _authorization(),
    )
    monkeypatch.setattr(
        R,
        "_sentinel_provider_consume",
        lambda **_kwargs: events.append("consume") or {
            "ok": True,
            "authorized": True,
            "outcome": "CAPABILITY_CONSUMED",
        },
    )

    def provider_failure(**_kwargs):
        events.append("provider")
        raise RuntimeError("provider unavailable")

    monkeypatch.setitem(
        R.BACKEND_DISPATCH,
        "groq",
        provider_failure,
    )
    monkeypatch.setattr(
        R,
        "_sentinel_outbound",
        lambda *_args, **_kwargs: events.append("outbound"),
    )

    with pytest.raises(
        R.GovernedProviderError,
        match="Provider adapter raised an exception",
    ):
        _execute()

    assert events == ["authorize", "consume", "provider"]


def test_outbound_rejection_withholds_generated_provider_text(monkeypatch):
    events = []

    monkeypatch.setattr(
        R,
        "_resolve_provider_model",
        lambda _provider: MODEL,
    )
    monkeypatch.setattr(
        R,
        "_sentinel_provider_authorize",
        lambda **_kwargs: events.append("authorize") or _authorization(),
    )
    monkeypatch.setattr(
        R,
        "_sentinel_provider_consume",
        lambda **_kwargs: events.append("consume") or {
            "ok": True,
            "authorized": True,
            "outcome": "CAPABILITY_CONSUMED",
        },
    )
    monkeypatch.setitem(
        R.BACKEND_DISPATCH,
        "groq",
        lambda **_kwargs: events.append("provider") or "sensitive raw output",
    )

    def reject_outbound(*_args, **_kwargs):
        events.append("outbound")
        raise R.GovernedProviderError("outbound rejected")

    monkeypatch.setattr(
        R,
        "_sentinel_outbound",
        reject_outbound,
    )

    with pytest.raises(
        R.GovernedProviderError,
        match="outbound rejected",
    ):
        _execute()

    assert events == [
        "authorize",
        "consume",
        "provider",
        "outbound",
    ]


def test_successful_execution_is_ordered_and_returns_evidence(monkeypatch):
    events = []

    monkeypatch.setattr(
        R,
        "_resolve_provider_model",
        lambda _provider: MODEL,
    )
    monkeypatch.setattr(
        R,
        "_sentinel_provider_authorize",
        lambda **_kwargs: events.append("authorize") or _authorization(),
    )
    monkeypatch.setattr(
        R,
        "_sentinel_provider_consume",
        lambda **_kwargs: events.append("consume") or {
            "ok": True,
            "authorized": True,
            "outcome": "CAPABILITY_CONSUMED",
        },
    )
    monkeypatch.setitem(
        R.BACKEND_DISPATCH,
        "groq",
        lambda **_kwargs: events.append("provider") or "governed response",
    )
    monkeypatch.setattr(
        R,
        "_sentinel_outbound",
        lambda *_args, **_kwargs: events.append("outbound") or {
            "ok": True,
            "verdict": "APPROVED",
            "session_id": SESSION_ID,
        },
    )
    monkeypatch.setattr(R, "log_event", lambda *_args, **_kwargs: None)

    text, evidence = _execute()

    assert events == [
        "authorize",
        "consume",
        "provider",
        "outbound",
    ]
    assert text == "governed response"
    assert evidence == {
        "gov_tx_id": GOV_TX_ID,
        "verdict_id": VERDICT_ID,
        "decision_id": "decision-test-001",
        "capability_id": "capability-test-001",
        "backend": "groq",
        "model": MODEL,
        "capability_outcome": "CAPABILITY_CONSUMED",
        "outbound_verdict": "APPROVED",
        "execution_status": "completed",
    }
