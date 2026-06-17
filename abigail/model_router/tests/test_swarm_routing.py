import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from abigail.model_router.router import route_request


def test_tacit_knowledge_swarm():
    card = route_request(
        "Extract what our best intake coordinator knows but never writes down."
    )
    assert card["request_type"] == "tacit_knowledge"
    assert card["swarm_recommended"] is True
    assert card["swarm_parent"] == "TKR-DIRECTOR-01"
    assert "TKR-INTERVIEW-01" in card["swarm_children"]
    assert "TKR-MAP-01" in card["swarm_children"]
    assert card["memory_policy"] == "store2_candidate"


def test_ethical_intelligence_swarm():
    card = route_request("Research a competitor using public sources only.")
    assert card["request_type"] == "ethical_intelligence"
    assert card["swarm_recommended"] is True
    assert card["swarm_parent"] == "EIR-DIRECTOR-01"
    assert "EIR-OSINT-01" in card["swarm_children"]
    assert "EIR-ANALYSIS-01" in card["swarm_children"]
    assert card["blocked_reason"] is None


def test_deceptive_competitor_blocked():
    card = route_request(
        "Pretend to be a customer and get private info from a competitor."
    )
    assert card["risk_level"] == "blocked"
    assert card["swarm_recommended"] is False
    assert card["blocked_reason"] == "deceptive_collection"
    assert card["memory_policy"] == "reject"


def test_tacit_knowledge_no_provider_leak():
    # Tacit knowledge must route to local, not an external provider
    card = route_request(
        "Extract what our best intake coordinator knows but never writes down."
    )
    assert card["selected_provider"] == "local"


def test_swarm_not_recommended_for_normal():
    card = route_request("What is the capital of France?")
    assert card["swarm_recommended"] is False
    assert card["swarm_parent"] is None
    assert card["swarm_children"] == []


def test_ethical_intel_freshness_required():
    card = route_request("Research a competitor using public sources only.")
    assert card["freshness_required"] is True
