import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from abigail.model_router.adapters.dry_run import DryRunProviderAdapter
from abigail.model_router.envelopes import ProviderRequestEnvelope, ProviderResponseEnvelope
from abigail.model_router.adapters.registry import ProviderRegistry

_ADAPTER = DryRunProviderAdapter(provider_name="openai")
_REGISTRY = ProviderRegistry()

_ROUTE_TECHNICAL = {
    "card_id": "test-t01",
    "request_type": "technical_task",
    "risk_level": "low",
    "data_sensitivity": "public",
    "selected_provider": "openai",
    "output_contract": "markdown",
    "tool_required": "code",
    "review_required": False,
    "blocked_reason": None,
}

_ROUTE_PRIVATE = {
    "card_id": "test-p01",
    "request_type": "private_memory",
    "risk_level": "low",
    "data_sensitivity": "user_private",
    "selected_provider": "local",
    "output_contract": "freeform",
    "tool_required": "none",
    "review_required": False,
    "blocked_reason": None,
}

_ROUTE_BLOCKED = {
    "card_id": "test-b01",
    "request_type": "blocked",
    "risk_level": "blocked",
    "data_sensitivity": "public",
    "selected_provider": "current_backend",
    "output_contract": "freeform",
    "tool_required": "none",
    "review_required": False,
    "blocked_reason": "deceptive_collection",
}


def test_build_request_returns_request_envelope():
    env = _ADAPTER.build_request(_ROUTE_TECHNICAL)
    assert isinstance(env, ProviderRequestEnvelope)


def test_execute_returns_response_envelope():
    env = _ADAPTER.build_request(_ROUTE_TECHNICAL)
    resp = _ADAPTER.execute(env)
    assert isinstance(resp, ProviderResponseEnvelope)


def test_dry_run_always_true_on_request():
    env = _ADAPTER.build_request(_ROUTE_TECHNICAL)
    assert env.dry_run is True


def test_dry_run_always_true_on_response():
    env = _ADAPTER.build_request(_ROUTE_TECHNICAL)
    resp = _ADAPTER.execute(env)
    assert resp.dry_run is True


def test_supports_any_route():
    assert _ADAPTER.supports(_ROUTE_TECHNICAL) is True
    assert _ADAPTER.supports(_ROUTE_BLOCKED) is True
    assert _ADAPTER.supports({}) is True


def test_messages_summary_never_raw_content():
    raw = "My private recovery journal entry from yesterday."

    class _Session:
        messages = [{"role": "user", "content": raw}]

    env = _ADAPTER.build_request(_ROUTE_PRIVATE, session=_Session())
    assert raw not in env.messages_summary
    assert raw not in env.system_policy_summary


def test_system_policy_summary_never_full_system_prompt():
    full_prompt = "You are Abigail - CP-00, Constitutional Administrator of the LOGOS Agentic Software Firm."
    env = _ADAPTER.build_request(_ROUTE_TECHNICAL)
    assert full_prompt not in env.system_policy_summary


def test_blocked_route_response_not_empty_error():
    env = _ADAPTER.build_request(_ROUTE_BLOCKED)
    resp = _ADAPTER.execute(env)
    assert resp.output_text == ""
    assert resp.error is not None
    assert resp.dry_run is True


def test_blocked_route_has_safety_flag():
    env = _ADAPTER.build_request(_ROUTE_BLOCKED)
    resp = _ADAPTER.execute(env)
    assert "route_blocked" in resp.safety_flags


def test_private_route_redaction_applied():
    adapter = _REGISTRY.get("local")
    env = adapter.build_request(_ROUTE_PRIVATE)
    assert env.redaction_applied is True


def test_execute_does_not_mutate_session():
    class _Session:
        messages = [{"role": "user", "content": "original"}]

    session = _Session()
    original_len = len(session.messages)
    env = _ADAPTER.build_request(_ROUTE_TECHNICAL, session=session)
    _ADAPTER.execute(env)
    assert len(session.messages) == original_len


def test_no_subprocess_in_dry_run():
    dry_run_file = Path(__file__).parent.parent / "adapters" / "dry_run.py"
    content = dry_run_file.read_text()
    assert "subprocess" not in content
    assert "eval(" not in content
    assert "exec(" not in content
