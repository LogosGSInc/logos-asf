# -*- coding: utf-8 -*-
"""
classify.py — pure chat request classifier (router-wrapper-realignment / D1).

classify_route(prompt, session) -> RouteCard

Contract:
  - Pure and deterministic. No network. No provider call. No Sentinel call.
  - Importable without Flask (only stdlib + pydantic + this package's
    sibling modules, none of which touch Flask).
  - Operating rule: danger is opt-in, not default. A request only leaves the
    ordinary chat lanes when an action verb is found together with a
    resolvable target resource (connector, file, repo, deployment target,
    department, tool) or a protected-disclosure pattern matches. Absence of
    any such signal is ordinary chat — never UNKNOWN_HIGH_RISK, never
    quarantined.

This module also doubles as the D4 CLI:
    python -m abigail.model_router.classify --corpus tests/route_corpus.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from .schemas import ModelRouteCard
from .sensitivity import classify_sensitivity

# ── intent_class enum (exact strings, per spec) ─────────────────────────────
LOCAL_STATUS = "LOCAL_STATUS"
LOCAL_TESTING_GUIDANCE = "LOCAL_TESTING_GUIDANCE"
GENERAL_CHAT = "GENERAL_CHAT"
RESEARCH_SYNTHESIS = "RESEARCH_SYNTHESIS"
PLAN_ONLY = "PLAN_ONLY"
DEPARTMENT_TASK = "DEPARTMENT_TASK"
TOOL_REQUEST = "TOOL_REQUEST"
CONNECTOR_REQUEST = "CONNECTOR_REQUEST"
CODE_WRITE_REQUEST = "CODE_WRITE_REQUEST"
FILE_WRITE_REQUEST = "FILE_WRITE_REQUEST"
GIT_REQUEST = "GIT_REQUEST"
DEPLOYMENT_REQUEST = "DEPLOYMENT_REQUEST"
SECRET_OR_CREDENTIAL_REQUEST = "SECRET_OR_CREDENTIAL_REQUEST"
SYSTEM_PROMPT_DISCLOSURE = "SYSTEM_PROMPT_DISCLOSURE"
UNKNOWN_HIGH_RISK = "UNKNOWN_HIGH_RISK"

INTENT_CLASSES = frozenset({
    LOCAL_STATUS, LOCAL_TESTING_GUIDANCE, GENERAL_CHAT, RESEARCH_SYNTHESIS,
    PLAN_ONLY, DEPARTMENT_TASK, TOOL_REQUEST, CONNECTOR_REQUEST,
    CODE_WRITE_REQUEST, FILE_WRITE_REQUEST, GIT_REQUEST, DEPLOYMENT_REQUEST,
    SECRET_OR_CREDENTIAL_REQUEST, SYSTEM_PROMPT_DISCLOSURE, UNKNOWN_HIGH_RISK,
})

# Known department codes (departments/registry.json — active + stub only;
# HR is 'removed_ghost' and intentionally excluded so it can never route).
_DEPT_CODES = ("EXE", "ENG", "SC", "SEC", "QA", "OPS", "GRC", "REV", "FIN",
               "LGL", "PRD", "MKT", "DAT", "RI", "TKR")
_DEPT_ALT = "|".join(_DEPT_CODES)


class RouteCard(ModelRouteCard):
    """Extends ModelRouteCard (model_router/schemas.py) with the D1 fields.
    request_type/risk_level/data_sensitivity are populated from intent_class/
    complexity/sensitivity so existing MODEL_ROUTE_CARD audit consumers keep
    working unchanged."""
    intent_class: str
    complexity: str = "low"
    sensitivity: str = "public"
    provider_family: Optional[str] = None  # provider family id, or "local"
    execution_mode: str = "chat"
    requires_research: bool = False
    allows_tools: bool = False
    allows_connectors: bool = False
    allows_credentials: bool = False
    allows_writes: bool = False
    requires_human_approval: bool = False
    route_reason: str = ""


def _rx(*patterns, flags=re.IGNORECASE):
    return [re.compile(p, flags) for p in patterns]


# ── Step 1: protected disclosure ────────────────────────────────────────────
_SYSTEM_PROMPT_RE = _rx(
    r"\b(show|reveal|print|display|give\s+me|tell\s+me|output|leak|dump)\b.{0,25}"
    r"\b(your\s+)?system\s*prompt\b",
    r"\bwhat\s+(is|are)\s+your\s+(instructions|system\s*prompt)\b",
    r"\breveal\s+your\s+instructions\b",
)

_SECRET_RE = _rx(
    r"\b(dump|show|reveal|print|leak|expose|list)\b.{0,25}"
    r"\b(env(ironment)?\s+variables?|env\s+vars?|secrets?|credentials?|"
    r"api[_ -]?keys?|passwords?|tokens?)\b",
    r"\bwhat('?s|\s+is)\s+your\s+(api[_ -]?key|password|token|secret)\b",
    r"\bgive\s+me\s+(the|your)\s+(api[_ -]?key|password|token|credentials?)\b",
)

# ── Step 2: action verb + resolvable target resource ────────────────────────
# UNKNOWN_HIGH_RISK: an explicit circumvention verb aimed at the governance
# layer itself — the verb is real but there is no resolvable target resource
# (no file, repo, connector, or department to route to). Never assigned for
# mere lack of signal — only for this specific detected-but-unresolvable case.
_UNKNOWN_HIGH_RISK_RE = _rx(
    r"\b(bypass|disable|bypasses|circumvent|override|jailbreak|turn\s*off)\b"
    r".{0,25}\b(sentinel|haap|overwatch|governance|guard\w*|safety|"
    r"constitution\w*|kill.?switch)\b",
)

_CONNECTOR_RE = _rx(
    r"\bconnect\s+(to|with)\b",
    r"\blink\s+(to|with)\s+my\b",
    r"\bauthorize\s+access\s+to\b",
    r"\boauth\b.{0,20}\b(gmail|slack|drive|calendar|account)\b",
    r"\bhook\s+up\b.{0,20}\b(gmail|slack|drive|calendar|email|account)\b",
    r"\bsign\s+in\s+to\s+my\b",
    r"\blog\s+into\s+my\b",
)

_GIT_RE = _rx(
    r"\bpush\b.{0,25}\b(to\s+)?(github|gitlab|origin|main|master|repo\w*)\b",
    r"\b(commit|merge)\b.{0,20}\b(and\s+push|to\s+(main|master|github))\b",
    r"\bopen\s+a\s+pull\s+request\b",
    r"\bcreate\s+a\s+(pull\s+request|pr)\b",
)

_DEPLOYMENT_RE = _rx(
    r"\bdeploy\b.{0,20}\b(to\s+)?(prod\w*|staging|live|server)\b",
    r"\bship\b.{0,15}\bto\s+prod\w*\b",
    r"\brelease\b.{0,15}\bto\s+prod\w*\b",
)

_DEPARTMENT_TASK_RE = _rx(
    rf"\b(have|ask|assign|tell|task)\b.{{0,10}}\b({_DEPT_ALT})\b.{{0,30}}"
    rf"\b(implement|build|write|fix|design|review|handle|do|investigate|draft|prepare)\b",
    rf"\bassign\s+(this|it)\s+to\s+({_DEPT_ALT})\b",
)

_FILE_WRITE_RE = _rx(
    r"\b(write|save|create|generate)\b.{0,20}\bthe\s+files?\b",
    r"\b(write|save)\b.{0,20}\bto\s+disk\b",
)

_CODE_WRITE_RE = _rx(
    r"\b(implement|refactor)\b.{0,30}\b(function|class|module|endpoint|"
    r"feature|codebase)\b",
    r"\bwrite\s+(the\s+)?code\b",
    r"\bfix\s+the\s+bug\b.{0,20}\band\s+(commit|apply|ship)\b",
)

_TOOL_RE = _rx(
    r"\b(use|call|invoke|run)\b.{0,20}\b(this\s+)?(tool|api|plugin|script)\b",
    r"\brun\s+this\s+command\b",
)

_STEP2_ORDER = (
    (UNKNOWN_HIGH_RISK, _UNKNOWN_HIGH_RISK_RE),
    (CONNECTOR_REQUEST, _CONNECTOR_RE),
    (GIT_REQUEST, _GIT_RE),
    (DEPLOYMENT_REQUEST, _DEPLOYMENT_RE),
    (DEPARTMENT_TASK, _DEPARTMENT_TASK_RE),
    (FILE_WRITE_REQUEST, _FILE_WRITE_RE),
    (CODE_WRITE_REQUEST, _CODE_WRITE_RE),
    (TOOL_REQUEST, _TOOL_RE),
)

# ── Step 3: runtime-state / testing questions ───────────────────────────────
_LOCAL_TESTING_RE = _rx(
    r"\bhow\b.{0,40}\btest\b",
    r"\btest\b.{0,40}\bhow\b",
    r"\bhow\s+(can|do|would|should)\s+i\s+(test|verify|check)\b",
)

_LOCAL_STATUS_RE = _rx(
    r"\b(current\s+)?runtime\s+status\b",
    # Deliberately requires a runtime-state qualifier: bare "what can you do"
    # (no "right now"/"currently"/etc.) is the pre-existing UX-01 benign
    # capability question (see public_intent_answer's "capability" label,
    # tests/test_public_response_calibration.py) and must keep flowing
    # through the governed pipeline unchanged, not bypass it as LOCAL_STATUS.
    r"\bwhat\s+can\s+you\s+do\s+(right\s+now|currently|today|at\s+the\s+moment)\b",
    r"\bare\s+(the\s+)?agents?\s+active\b",
    r"\byour\s+(current\s+)?status\b",
    r"\bare\s+you\s+(online|running|active|up)\b",
    r"\bwhich\s+backend\b",
    r"\bis\s+sentinel\s+(healthy|up|reachable)\b",
    r"\bkill.?switch\s+(status|state|on|active)\b",
    r"\bhow\s+many\s+turns?\b",
)

# ── Step 4: research ─────────────────────────────────────────────────────────
# Checked before PLAN_ONLY: a leading research/compare verb governs the
# overall intent even when the prompt also asks for a plan as its output
# (e.g. "research X and plan an MVP" is a research task, not a plan-only one).
_RESEARCH_RE = _rx(
    r"\bresearch\b",
    r"\bcompare\b",
    r"\bfind\s+out\b",
    r"\bwhat\s+are\s+the\s+options\b",
    r"\boptions\s+for\b",
)

# ── Step 5: plan / outline / scope / design / architect / review ───────────
_PLAN_RE = _rx(
    r"\bplan\b", r"\boutline\b", r"\bscope\b", r"\bdesign\b",
    r"\barchitect\b", r"\breview\b",
)


def _any_match(text: str, patterns) -> Optional[re.Match]:
    for rx in patterns:
        m = rx.search(text)
        if m:
            return m
    return None


def _classify_intent(text: str) -> tuple[str, str]:
    """Returns (intent_class, matched_signal). First match wins, step order
    per the branch spec precedence list."""
    m = _any_match(text, _SYSTEM_PROMPT_RE)
    if m:
        return SYSTEM_PROMPT_DISCLOSURE, m.group(0)[:60]
    m = _any_match(text, _SECRET_RE)
    if m:
        return SECRET_OR_CREDENTIAL_REQUEST, m.group(0)[:60]

    for intent, patterns in _STEP2_ORDER:
        m = _any_match(text, patterns)
        if m:
            return intent, m.group(0)[:60]

    m = _any_match(text, _LOCAL_TESTING_RE)
    if m:
        return LOCAL_TESTING_GUIDANCE, m.group(0)[:60]
    m = _any_match(text, _LOCAL_STATUS_RE)
    if m:
        return LOCAL_STATUS, m.group(0)[:60]

    m = _any_match(text, _RESEARCH_RE)
    if m:
        return RESEARCH_SYNTHESIS, m.group(0)[:60]
    m = _any_match(text, _PLAN_RE)
    if m:
        return PLAN_ONLY, m.group(0)[:60]

    return GENERAL_CHAT, ""


# ── capability matrix ────────────────────────────────────────────────────────
def _capabilities(intent_class: str) -> dict:
    local = dict(provider_family="local", execution_mode="local",
                 requires_research=False, allows_tools=False,
                 allows_connectors=False, allows_credentials=False,
                 allows_writes=False, requires_human_approval=False)
    chat = dict(provider_family="current_backend", execution_mode="chat",
                requires_research=False, allows_tools=False,
                allows_connectors=False, allows_credentials=False,
                allows_writes=False, requires_human_approval=False)
    gated = dict(provider_family="current_backend", execution_mode="gated",
                 requires_research=False, allows_tools=True,
                 allows_connectors=False, allows_credentials=False,
                 allows_writes=True, requires_human_approval=True)
    blocked = dict(provider_family=None, execution_mode="blocked",
                   requires_research=False, allows_tools=False,
                   allows_connectors=False, allows_credentials=False,
                   allows_writes=False, requires_human_approval=False)

    table = {
        LOCAL_STATUS: local,
        LOCAL_TESTING_GUIDANCE: local,
        GENERAL_CHAT: chat,
        RESEARCH_SYNTHESIS: {**chat, "execution_mode": "research",
                              "requires_research": True},
        PLAN_ONLY: {**chat, "execution_mode": "plan"},
        DEPARTMENT_TASK: {**gated, "provider_family": "groq",
                           "execution_mode": "department_dispatch"},
        CONNECTOR_REQUEST: {**gated, "allows_connectors": True,
                             "allows_credentials": True},
        CODE_WRITE_REQUEST: dict(gated),
        FILE_WRITE_REQUEST: dict(gated),
        GIT_REQUEST: dict(gated),
        DEPLOYMENT_REQUEST: dict(gated),
        TOOL_REQUEST: dict(gated),
        SECRET_OR_CREDENTIAL_REQUEST: dict(blocked),
        SYSTEM_PROMPT_DISCLOSURE: dict(blocked),
        UNKNOWN_HIGH_RISK: dict(blocked),
    }
    return table[intent_class]


def _complexity(text: str) -> str:
    n = len(text.split())
    if n <= 6:
        return "low"
    if n <= 30:
        return "medium"
    return "high"


def classify_route(prompt: str, session=None) -> RouteCard:
    """Pure, deterministic chat request classifier. No network, no provider
    call, no Sentinel call. Safe to import and call without Flask."""
    text = (prompt or "").strip()
    intent_class, signal = _classify_intent(text)
    sensitivity, sens_signal = classify_sensitivity(text)
    caps = _capabilities(intent_class)
    complexity = _complexity(text)

    risk_level = "blocked" if caps["execution_mode"] == "blocked" else (
        "high" if caps["requires_human_approval"] else
        "medium" if intent_class in (RESEARCH_SYNTHESIS, DEPARTMENT_TASK) else
        "low"
    )

    reason_parts = [f"intent_class={intent_class}"]
    if signal:
        reason_parts.append(f"signal='{signal}'")
    if sens_signal:
        reason_parts.append(f"sensitivity={sensitivity}('{sens_signal}')")
    route_reason = "; ".join(reason_parts)

    return RouteCard(
        request_type=intent_class,
        risk_level=risk_level,
        data_sensitivity=sensitivity,
        selected_provider=caps["provider_family"] or "current_backend",
        intent_class=intent_class,
        complexity=complexity,
        sensitivity=sensitivity,
        provider_family=caps["provider_family"],
        execution_mode=caps["execution_mode"],
        requires_research=caps["requires_research"],
        allows_tools=caps["allows_tools"],
        allows_connectors=caps["allows_connectors"],
        allows_credentials=caps["allows_credentials"],
        allows_writes=caps["allows_writes"],
        requires_human_approval=caps["requires_human_approval"],
        route_reason=route_reason,
    )


# ── D4: CLI ──────────────────────────────────────────────────────────────────
def _run_corpus(corpus_path: Path) -> int:
    mismatches = 0
    total = 0
    rows = []
    with open(corpus_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            prompt = rec["prompt"]
            expected = rec["expected"]
            actual = classify_route(prompt, None).intent_class
            total += 1
            verdict = "PASS" if actual == expected else "FAIL"
            if verdict == "FAIL":
                mismatches += 1
            rows.append((prompt, expected, actual, verdict))

    for prompt, expected, actual, verdict in rows:
        print(f"{prompt} | {expected} | {actual} | {verdict}")
    print(f"\n{total - mismatches}/{total} passed", file=sys.stderr)
    return 1 if mismatches else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m abigail.model_router.classify")
    parser.add_argument("--corpus", required=True, type=Path)
    args = parser.parse_args(argv)
    return _run_corpus(args.corpus)


if __name__ == "__main__":
    sys.exit(main())
