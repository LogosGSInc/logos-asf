from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

import yaml

from .schemas import ModelRouteCard
from .sensitivity import classify_sensitivity

_DIR = Path(__file__).parent


def _load_yaml(name: str) -> dict:
    with open(_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


try:
    _ROUTING: dict = _load_yaml("routing_policy.yaml")["routing_policy"]
    _SWARM: dict   = _load_yaml("swarm_policy.yaml")["swarm_policy"]
except Exception as _e:
    import sys
    print(f"[MODEL_ROUTER] YAML load error: {_e}", file=sys.stderr)
    _ROUTING = {}
    _SWARM   = {}

# Request type signals — most specific first, normal_chat is the final fallback
_TYPE_SIGNALS: list[tuple[str, list[str]]] = [
    ("blocked", [
        r"pretend\s+(you\s+are|to\s+be)\s+a\s+(customer|competitor|employee|rep)",
        r"\bimpersonat\w*\b",
        r"\bphish\w*\b",
        r"get\s+(private|personal|confidential)\s+(info|data)\s+from\s+a\s+competitor",
        r"(hacked|leaked)\s+(data|info|credentials)",
    ]),
    ("tacit_knowledge", [
        r"what\s+.+(know|knows).+(never\s+writ|never\s+document)",
        r"(extract|capture|map)\s+.+(knowledge|expertise|know.?how).+(coordinator|staff|employee|team)",
        r"\btacit\s+knowledge\b",
        r"\bworkflow\s+mapping\b",
        r"\bsop\s+(build|creat|extract)\w*\b",
        r"\bknowledge\s+(extraction|transfer|capture)\b",
    ]),
    ("ethical_intelligence", [
        r"research\s+.{0,30}competitor",
        r"competitor\s+.{0,30}(public|source|analy|position|landscape)",
        r"\bmarket\s+(terrain|intelligence|landscape)\b",
        r"\b(osint|open.source\s+intelligence)\b",
        r"\bthreat\s+briefing\b",
        r"public\s+source",
    ]),
    ("doctrine", [
        r"\bdoctrine\s+card\b",
        r"(scripture|bible|quran|torah).{0,30}(art\s+of\s+war|proverb|doctrine)",
        r"(art\s+of\s+war|proverb|doctrine).{0,30}(scripture|bible|quran|torah)",
        r"\bcreate\s+a\s+doctrine\b",
    ]),
    ("private_memory", [
        r"my\s+(private|personal)\s+(recovery\s+)?journal",
        r"(summarize|review|read|access)\s+my\s+(private|personal|confidential)\b",
        r"\bprivate\s+notes?\b",
        r"\bpersonal\s+diary\b",
    ]),
    ("technical_task", [
        r"\b(patch|bug|fix|debug|refactor|implement|traceback|exception)\b",
        r"\b(python|javascript|typescript|sql|bash|rust|go|java)\s+(bug|error|issue|code)\b",
        r"help\s+me\s+(write|build|fix|patch|debug)\b",
        r"\b(code|function|class|script|unit\s+test)\b",
    ]),
]

_TYPE_RE: list[tuple[str, list[re.Pattern]]] = [
    (t, [re.compile(p, re.IGNORECASE | re.DOTALL) for p in pats])
    for t, pats in _TYPE_SIGNALS
]

_DECEPTIVE_RE: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in _TYPE_SIGNALS[0][1]  # reuse blocked patterns
]


def _classify_request_type(text: str) -> tuple[str, str]:
    for rtype, patterns in _TYPE_RE:
        for rx in patterns:
            m = rx.search(text)
            if m:
                return rtype, m.group(0)[:60]
    return "normal_chat", ""


def _risk_level(request_type: str, drs_score: int, sensitivity: str) -> str:
    if request_type == "blocked":
        return "blocked"
    if sensitivity in ("regulated", "sacred_doctrinal") or drs_score > 60:
        return "high"
    if sensitivity == "confidential" or drs_score > 30:
        return "medium"
    return "low"


def _swarm_routing(request_type: str) -> tuple[bool, Optional[str], list[str]]:
    key_map = {
        "tacit_knowledge":       "tacit_knowledge_requests",
        "ethical_intelligence":  "ethical_intelligence_requests",
    }
    key = key_map.get(request_type)
    if not key or key not in _SWARM:
        return False, None, []
    policy   = _SWARM[key]
    parent   = policy.get("parent_agent")
    children = [str(c) for c in policy.get("children", [])]
    return True, parent, children


def _blocked_reason(text: str) -> Optional[str]:
    for rx in _DECEPTIVE_RE:
        if rx.search(text):
            return "deceptive_collection"
    return None


def route_request(
    prompt: str,
    drs_score: int = 0,
    drs_signals: Optional[list] = None,
    tacit_card: Optional[dict] = None,
) -> dict:
    """
    Shadow-mode router. Returns a MODEL_ROUTE_CARD dict.
    Does not call any provider. Does not mutate dispatch.
    """
    request_type, type_signal = _classify_request_type(prompt)
    sensitivity, sens_signal   = classify_sensitivity(prompt)
    risk                       = _risk_level(request_type, drs_score, sensitivity)

    policy = _ROUTING.get(request_type) or _ROUTING.get("normal_chat", {})

    swarm_rec, swarm_parent, swarm_children = _swarm_routing(request_type)

    blocked = _blocked_reason(prompt) if request_type == "blocked" else None

    # Privacy override: user_private data never leaves local
    if sensitivity == "user_private" and policy.get("selected_provider") not in ("local", None):
        selected_provider = "local"
        fallback_provider = None
    else:
        selected_provider = policy.get("selected_provider", "current_backend")
        fallback_provider = policy.get("fallback_provider")

    reason_parts = [f"request_type={request_type}"]
    if type_signal:
        reason_parts.append(f"signal='{type_signal[:60]}'")
    if sens_signal:
        reason_parts.append(f"sensitivity={sensitivity}('{sens_signal[:40]}')")
    if swarm_rec:
        reason_parts.append(f"swarm_lane={swarm_parent}")

    card = ModelRouteCard(
        request_type=request_type,
        risk_level=risk,
        data_sensitivity=sensitivity,
        freshness_required=(request_type == "ethical_intelligence"),
        tool_required=policy.get("tool_required", "none"),
        latency_need=policy.get("latency_need", "normal"),
        cost_ceiling=policy.get("cost_ceiling", "medium"),
        output_contract=policy.get("output_contract", "freeform"),
        selected_provider=selected_provider,
        fallback_provider=fallback_provider,
        review_required=bool(policy.get("review_required", False)),
        reviewer_provider=policy.get("reviewer_provider"),
        swarm_recommended=swarm_rec,
        swarm_parent=swarm_parent,
        swarm_children=swarm_children,
        memory_policy=policy.get("memory_policy", "ephemeral"),
        reason_for_route="; ".join(reason_parts),
        blocked_reason=blocked,
    )
    return card.model_dump()
