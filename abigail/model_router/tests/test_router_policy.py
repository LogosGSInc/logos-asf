import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from abigail.model_router.router import route_request


def test_technical_task():
    card = route_request("Help me patch this Python bug.")
    assert card["request_type"] == "technical_task"
    assert card["selected_provider"] in ("openai", "current_backend")
    assert card["swarm_recommended"] is False
    assert card["risk_level"] == "low"


def test_doctrine_card():
    card = route_request("Create a doctrine card from Scripture and The Art of War.")
    assert card["request_type"] == "doctrine"
    assert card["selected_provider"] == "openai"
    assert card["review_required"] is True
    assert card["reviewer_provider"] == "anthropic"
    assert card["memory_policy"] == "doctrine_candidate"


def test_private_memory():
    card = route_request("Summarize my private recovery journal.")
    assert card["data_sensitivity"] == "user_private"
    assert card["selected_provider"] == "local"
    assert card["fallback_provider"] is None
    assert card["memory_policy"] == "ephemeral"


def test_blocked_reason_not_in_normal_route():
    card = route_request("Help me write a Python function.")
    assert card["blocked_reason"] is None
    assert card["risk_level"] != "blocked"


def test_card_has_no_raw_prompt():
    from abigail.model_router.audit import safe_route_fields
    card = route_request("Sensitive prompt text that must not appear in logs.")
    safe = safe_route_fields(card)
    for v in safe.values():
        if isinstance(v, str):
            assert "Sensitive prompt text that must not appear in logs" not in v
