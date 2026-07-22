from abigail.model_router import dispatcher as D


def _route_dict(*_args, **_kwargs):
    return {
        "selected_provider": "anthropic",
        "request_type": "technical_task",
    }


def _adapter(*_args, **_kwargs):
    raise AssertionError("selection-only path must never execute an adapter")


def test_selection_returns_routed_provider_without_execution(monkeypatch):
    monkeypatch.setattr(D.caps, "key_present", lambda _p: True)
    monkeypatch.setattr(D.caps, "tier_permits", lambda _t, _p: True)
    monkeypatch.setattr(D.caps, "health", lambda _p: "available")

    result = D.governed_route_selection(
        "debug this code",
        approval_state="cleared",
        cost_state={"approved": True},
        route_fn=_route_dict,
        dispatch_table={"anthropic": _adapter},
    )

    assert result["selection_status"] == "selected"
    assert result["provider_selected"] == "anthropic"
    assert result["route_request_type"] == "technical_task"


def test_selection_fails_closed_without_fallback(monkeypatch):
    monkeypatch.setattr(D.caps, "key_present", lambda _p: True)
    monkeypatch.setattr(D.caps, "tier_permits", lambda _t, _p: True)
    monkeypatch.setattr(D.caps, "health", lambda _p: "available")

    result = D.governed_route_selection(
        "debug this code",
        approval_state="cleared",
        cost_state={"approved": True},
        route_fn=_route_dict,
        dispatch_table={"groq": _adapter},
    )

    assert result["selection_status"] == "unavailable"
    assert result["reason"] == "provider_not_live_wired"
    assert result["fallback_provider"] is None


def test_existing_dispatch_reads_dict_router_card(monkeypatch):
    monkeypatch.setattr(D.caps, "key_present", lambda _p: True)
    monkeypatch.setattr(D.caps, "tier_permits", lambda _t, _p: True)
    monkeypatch.setattr(D.caps, "health", lambda _p: "available")

    result = D.governed_route_and_dispatch(
        "debug this code",
        approval_state="cleared",
        cost_state={"approved": True},
        route_fn=_route_dict,
        dispatch_table={"anthropic": lambda _m, _s: "ok"},
        messages=[],
        system="",
    )

    assert result["dispatch_status"] == "executed"
    assert result["provider_selected"] == "anthropic"
    assert result["route_request_type"] == "technical_task"
