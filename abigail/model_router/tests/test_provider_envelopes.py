import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from abigail.model_router.envelopes import ProviderRequestEnvelope, ProviderResponseEnvelope
from abigail.model_router.adapters.dry_run import DryRunProviderAdapter
from abigail.model_router.provider_audit import safe_provider_fields

_ADAPTER = DryRunProviderAdapter(provider_name="openai")

_BASE_ROUTE = {
    "card_id": "test-card-01",
    "request_type": "technical_task",
    "data_sensitivity": "public",
    "selected_provider": "openai",
    "output_contract": "markdown",
    "tool_required": "code",
    "review_required": False,
    "blocked_reason": None,
}


def test_request_envelope_never_stores_raw_prompt():
    raw_prompt = "Help me patch this critical Python bug in production."
    route = {**_BASE_ROUTE}

    class _FakeSession:
        messages = [{"role": "user", "content": raw_prompt}]

    env = _ADAPTER.build_request(route, session=_FakeSession())
    dump = env.model_dump()

    for field, value in dump.items():
        if isinstance(value, str):
            assert raw_prompt not in value, f"Raw prompt leaked into field '{field}'"


def test_response_envelope_always_dry_run():
    req = _ADAPTER.build_request(_BASE_ROUTE)
    resp = _ADAPTER.execute(req)
    assert resp.dry_run is True


def test_request_envelope_dry_run_always_true():
    env = _ADAPTER.build_request(_BASE_ROUTE)
    assert env.dry_run is True


def test_private_data_sets_redaction_applied():
    route = {**_BASE_ROUTE, "data_sensitivity": "user_private"}
    env = _ADAPTER.build_request(route)
    assert env.redaction_applied is True


def test_public_data_no_redaction():
    route = {**_BASE_ROUTE, "data_sensitivity": "public"}
    env = _ADAPTER.build_request(route)
    assert env.redaction_applied is False


def test_regulated_data_sets_redaction():
    route = {**_BASE_ROUTE, "data_sensitivity": "regulated"}
    env = _ADAPTER.build_request(route)
    assert env.redaction_applied is True


def test_safe_fields_excludes_messages_summary():
    env = _ADAPTER.build_request(_BASE_ROUTE)
    safe = safe_provider_fields(env.model_dump())
    assert "messages_summary" not in safe


def test_safe_fields_excludes_system_policy_summary():
    env = _ADAPTER.build_request(_BASE_ROUTE)
    safe = safe_provider_fields(env.model_dump())
    assert "system_policy_summary" not in safe


def test_safe_fields_excludes_model_hint():
    env = _ADAPTER.build_request(_BASE_ROUTE)
    safe = safe_provider_fields(env.model_dump())
    assert "model_hint" not in safe


def test_blocked_route_sets_error_not_output():
    route = {**_BASE_ROUTE, "blocked_reason": "deceptive_collection"}
    env = _ADAPTER.build_request(route)
    resp = _ADAPTER.execute(env)
    assert resp.output_text == ""
    assert resp.error is not None
    assert "blocked" in resp.error
    assert "route_blocked" in resp.safety_flags
