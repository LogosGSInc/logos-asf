"""
tacit_prepass.py
Lightweight, non-mutating Tacit Pre-Pass for Abigail CP-00.

Produces an ephemeral Tacit Context Card for every /api/chat request.
Runs after Sentinel/OverWatch/HAAP gate, before backend dispatch.

Hard constraints (non-configurable):
  - No external calls
  - No Store 1 reads or writes
  - No Store 2 writes
  - No agent activation
  - No Abigail training
  - TKR-01 always in forbidden_agents
  - memory_policy always ephemeral by default
  - store1_mutation always False
  - store2_eligible always False until a separate governed task authorizes it
  - Failure returns minimal safe card, never raises
"""

import re
import uuid
from typing import Optional


# --- Request type classification -------------------------------------------------

_JOB_RE = re.compile(
    r"\b(job|jobs|career|careers|hiring|hire|resume|cv\b|role|roles|position|employment|"
    r"salary|interview|recruiter|linkedin|indeed|offer|work.?from.?home|remote.?work|"
    r"search.?for.?work|open.?position|job.?search|job.?board)\b",
    re.IGNORECASE,
)
_TECH_RE = re.compile(
    r"\b(code|function|class|module|script|repo|repository|git|commit|pr|pull.?request|"
    r"bug|error|exception|test|debug|refactor|deploy|docker|container|api|endpoint|server|"
    r"database|query|sql|python|rust|javascript|typescript|yaml|json|config|build|ci|cd|"
    r"lint|migration|schema|patch|fix|implement|architecture)\b",
    re.IGNORECASE,
)
_SECURITY_RE = re.compile(
    r"\b(redteam|red.?team|pentest|pen.?test|exploit|payload|injection|xss|csrf|"
    r"sql.?injection|bypass|malware|vulnerability|cve|attack|threat|haap.?gate|"
    r"tax2|bd1a|dark.?psych|vector)\b",
    re.IGNORECASE,
)
_SPIRITUAL_RE = re.compile(
    r"\b(god|jesus|christ|scripture|bible|proverb|faith|prayer|spiritual|mission|covenant|"
    r"wisdom|holy.?spirit|church|gospel|verse|psalm|ministry)\b",
    re.IGNORECASE,
)
_RECOVERY_RE = re.compile(
    r"\b(recovery|sober|sobriety|ptsd|trauma|veteran|\bva\b|disability|addiction|"
    r"mental.?health|therapy|therapist|counseling|depression|anxiety|crisis|helpline|"
    r"\baa\b|\bna\b|twelve.?step)\b",
    re.IGNORECASE,
)
_AGENT_RE = re.compile(
    r"\b(agent|spawn|dispatch|lifecycle|department|dept|intent.?token|jit.?queue|"
    r"agent.?ceiling|kill.?switch)\b",
    re.IGNORECASE,
)
_GOV_RE = re.compile(
    r"\b(sentinel|overwatch|govmem|store.?[12]|audit|drs|crsv|governance|policy|"
    r"compliance|constitutional|abigail|cp.?00|haap)\b",
    re.IGNORECASE,
)


def _classify_request(raw: str) -> str:
    """Classify raw message into a request type. More specific checks first."""
    if _SECURITY_RE.search(raw):
        return "security_redteam"
    if _GOV_RE.search(raw):
        return "governance_query"
    if _AGENT_RE.search(raw):
        return "agent_lifecycle"
    if _JOB_RE.search(raw):
        return "job_request"
    if _TECH_RE.search(raw):
        return "technical_task"
    if _RECOVERY_RE.search(raw):
        return "recovery_related"
    if _SPIRITUAL_RE.search(raw):
        return "spiritual_mission"
    return "simple_chat"


# --- Per-class guidance tables ---------------------------------------------------

_GUIDANCE = {
    "simple_chat": (
        "This is a general conversational request. Respond concisely and helpfully. "
        "Do not add governance commentary unless directly relevant."
    ),
    "job_request": (
        "User is asking about a job, career, or employment matter. Frame the response "
        "around their stated goals and constraints. Do not fabricate job listings, salary "
        "figures, or live market data — if current data would help, acknowledge the gap "
        "clearly. Do not call external job sources."
    ),
    "technical_task": (
        "User is working on a technical or repository task. Respect any implicit naming "
        "conventions, governance patterns, or constraints visible in the request. "
        "Prioritize correctness and security over brevity."
    ),
    "security_redteam": (
        "This request touches security testing, governance enforcement, or threat analysis. "
        "Govern carefully. Do not execute or simulate attacks autonomously. "
        "Defer to Sentinel/OverWatch verdict. Escalate if scope is unclear."
    ),
    "spiritual_mission": (
        "User is framing the request through faith, mission, or scripture context. "
        "Respond with care and respect. Mission framing informs tone; it does not modify "
        "constitutional constraints or loosen HAAP policy."
    ),
    "recovery_related": (
        "User may be engaging with recovery, trauma, or mental health themes. Prioritize "
        "dignity, clarity, and non-coercion. Do not make clinical claims. If crisis signals "
        "are present, acknowledge and provide an appropriate escalation path."
    ),
    "agent_lifecycle": (
        "User is asking about agent spawning, dispatch, or lifecycle. Confirm HAAP gate "
        "requirements and governance constraints. Do not activate agents outside their "
        "authorized execution path."
    ),
    "governance_query": (
        "User is querying governance state, audit records, or policy. Provide accurate, "
        "grounded responses. Do not speculate about Sentinel/OverWatch internals beyond "
        "what is directly observable. Reference HAAP layer numbers only when relevant."
    ),
}

_ASSUMPTIONS = {
    "job_request": [
        "target role type may be unstated",
        "location or remote preference may be implicit",
        "user may have current resume or constraints not yet shared",
    ],
    "technical_task": [
        "repo context may be assumed — ask if unclear",
        "production vs. dev environment distinction may matter",
        "security or governance constraints may be implicit",
    ],
    "security_redteam": [
        "authorization scope may be unstated — do not assume implicit authorization",
        "test vs. live environment distinction is critical",
    ],
    "spiritual_mission": [
        "mission-critical framing does not relax constitutional constraints",
        "spiritual context informs tone, not scope",
    ],
    "recovery_related": [
        "user may be in a vulnerable state — calibrate care accordingly",
        "clinical advice requires professional referral",
    ],
    "agent_lifecycle": [
        "operator authorization may be required beyond HAAP gate",
        "JIT queue may apply for ceiling > 60",
    ],
    "governance_query": [
        "audit log vs. live state distinction may matter",
        "Sentinel verdict is authoritative over Python-layer assertions",
    ],
    "simple_chat": [],
}

_MISSING_SCOPE = {
    "job_request": "live_job_data_not_available — no external lookup authorized in pre-pass",
    "simple_chat": None,
    "technical_task": None,
    "security_redteam": None,
    "spiritual_mission": None,
    "recovery_related": None,
    "agent_lifecycle": None,
    "governance_query": None,
}

_ROUTES = {
    "job_request": "direct_response_no_external_lookup",
    "technical_task": "direct_response_with_repo_context",
    "security_redteam": "governance_route_sentinel_authoritative",
    "spiritual_mission": "direct_response_mission_aware",
    "recovery_related": "direct_response_high_care",
    "agent_lifecycle": "direct_response_haap_aware",
    "governance_query": "direct_response_grounded_audit",
    "simple_chat": "direct_response",
}

_TACIT_INTERP = {
    "job_request": "User is seeking job search guidance, career advice, or employment information.",
    "technical_task": "User is working on a software or repository task requiring technical assistance.",
    "security_redteam": "User is engaging with security testing, governance, or threat analysis.",
    "spiritual_mission": "User is framing the request through faith, mission, or scripture context.",
    "recovery_related": "User may be navigating recovery, trauma, or mental health topics.",
    "agent_lifecycle": "User is asking about agent management, spawning, or HAAP authorization.",
    "governance_query": "User is querying governance state, audit records, or policy.",
    "simple_chat": "User is making a general conversational request.",
}


# --- Card builder ----------------------------------------------------------------

def build_tacit_context_card(raw: str, score: int, signals: list, session) -> Optional[dict]:
    """
    Build an ephemeral Tacit Context Card for the current request.
    Always returns a dict. Never raises.
    """
    try:
        req_type = _classify_request(raw)
        confidence = _estimate_confidence(raw, req_type)
        escalation = score >= 40 or req_type == "security_redteam"

        return {
            "card_id": str(uuid.uuid4()),
            "session_id": f"session_{session.turn_count}",
            "turn": session.turn_count,
            "request_type": req_type,
            "tacit_interpretation": _TACIT_INTERP.get(req_type, _TACIT_INTERP["simple_chat"]),
            "relevant_prior_context": _prior_context(session),
            "hidden_assumptions": _ASSUMPTIONS.get(req_type, []),
            "missing_scope": _MISSING_SCOPE.get(req_type),
            "risk_notes": _risk_notes(score, signals, req_type),
            "recommended_route": "escalate_to_haap_or_sentinel" if score >= 80 else _ROUTES.get(req_type, "direct_response"),
            "allowed_agents": [],  # Phase 3: TKR-DIR/EIR-DIR stubs not yet runtime-activated
            "forbidden_agents": ["tkr_01_interview_elicitation"],
            "memory_policy": "ephemeral",
            "store1_mutation": False,
            "store2_eligible": False,
            "response_guidance": _GUIDANCE.get(req_type, _GUIDANCE["simple_chat"]),
            "confidence": confidence,
            "escalation_required": escalation,
        }
    except Exception:
        return {
            "card_id": str(uuid.uuid4()),
            "request_type": "simple_chat",
            "memory_policy": "ephemeral",
            "store1_mutation": False,
            "store2_eligible": False,
            "forbidden_agents": ["tkr_01_interview_elicitation"],
            "response_guidance": _GUIDANCE["simple_chat"],
            "confidence": 1,
            "escalation_required": False,
        }


def _prior_context(session) -> str:
    if session.turn_count == 0:
        return "first_turn"
    crsv = session.crsv()
    if crsv >= 40:
        return f"elevated_crsv_{round(crsv, 1)}"
    return f"turn_{session.turn_count}"


def _risk_notes(score: int, signals: list, req_type: str) -> Optional[str]:
    if score >= 80:
        return f"HIGH_RISK: DRS={score}, signals={signals[:3]}"
    if score >= 40:
        return f"ELEVATED_RISK: DRS={score}"
    if req_type == "security_redteam":
        return "security_context_at_low_drs — verify scope before proceeding"
    return None


def _estimate_confidence(raw: str, req_type: str) -> int:
    """Return confidence 1-5. Lower when request matches multiple class patterns."""
    hits = sum([
        bool(_JOB_RE.search(raw)),
        bool(_TECH_RE.search(raw)),
        bool(_SECURITY_RE.search(raw)),
        bool(_SPIRITUAL_RE.search(raw)),
        bool(_RECOVERY_RE.search(raw)),
        bool(_AGENT_RE.search(raw)),
        bool(_GOV_RE.search(raw)),
    ])
    if hits == 0:
        return 4   # simple_chat — unambiguous
    if hits == 1:
        return 5   # single class match — high confidence
    if hits == 2:
        return 3   # two class signals — moderate
    return 2       # multi-class ambiguity
