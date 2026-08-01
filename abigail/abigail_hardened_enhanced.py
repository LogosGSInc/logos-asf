# -*- coding: utf-8 -*-
"""
abigail_hardened_enhanced.py
LOGOS Governance Systems Inc.
Logos Agentic Software Firm — Control Plane (Hardened)
Founder & CEO: David W. Smith | US Provisional Patent 63/953,447

SPRINT 6 ADDITIONS (all existing HAAP layers preserved):
  - Docker + venv constitutional sandbox for spawned agents
  - /api/sentinel-health proxy
  - /api/agents/spawn  — HAAP-gated Docker launcher
  - /api/agents/departments — ASF registry
  - /api/audit/tail — admin log viewer
  - CORS: GitHub Pages + *.app.github.dev wildcard (flask-cors + manual fallback)
  - CSP connect-src widened for Codespaces in embedded WEB_HTML

"By wisdom a house is built, and through understanding it is established."
— Proverbs 24:3
"""

import datetime, hashlib, json, logging, os, re, stat
import subprocess, sys, threading, time, uuid, webbrowser
from pathlib import Path

import privileged_credentials

# ── Agent loader (YAML definitions) ──────────────────────────────────────────
try:
    from agent_loader import get_agent as _get_yaml_agent, list_agents as _list_yaml_agents
    _AGENT_LOADER_OK = True
except ImportError:
    _AGENT_LOADER_OK = False
    def _get_yaml_agent(_id): return None
    def _list_yaml_agents(): return []

# ── Tacit Pre-Pass (ephemeral, non-mutating) ──────────────────────────────────
try:
    from tacit_prepass import build_tacit_context_card as _build_tacit_card
    _TACIT_PREPASS_OK = True
except ImportError:
    _TACIT_PREPASS_OK = False
    def _build_tacit_card(raw, score, signals, session): return None

# ── Model Router Shadow Pass (MR-01, non-mutating, observation + logging only)
try:
    from model_router import route_request as _route_request
    from model_router.audit import safe_route_fields as _safe_route_fields
    _MODEL_ROUTER_OK = True
except ImportError:
    _MODEL_ROUTER_OK = False
    def _route_request(*a, **kw): return None
    def _safe_route_fields(c): return {}

# ── Provider Adapter Dry Run (MR-02, dry-run only, no provider calls, no key reads)
try:
    from model_router.adapters.registry import ProviderRegistry as _ProviderRegistry
    from model_router.provider_audit import safe_provider_fields as _safe_provider_fields
    _provider_registry = _ProviderRegistry()
    _PROVIDER_ADAPTER_OK = True
except ImportError:
    _PROVIDER_ADAPTER_OK = False
    _provider_registry = None
    def _safe_provider_fields(e): return {}

# ── MR-05: MoE router → chat-path integration (governed live dispatch) ─────────
try:
    from model_router.dispatcher import (
        governed_route_and_dispatch as _governed_route_and_dispatch,
        governed_route_selection as _governed_route_selection,
    )
    _MOE_DISPATCH_OK = True
except ImportError:
    _MOE_DISPATCH_OK = False

    def _governed_route_and_dispatch(*a, **kw):
        return {
            "dispatch_status": "unavailable",
            "provider_selected": None,
            "reason": "moe_dispatch_unavailable",
            "fallback_provider": None,
        }

    def _governed_route_selection(*a, **kw):
        return {
            "selection_status": "unavailable",
            "provider_selected": None,
            "reason": "moe_selection_unavailable",
            "fallback_provider": None,
        }

# ── Governed Command Bus (CB-01, pre-inference operator command detection) ─────
try:
    from command_bus import try_operator_command as _try_operator_command_fn
    _COMMAND_BUS_OK = True
except ImportError:
    _COMMAND_BUS_OK = False
    def _try_operator_command_fn(*a, **kw): return None

# ── Shadow Orchestration Bridge (MM-02, audit-safe shadow routing context) ─────
# ── + MM-03 enforced approval gate predicate ──────────────────────────────────
try:
    from orchestration.runtime_bridge import (
        build_shadow_orchestration_context as _build_shadow_ctx,
        approval_gate_blocks as _approval_gate_blocks,
    )
    _ORCHESTRATION_BRIDGE_OK = True
except ImportError:
    _ORCHESTRATION_BRIDGE_OK = False
    def _build_shadow_ctx(*a, **kw): return None
    def _approval_gate_blocks(*a, **kw): return False

# ── Curated Control Plane Registry — safe read-only exposure of Skills to Ops ───
try:
    from orchestration.control_plane_registry import (
        build_default_control_plane_registry as _build_control_plane_registry,
        ControlPlaneAuthError as _ControlPlaneAuthError,
    )
    _CONTROL_PLANE_OK = True
except ImportError:
    _CONTROL_PLANE_OK = False
    class _ControlPlaneAuthError(Exception): pass
    def _build_control_plane_registry(*a, **kw): return None

# ── Governed Local Swarm (AG-01) — P0-5: one real end-to-end governed dispatch path ──
try:
    from swarm import (
        SwarmRegistry as _SwarmRegistry,
        JobSpec as _JobSpec,
        ContainmentController as _ContainmentController,
        ContainmentMode as _ContainmentMode,
        ActivationState as _ActivationState,
        LocalExecutor as _LocalExecutor,
        supervisor_merge as _supervisor_merge,
    )
    _SWARM_OK = True
except ImportError:
    _SWARM_OK = False

VERSION      = "1.2.0-sprint6-docker-sandbox"
HOME         = Path.home()
LOG_FILE     = HOME / ".abigail_audit.jsonl"
HISTORY_FILE = HOME / ".abigail_history"
ENV_FILE     = HOME / ".abigail.env"
GROQ_TIMEOUT = 60

SENTINEL_URL           = os.environ.get("SENTINEL_URL", "http://sentinel:8080")
SENTINEL_SERVICE_TOKEN = os.environ.get("SENTINEL_SERVICE_TOKEN", "").strip()
# P0-1 (ABIGAIL-SPRINT-01): the authoritative Rust Sentinel is REQUIRED by default.
# When it is unreachable the request is hard-blocked (fail-closed) rather than silently
# downgraded to the weaker Python regex layer. Operators may opt out explicitly with
# SENTINEL_REQUIRED=0, in which case the Python HAAP layer runs as defense-in-depth and
# the skip is always audited (never silent).
SENTINEL_REQUIRED      = os.environ.get("SENTINEL_REQUIRED", "1").strip() == "1"
AGENT_BASE_IMAGE       = os.environ.get("AGENT_BASE_IMAGE", "python:3.11-slim")
AGENT_NETWORK    = os.environ.get("AGENT_NETWORK", "logos-asf_default")
AGENT_TIMEOUT    = int(os.environ.get("AGENT_TIMEOUT_SECONDS", 120))

LOGO_BANNER = f"""
╔══════════════════════════════════════════════════════════════╗
║          LOGOS AGENTIC SOFTWARE FIRM — CONTROL PLANE        ║
║          Abigail | Constitutional Administrator v{VERSION}  ║
║          HAAP Five-Layer Enforcement — ACTIVE               ║
║          Sprint 6 — Docker + venv Constitutional Sandbox    ║
╚══════════════════════════════════════════════════════════════╝
"By wisdom a house is built." — Proverbs 24:3
"""


def try_grounded_answer(raw, session=None):
    q = (raw or "").lower()
    if any(k in q for k in ["logging path","log path","audit path","where are logs",
                              "auth_verified","authz_granted","session_authenticated"]):
        return {"ok": True,
                "text": (f"The observed audit log path in this build is: {LOG_FILE}\n\n"
                         "I do not have evidence in this build of dedicated AUTH_VERIFIED, "
                         "AUTHZ_GRANTED, or SESSION_AUTHENTICATED event logging."),
                "drs": 0, "mode": "GROUNDED_INFO",
                "crsv": round(session.crsv(), 1) if session else 0.0}
    return None


# ── Secure helpers ────────────────────────────────────────────────────────────
def _secure_touch(path):
    path.touch(exist_ok=True); path.chmod(stat.S_IRUSR | stat.S_IWUSR)

def _secure_open(path, mode="a"):
    _secure_touch(path); return open(path, mode, encoding="utf-8")

_SECRET_RE = re.compile(
    r"(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36}|[A-Za-z0-9+/]{40,}={0,2})",
    re.IGNORECASE)

def _scrub(obj):
    if isinstance(obj, dict):  return {k: _scrub(v) for k,v in obj.items()}
    if isinstance(obj, list):  return [_scrub(v) for v in obj]
    if isinstance(obj, str):   return _SECRET_RE.sub("[REDACTED]", obj)
    return obj

def log_event(event_type, data):
    entry = {"ts": datetime.datetime.utcnow().isoformat()+"Z",
              "event_type": event_type, "data": _scrub(data)}
    try:
        with _secure_open(LOG_FILE, "a") as fh:
            fh.write(json.dumps(entry)+"\n")
    except Exception as exc:
        print(f"[AUDIT-WRITE-ERROR] {type(exc).__name__}", file=sys.stderr)


# ── Env ───────────────────────────────────────────────────────────────────────
def _load_env_file(path):
    if not path.exists(): return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k,_,v = line.partition("=")
            k=k.strip(); v=v.strip().strip('"').strip("'")
            if k and k not in os.environ: os.environ[k]=v

def _require_env_key(name):
    v = os.environ.get(name,"")
    if not v or v.upper().startswith("YOUR_") or v=="PLACEHOLDER":
        raise RuntimeError(f"[CONFIG-FATAL] {name} is required. Set it in {ENV_FILE}.")
    return v


# ── SEC-02: Runtime hardening — bind host, admin auth, cost governor ────────────
def resolve_bind_host():
    """SEC-02 (L3-1): default to localhost. A non-local bind must be explicitly opted
    into via ABIGAIL_BIND_HOST plus ABIGAIL_ALLOW_NONLOCAL_BIND=1; otherwise the request
    is refused and downgraded to 127.0.0.1."""
    requested = (os.environ.get("ABIGAIL_BIND_HOST","") or "127.0.0.1").strip()
    if requested in ("127.0.0.1","localhost","::1"):
        return "127.0.0.1"
    if os.environ.get("ABIGAIL_ALLOW_NONLOCAL_BIND","0") == "1":
        return requested
    log_event("BIND_NONLOCAL_REFUSED", {"requested_len": len(requested)})
    return "127.0.0.1"


_DEFAULT_MAX_REQUEST_BYTES = 1_048_576  # 1 MiB


def resolve_max_request_bytes():
    """C6: request body size boundary. Werkzeug/Flask enforce this before any
    route handler runs (413 Request Entity Too Large), so an oversized body
    never reaches process_message()/agent dispatch/etc. Configurable via
    ABIGAIL_MAX_REQUEST_BYTES; a missing, non-numeric, or non-positive value
    falls back to the safe default rather than disabling the limit."""
    try:
        value = int(os.environ.get("ABIGAIL_MAX_REQUEST_BYTES", ""))
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else _DEFAULT_MAX_REQUEST_BYTES


def require_admin_token(req):
    """SEC-02 (L1-1) / C4: fail-closed admin authentication.
    Returns (ok, http_status, error). ok is True only when a server-side
    ABIGAIL_ADMIN_TOKEN is configured (per the centralized C4 validator —
    present, non-placeholder, >=43 chars) AND the request presents the
    matching token (constant-time compare). A missing OR invalid/placeholder
    server token is a misconfiguration and fails closed (503) — identically,
    so a caller can never distinguish "not set" from "set to a placeholder".
    A missing or incorrect client token is 401. Error text never reveals
    token contents or closeness."""
    if privileged_credentials.resolve_configured_token("ABIGAIL_ADMIN_TOKEN") is None:
        return (False, 503, "Admin control unavailable: server auth not configured.")
    auth = req.headers.get("Authorization","").removeprefix("Bearer ").strip()
    token = auth or req.headers.get("X-HAAP-Token","").strip()
    if not privileged_credentials.credential_matches(token, "ABIGAIL_ADMIN_TOKEN"):
        return (False, 401, "Admin token required.")
    return (True, 200, None)


def estimate_tokens(text):
    """Deterministic local token estimate (~4 chars/token). No provider calls."""
    return max(1, (len(text or "") + 3) // 4)


def check_chat_cost_budget(message, mode, session):
    """SEC-02 (L7-1): deterministic local pre-inference spend gate. Returns
    (allowed, meta). No external billing calls. When enabled, a zero/empty budget fails
    closed; over-budget turn counts or oversized requests are blocked before any paid
    provider dispatch. meta is audit-safe — message length only, never raw prompt."""
    enabled = os.environ.get("ABIGAIL_COST_GOVERNOR_ENABLED","1") == "1"
    def _int(name, default):
        try: return int(os.environ.get(name, str(default)) or 0)
        except ValueError: return 0
    max_turns  = _int("ABIGAIL_MAX_CHAT_TURNS", 1000)
    max_tokens = _int("ABIGAIL_MAX_ESTIMATED_TOKENS", 8000)
    est = estimate_tokens(message)
    meta = {"cost_governor": "enabled" if enabled else "disabled",
            "turns_used": session.turn_count, "max_chat_turns": max_turns,
            "estimated_tokens": est, "max_estimated_tokens": max_tokens}
    if not enabled:
        meta["decision"] = "allow_disabled"; return (True, meta)
    if max_turns <= 0 or max_tokens <= 0:
        meta["decision"] = "block_zero_budget"; return (False, meta)
    if session.turn_count >= max_turns:
        meta["decision"] = "block_turns_exhausted"; return (False, meta)
    if est > max_tokens:
        meta["decision"] = "block_request_too_large"; return (False, meta)
    meta["decision"] = "allow"; return (True, meta)


def build_approval_required_response(approval_meta, session):
    """MM-03: governed APPROVAL_REQUIRED response. Returned when human_approval_required
    is true and no hard-block fired first. No worker executes, no external action, no file
    write, no tool/outbound path, and no provider inference/spend occurs. Reason fields are
    audit-safe (ids, risk, signal) — never the raw prompt."""
    m = approval_meta or {}
    reasons = []
    if m.get("command_style_signal"): reasons.append("command_style_signal")
    if m.get("risk_level") in ("high", "critical"): reasons.append("risk_level:" + str(m.get("risk_level")))
    if m.get("request_type"): reasons.append("request_type:" + str(m.get("request_type")))
    return {
        "ok": False,
        "mode": "APPROVAL_REQUIRED",
        "text": ("Human approval is required before this request can proceed. Abigail "
                 "stopped before action: no worker, tool, outbound call, file write, or "
                 "model inference was performed."),
        "drs": 0,
        "crsv": session.crsv(),
        "approval": {
            "human_approval_required": True,
            "enforced": True,
            "gov_tx_id": m.get("gov_tx_id"),
            "manifest_id": m.get("manifest_id"),
            "state_id": m.get("state_id"),
            "risk_level": m.get("risk_level"),
            "command_style_signal": m.get("command_style_signal"),
            "reason": reasons or ["human_approval_required"],
        },
    }


# ── Backends ──────────────────────────────────────────────────────────────────
BACKENDS = {
    "groq":       {"env":"GROQ_API_KEY",      "label":"Groq (Llama 4 Scout)"},
    "anthropic":  {"env":"ANTHROPIC_API_KEY",  "label":"Anthropic (Claude Sonnet)"},
    "perplexity": {"env":"PERPLEXITY_API_KEY", "label":"Perplexity (Sonar)"},
    "ollama":     {"env":None,                 "label":"Ollama (local)"},
    "openai":     {"env":"OPENAI_API_KEY",     "label":"OpenAI (GPT-4o)"},
    "xai":        {"env":"XAI_API_KEY",        "label":"xAI (Grok)"},
}

def _safe_error(ctx,exc): return f"[{ctx} error — {type(exc).__name__}]"

def call_groq(messages, system, model=None):
    model = model or os.environ.get(
        "GROQ_MODEL",
        "llama-3.3-70b-versatile",
    ).strip()

    try:
        from groq import Groq

        # Deterministic acceptance-only timeout injection.
        # Disabled unless both explicit test guards are configured. It is not
        # request-controlled and executes only after the governed capability
        # has already been authorized and atomically consumed upstream.
        test_faults_enabled = (
            os.environ.get("ABIGAIL_ENABLE_TEST_FAULTS", "0").strip() == "1"
        )

        try:
            injected_delay = float(
                os.environ.get(
                    "ABIGAIL_TEST_GROQ_TIMEOUT_SECONDS",
                    "0",
                ).strip()
                or "0"
            )
        except ValueError:
            injected_delay = 0.0

        if test_faults_enabled and injected_delay > 0:
            bounded_delay = min(injected_delay, 10.0)

            log_event(
                "TEST_PROVIDER_TIMEOUT_INJECTED",
                {
                    "backend": "groq",
                    "delay_seconds": bounded_delay,
                    "test_faults_enabled": True,
                },
            )

            time.sleep(bounded_delay)
            raise TimeoutError(
                "Injected Groq provider deadline exceeded for acceptance testing"
            )

        response = Groq(
            api_key=_require_env_key("GROQ_API_KEY"),
            timeout=GROQ_TIMEOUT,
        ).chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=2048,
            temperature=0.3,
        )

        return response.choices[0].message.content.strip()

    except ImportError as exc:
        log_event(
            "BACKEND_ERROR",
            {
                "backend": "groq",
                "error_type": type(exc).__name__,
                "terminal_state": "UNAVAILABLE",
            },
        )
        raise GovernedProviderError(
            "Groq provider client is unavailable.",
            terminal_state="UNAVAILABLE",
            provider_called=False,
        ) from exc

    except Exception as exc:
        error_type = type(exc).__name__
        error_text = str(exc).lower()

        timed_out = (
            "timeout" in error_type.lower()
            or "timed out" in error_text
            or "deadline exceeded" in error_text
        )

        terminal_state = "TIMED_OUT" if timed_out else "UNAVAILABLE"

        log_event(
            "BACKEND_ERROR",
            {
                "backend": "groq",
                "error_type": error_type,
                "terminal_state": terminal_state,
            },
        )

        raise GovernedProviderError(
            (
                "Groq provider execution exceeded the configured deadline."
                if timed_out
                else "Groq provider execution was unavailable."
            ),
            terminal_state=terminal_state,
            provider_called=True,
        ) from exc

def call_anthropic(messages, system, model=None):
    try:
        import anthropic
        model=model or os.environ.get("ABIGAIL_ANTHROPIC_MODEL","claude-sonnet-5")
        r=anthropic.Anthropic(api_key=_require_env_key("ANTHROPIC_API_KEY"),timeout=GROQ_TIMEOUT).messages.create(
            model=model,max_tokens=2048,system=system,messages=messages)
        return r.content[0].text.strip()
    except ImportError: return "[anthropic not installed]"
    except Exception as exc:
        log_event("BACKEND_ERROR",{"backend":"anthropic","error_type":type(exc).__name__})
        return _safe_error("Anthropic",exc)

def call_perplexity(messages, system):
    try:
        import httpx
        key=_require_env_key("PERPLEXITY_API_KEY")
        with httpx.Client(timeout=GROQ_TIMEOUT) as c:
            r=c.post("https://api.perplexity.ai/chat/completions",
                     headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                     json={"model":"sonar","messages":[{"role":"system","content":system}]+messages,"max_tokens":2048})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except ImportError: return "[httpx not installed]"
    except Exception as exc:
        log_event("BACKEND_ERROR",{"backend":"perplexity","error_type":type(exc).__name__})
        return _safe_error("Perplexity",exc)

def call_ollama(messages, system, model="llama3"):
    try:
        import httpx
        base=os.environ.get("OLLAMA_BASE_URL","http://localhost:11434")
        if not re.match(r"https?://(localhost|127\.0\.0\.1)(:\d+)?",base):
            return "[Ollama: only localhost URLs permitted]"
        with httpx.Client(timeout=GROQ_TIMEOUT) as c:
            r=c.post(f"{base}/api/chat",
                     json={"model":model,"messages":[{"role":"system","content":system}]+messages,"stream":False})
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception as exc:
        log_event("BACKEND_ERROR",{"backend":"ollama","error_type":type(exc).__name__})
        return _safe_error("Ollama",exc)

def call_openai(messages, system, model=None):
    try:
        import httpx
        key=_require_env_key("OPENAI_API_KEY")
        model=model or os.environ.get("ABIGAIL_OPENAI_MODEL","gpt-4o")
        with httpx.Client(timeout=GROQ_TIMEOUT) as c:
            r=c.post("https://api.openai.com/v1/chat/completions",
                     headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                     json={"model":model,"messages":[{"role":"system","content":system}]+messages,
                           "max_tokens":2048,"temperature":0.3})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except ImportError: return "[httpx not installed]"
    except Exception as exc:
        log_event("BACKEND_ERROR",{"backend":"openai","error_type":type(exc).__name__})
        return _safe_error("OpenAI",exc)

def call_xai(messages, system, model=None):
    try:
        import httpx
        key=_require_env_key("XAI_API_KEY")
        model=model or os.environ.get("ABIGAIL_XAI_MODEL","grok-4.3")
        with httpx.Client(timeout=GROQ_TIMEOUT) as c:
            r=c.post("https://api.x.ai/v1/chat/completions",
                     headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                     json={"model":model,"messages":[{"role":"system","content":system}]+messages,
                           "max_tokens":2048,"temperature":0.3})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except ImportError: return "[httpx not installed]"
    except Exception as exc:
        log_event("BACKEND_ERROR",{"backend":"xai","error_type":type(exc).__name__})
        return _safe_error("xAI",exc)

BACKEND_DISPATCH = {"groq":call_groq,"anthropic":call_anthropic,
                    "perplexity":call_perplexity,"ollama":call_ollama,
                    "openai":call_openai,"xai":call_xai}


# ── DRS / HAAP ────────────────────────────────────────────────────────────────
CONSTITUTIONAL_BLOCKS = [
    r"delete\s+(audit|log|governance|trail)",
    r"export\s+pii",
    r"disable\s+(auth|authentication|authorization|haap|governance)",
    r"grant\s+(root|admin|sudo)",
    r"bypass\s+(kill.?switch|sentinel|overwatch|haap)",
    r"modify\s+(audit|log)\s+record",
]
SENTINEL_PATTERNS = [
    r"ignore\s+(previous|prior|all|above)\s+instructions?",
    r"forget\s+(your|all|previous)",
    r"you\s+are\s+now\s+(a\s+)?(?!abigail)",
    r"pretend\s+(you\s+are|to\s+be)",
    r"jailbreak",r"DAN\b",r"do\s+anything\s+now",
    r"hypothetically\s+speaking.{0,30}(harm|weapon|exploit)",
    r"[\u200b-\u200f\u2028\u2029\ufeff]",
    # CMD_STYLE_INJECTION signals (SENT-CMD-001 through SENT-CMD-006)
    # Catches hostile command-shaped input not on the operator allowlist.
    # "status" and "help" do not match any of these patterns \u2014 no conflict.
    r"dump.{0,10}(config|env|key|secret|token|credential)",                         # SENT-CMD-001
    r"/api/(admin|internal|secret|debug|config|raw|v\d)",                           # SENT-CMD-002
    r"(show|reveal|print|echo|expose|list).{0,20}(key|token|secret|route|config)",  # SENT-CMD-003
    r"(role|grant|escalate).{0,15}(admin|root|operator|superuser)",                 # SENT-CMD-004
    r"(tool|function|call|invoke|execute|run).{0,20}(shell|bash|system|exec|eval)", # SENT-CMD-005
    r"(bypass|skip|ignore).{0,20}(auth|governance|gate|haap|sentinel)",             # SENT-CMD-006
]
_DRS_SIGNALS = [
    (r"delete|remove|drop|truncate",          8, "destructive verb"),
    (r"production|prod\b|live\s+system",     6, "production scope"),
    (r"deploy|push\s+to\s+main|merge\s+to", 6, "deployment action"),
    (r"secret|password|credential|api.?key",  10, "credential reference"),
    (r"sudo|root|admin",                       8, "privilege escalation"),
    (r"all\s+users|everyone|bulk",            5, "blast radius"),
    (r"external|third.?party|vendor",          4, "external exposure"),
    (r"irreversible|can.t\s+undo|permanent",  7, "irreversibility"),
    (r"now|immediately|skip\s+approval",      5, "urgency bypass"),
    (r"billing|payment|charge|invoice",        6, "financial action"),
]
_CONST_RE  = [re.compile(p,re.IGNORECASE) for p in CONSTITUTIONAL_BLOCKS]
_SENT_RE   = [re.compile(p,re.IGNORECASE|re.DOTALL) for p in SENTINEL_PATTERNS]
_SIGNAL_RE = [(re.compile(p,re.IGNORECASE),s,l) for p,s,l in _DRS_SIGNALS]

# Compound risk calibration:
# Individual deployment, production, billing, urgency, or permanence references
# remain low/medium risk in isolation. A JIT approval bonus applies only when the
# request combines active execution, production scope, material impact, and
# urgency or irreversibility.
_DRS_COMPOUND_EXECUTION = re.compile(
    r"\b(deploy|push\s+to\s+main|merge\s+to|release|roll\s*out|ship)\b",
    re.IGNORECASE,
)
_DRS_COMPOUND_PRODUCTION = re.compile(
    r"\b(production|prod\b|live\s+system)\b",
    re.IGNORECASE,
)
_DRS_COMPOUND_BROAD_IMPACT = re.compile(
    r"\b(all\s+users|everyone|bulk|billing|payment|charge|invoice)\b",
    re.IGNORECASE,
)
_DRS_COMPOUND_ESCALATOR = re.compile(
    r"\b(now|immediately|permanent|irreversible|can(?:no|')t\s+undo)\b",
    re.IGNORECASE,
)
_DRS_COMPOUND_BONUS = 30

def drs_score(text):
    hits, total = [], 0

    for rx, weight, label in _SIGNAL_RE:
        if rx.search(text):
            total += weight
            hits.append(f"{label}(+{weight})")

    compound_matches = {
        "execution": bool(_DRS_COMPOUND_EXECUTION.search(text)),
        "production": bool(_DRS_COMPOUND_PRODUCTION.search(text)),
        "broad_or_financial_impact": bool(
            _DRS_COMPOUND_BROAD_IMPACT.search(text)
        ),
        "urgency_or_irreversibility": bool(
            _DRS_COMPOUND_ESCALATOR.search(text)
        ),
    }

    if all(compound_matches.values()):
        total += _DRS_COMPOUND_BONUS
        hits.append(
            "compound high-impact irreversible execution"
            f"(+{_DRS_COMPOUND_BONUS})"
        )

    return min(total, 100), hits

def sentinel_check(text):
    for rx in _SENT_RE:
        m=rx.search(text)
        if m: return m.group(0)[:80]
    return None

def constitutional_check(text):
    for rx in _CONST_RE:
        m=rx.search(text)
        if m: return m.group(0)[:80]
    return None

def drs_verdict(score):
    if score<=20: return "SILENT_AUTONOMY",    "\033[32m",  "ALLOW"
    if score<=40: return "TRUST_BUT_VERIFY",   "\033[36m",  "ALLOW_FLAG"
    if score<=60: return "SHADOW_MONITOR",     "\033[33m",  "ALLOW_ALERT"
    if score<=80: return "JIT_AUTHORIZATION",  "\033[91m",  "HARD_STOP"
    if score<=95: return "FAILSAFE_REVIEW",    "\033[31m",  "TERMINAL_STOP"
    return             "CONSTITUTIONAL_BLOCK", "\033[35m",  "PERMANENT_BLOCK"

class HAAPViolation(Exception): pass

def haap_gate(user_input, agent_drs_ceiling=80):
    v=constitutional_check(user_input)
    if v:
        log_event("HAAP_CONSTITUTIONAL_BLOCK",{"layer":"-1","matched":v,"action":"PERMANENT_BLOCK"})
        raise HAAPViolation(f"HAAP Layer -1 — CONSTITUTIONAL BLOCK\nMatched: {v}\nNo override.")
    a=sentinel_check(user_input)
    if a:
        log_event("HAAP_SENTINEL_BLOCK",{"layer":"1","matched":a,"action":"HARD_STOP"})
        raise HAAPViolation("HAAP Layer 1 — SENTINEL GATE BLOCK\nAdversarial pattern detected.")
    score,signals=drs_score(user_input)
    mode,color,action=drs_verdict(score)
    if score>agent_drs_ceiling: action="HARD_STOP"; mode=f"CEILING_BREACH({agent_drs_ceiling})"
    log_event("HAAP_DRS_DECISION",{"layer":"3","score":score,"signals":signals,"mode":mode,"action":action})
    if action=="PERMANENT_BLOCK":
        raise HAAPViolation(f"HAAP Layer 3 — CONSTITUTIONAL BLOCK\nDRS:{score}/100")
    if action in ("HARD_STOP","TERMINAL_STOP"):
        raise HAAPViolation(f"HAAP Layer 3 — {action}\nDRS: {score}/100  Mode: {mode}\n"
                            f"Human authorization required.\nSignals: {', '.join(signals) or 'none'}")


# ── System prompt ─────────────────────────────────────────────────────────────
ABIGAIL_SYSTEM_PROMPT = """You are Abigail - CP-00, Constitutional Administrator of the LOGOS Agentic Software Firm.
Governed by David W. Smith, Founder & CEO, LOGOS Governance Systems Inc. US Provisional Patent 63/953,447.

Authority: agent lifecycle, Intent Token issuance (Ed25519), DRS routing, JIT queue, kill-switch, audit log.
Sprint 6: Docker + venv constitutional sandbox governance — you govern execution, you do not execute.

Hard limits: never modify Constitutional Bounds without board auth; never delete audit logs; never grant root/admin.
Silence Rule: ambiguity defaults to HALT and escalate, never interpret expansively.
Truthfulness: never claim auth/authz verified unless application explicitly provided it.
Style: concise, plain language, reference HAAP layer numbers only when directly relevant."""


# ── Kill-switch & Session ─────────────────────────────────────────────────────
class KillSwitch:
    def __init__(self): self.is_active=False; self._at=None
    def activate(self,principal="OPERATOR"):
        self.is_active=True; self._at=datetime.datetime.utcnow().isoformat()+"Z"
        log_event("KILL_SWITCH_ACTIVATED",{"activated_by":principal,"at":self._at})
    def clear(self,principal="OPERATOR"):
        self.is_active=False; log_event("KILL_SWITCH_CLEARED",{"cleared_by":principal})
    def check(self):
        if self.is_active: raise HAAPViolation("[KILL-SWITCH ACTIVE] All execution halted.")

# P0-3 (ABIGAIL-SPRINT-01): bound the conversation history so it cannot grow unbounded
# and be resent in full on every provider call. Keeps the last N messages (user+assistant).
SESSION_HISTORY_WINDOW = max(2, int(os.environ.get("ABIGAIL_SESSION_HISTORY_WINDOW", "20") or 20))


class SessionState:
    def __init__(self):
        self.turn_count=0; self.cumulative_drs=0; self.messages=[]; self.flags=[]
        # A1: one durable Sentinel session_id for this conversation's whole
        # lifetime (not reminted per turn — see process_message()).
        # session_started tracks whether /session/start has been called yet,
        # so it happens exactly once per conversation.
        self.sentinel_session_id=f"conv_{uuid.uuid4().hex}"
        self.session_started=False
    def record_turn(self,user_input,score,signals):
        self.turn_count+=1; self.cumulative_drs+=score
        if signals: self.flags.append({"turn":self.turn_count,"score":score,"signals":signals})
    def append_message(self, role, content):
        """Append a turn message and trim to the history window so resent context stays
        bounded (P0-3). Older messages are dropped, not silently retained forever."""
        self.messages.append({"role":role,"content":content})
        if len(self.messages) > SESSION_HISTORY_WINDOW:
            self.messages = self.messages[-SESSION_HISTORY_WINDOW:]
    def crsv(self): return self.cumulative_drs/self.turn_count if self.turn_count else 0.0
    def drift_warning(self):
        a=self.crsv()
        if a>=60: return f"[OverWatch] CRSV={a:.1f} — HIGH drift. Escalating to Tier 3."
        if a>=40: return f"[OverWatch] CRSV={a:.1f} — Elevated drift. Monitor active."
        if a>=25: return f"[OverWatch] CRSV={a:.1f} — Sustained medium-risk trajectory flagged."
        return None


class SessionRegistry:
    """Keyed session store — one SessionState per session key (P0-3). Replaces the single
    process-wide SessionState so conversation history, CRSV, and turn counters cannot bleed
    across clients. In-process dict for now (proves isolation before Sprint 02 swaps in a
    shared backend such as Redis); the key is threaded explicitly from the HTTP layer."""
    def __init__(self, default=None, max_sessions=2048):
        self._store = {}
        self._lock = threading.Lock()
        self._max = max(1, int(max_sessions))
        if default is not None:
            self._store["default"] = default
    def get_or_create(self, key):
        key = key or "default"
        with self._lock:
            s = self._store.get(key)
            if s is None:
                if len(self._store) >= self._max:
                    # Bound memory: evict an arbitrary non-default session.
                    for k in list(self._store.keys()):
                        if k != "default":
                            evicted = self._store.pop(k)
                            # A1: best-effort /session/end for the evicted
                            # conversation. Never fail-closed here — a failed
                            # cleanup call must not block creating the new
                            # session that triggered this eviction.
                            try:
                                _sentinel_session_end(evicted.sentinel_session_id)
                            except Exception:
                                pass
                            break
                s = SessionState()
                self._store[key] = s
            return s
    def peek(self, key):
        with self._lock:
            return self._store.get(key or "default")
    def __len__(self):
        with self._lock:
            return len(self._store)


# ── MR-05: MoE router mode + mode-aware provider dispatch ──────────────────────
def _resolve_moe_mode():
    """ABIGAIL_MOE_ROUTER_MODE: '0' single-backend, '1' dry-run router, '2' live router.
    Invalid values fail closed to '0' with an audit-safe warning."""
    m = os.environ.get("ABIGAIL_MOE_ROUTER_MODE", "0").strip()
    if m not in ("0", "1", "2"):
        log_event("MOE_ROUTER_CONFIG_WARNING", {"invalid_value_len": len(m), "fell_back_to": "0"})
        return "0"
    return m


def _moe_dispatch(
    raw,
    session,
    active_backend,
    system,
    score,
    *,
    sentinel_session_id,
    gov_tx_id,
    verdict_id,
):
    """Select, authorize, consume, execute, and inspect one provider call.

    Every mode uses the same Sentinel capability boundary. Router failure and
    unavailable providers fail closed; no automatic provider fallback executes.
    """
    mode = _resolve_moe_mode()
    backend = active_backend[0]

    def _execute(provider, meta):
        response, evidence = _governed_provider_execute(
            provider=provider,
            messages=session.messages,
            system=system,
            sentinel_session_id=sentinel_session_id,
            gov_tx_id=gov_tx_id,
            expected_verdict_id=verdict_id,
        )
        return response, meta, evidence

    # Mode 0 — exact configured backend, still capability-bound.
    if mode == "0" or not _MOE_DISPATCH_OK:
        meta = {
            "router_mode": "0",
            "selected_provider": backend,
            "dispatch_status": "executed",
            "live_dispatch": True,
            "fallback_used": False,
        }
        return _execute(backend, meta)

    # Mode 1 — router observes only; execution remains on active backend.
    if mode == "1":
        selected = backend
        try:
            card = _route_request(raw, score, [], None)
            if card is not None:
                if isinstance(card, dict):
                    selected = card.get("selected_provider", backend)
                else:
                    selected = getattr(card, "selected_provider", backend)
        except Exception as exc:
            log_event(
                "MOE_ROUTER_ERROR",
                {
                    "mode": "1",
                    "error_type": type(exc).__name__,
                },
            )

        meta = {
            "router_mode": "1",
            "selected_provider": backend,
            "observed_provider": selected,
            "dispatch_status": "executed_active_backend",
            "live_dispatch": True,
            "fallback_used": False,
            "reason": "dry_run_selection_only",
        }
        return _execute(backend, meta)

    # Mode 2 — selection only. Execution happens here after Sentinel authority.
    tier = (
        os.environ.get("ABIGAIL_SUBSCRIBER_TIER", "paid").strip()
        or "paid"
    )

    try:
        selection = _governed_route_selection(
            raw,
            drs_score=score,
            approval_state="cleared",
            cost_state={"approved": True},
            subscriber_tier=tier,
            dispatch_table=BACKEND_DISPATCH,
            current_backend=backend,
        )
    except Exception as exc:
        log_event(
            "MOE_ROUTER_ERROR",
            {
                "mode": "2",
                "error_type": type(exc).__name__,
            },
        )
        raise GovernedProviderError(
            "Governed provider selection failed"
        ) from exc

    if selection.get("selection_status") != "selected":
        log_event(
            "MOE_SELECTION_REJECTED",
            {
                "provider": selection.get("provider_selected"),
                "status": selection.get("selection_status"),
                "reason": selection.get("reason"),
            },
        )
        raise GovernedProviderError(
            "No provider passed governed selection"
        )

    provider = selection.get("resolved_provider") or selection.get(
        "provider_selected"
    )
    if not provider:
        raise GovernedProviderError(
            "Governed selection returned no executable provider"
        )

    meta = {
        "router_mode": "2",
        "selected_provider": provider,
        "routed_provider": selection.get("routed_provider"),
        "dispatch_status": "selected_then_executed",
        "live_dispatch": True,
        "fallback_used": False,
        "reason": selection.get("reason"),
        "route_request_type": selection.get("route_request_type"),
    }

    log_event(
        "MOE_ROUTE_DECISION",
        {
            "router_mode": "2",
            "selected_provider": provider,
            "dispatch_status": "selected",
            "fallback_used": False,
        },
    )

    return _execute(provider, meta)




# ── Shared dispatch ───────────────────────────────────────────────────────────
def process_message(raw, session, kill_switch, active_backend, approval_meta=None,
                    step_up_ok=False, department_id=None, agent_id=None):
    try: kill_switch.check()
    except HAAPViolation as e:
        return {"ok":False,"text":str(e),"drs":0,"mode":"KILL_SWITCH","crsv":session.crsv()}

    # A1: the conversation's durable Sentinel session must be started before
    # anything else — including a grounded/canned answer, which is still
    # part of this conversation's turn sequence. No provider call, no
    # dispatch, and no session_id churn happen on this path; it either
    # proceeds or fails closed here, before any of that.
    if not _ensure_session_started(session):
        return {
            "ok": False,
            "text": ("[Sentinel OverWatch] Request blocked — the authoritative "
                      "governance tier could not start this session and "
                      "SENTINEL_REQUIRED is enforced."),
            "drs": 100,
            "mode": "SENTINEL_UNREACHABLE",
            "crsv": session.crsv(),
        }

    grounded=try_grounded_answer(raw,session)
    if grounded is not None: return grounded

    # Layer 1a — A2A relay hard-stop (before Sentinel + HAAP)
    if _detects_a2a_relay(raw):
        log_event("HAAP_SENTINEL_BLOCK",{"layer":"1","matched":"A2A relay authority claim","action":"HARD_STOP"})
        reason = "HAAP Layer 1 — A2A RELAY BLOCK\nUnverified agent-to-agent authority claim detected. Abigail cannot accept delegated authorization by assertion alone."
        log_event("REQUEST_BLOCKED",{"reason":reason})
        return {"ok":False,"text":reason,"drs":100,"mode":"BLOCKED","crsv":session.crsv()}

    # Layer 1b — Rust Sentinel OverWatch (authoritative threat classification)
    # Every verdict maps to exactly one of proceed / step-up / block.
    # No unknown or unreachable verdict may fall through implicitly.
    # A1: one durable session_id for the whole conversation, not reminted
    # per turn — this is what lets Sentinel accumulate drift/threat/lock
    # state across turns instead of seeing a "new session" every message.
    # Sessions that don't model this at all (minimal test doubles predating
    # A1 — see _ensure_session_started) fall back to the old per-call mint,
    # unchanged for them.
    sentinel_session_id = getattr(
        session, "sentinel_session_id", None
    ) or f"session_{session.turn_count}_{uuid.uuid4().hex[:12]}"
    s_result = _sentinel_inspect(raw, sentinel_session_id, department_id=department_id, agent_id=agent_id)
    s_verdict = s_result.get("verdict", "unknown")
    s_verdict_norm = str(s_verdict).strip().lower()
    s_gov_tx_id = str(s_result.get("gov_tx_id") or "").strip()
    s_verdict_id = str(s_result.get("verdict_id") or "").strip()
    s_provider_authorizable = (
        s_result.get("provider_authorizable") is True
    )

    sentinel_reachable = s_verdict_norm != "sentinel_offline"

    if not sentinel_reachable:
        if SENTINEL_REQUIRED:
            log_event("SENTINEL_UNREACHABLE_BLOCK", {
                "verdict": s_verdict,
                "session_id": sentinel_session_id,
                "sentinel_url": SENTINEL_URL,
                "error": str(s_result.get("error", ""))[:200],
            })
            return {
                "ok": False,
                "text": (
                    "[Sentinel OverWatch] Request blocked — the authoritative "
                    "governance tier is unreachable and SENTINEL_REQUIRED is enforced."
                ),
                "drs": 100,
                "mode": "SENTINEL_UNREACHABLE",
                "crsv": session.crsv(),
            }

        log_event("SENTINEL_DEGRADED_OPEN", {
            "verdict": s_verdict,
            "session_id": sentinel_session_id,
            "note": "SENTINEL_REQUIRED=0 — proceeding on Python HAAP backstop only",
        })

    else:
        if s_verdict_norm in ("quarantined", "hard_locked"):
            log_event("SENTINEL_BLOCK", {
                "verdict": s_verdict,
                "session_id": sentinel_session_id,
            })
            return {
                "ok": False,
                "text": (
                    f"[Sentinel OverWatch] Request blocked — verdict: "
                    f"{s_verdict_norm.upper()}. Session flagged for review."
                ),
                "drs": 100,
                "mode": "SENTINEL_BLOCK",
                "crsv": session.crsv(),
            }

        if s_verdict_norm == "haap_gated":
            log_event("SENTINEL_HAAP_GATED", {
                "verdict": s_verdict,
                "session_id": sentinel_session_id,
            })
            return {
                "ok": False,
                "text": (
                    "[Sentinel OverWatch] HAAP gate — human re-authorization "
                    "is required before this request may proceed."
                ),
                "drs": 100,
                "mode": "HAAP_GATED",
                "crsv": session.crsv(),
            }

        if s_verdict_norm == "restricted":
            log_event(
                "SENTINEL_STEP_UP_REQUIRED",
                {
                    "verdict": s_verdict,
                    "session_id": sentinel_session_id,
                    "step_up_present": bool(step_up_ok),
                    "provider_authorizable": False,
                },
            )
            return {
                "ok": False,
                "text": (
                    "[Sentinel OverWatch] Elevated risk (RESTRICTED) — "
                    "provider execution authority was not issued. A new "
                    "fully approved transaction is required."
                ),
                "drs": 80,
                "mode": "STEP_UP_REQUIRED",
                "crsv": session.crsv(),
            }

        elif s_verdict_norm == "approved":
            if not (
                s_provider_authorizable
                and s_gov_tx_id
                and s_verdict_id
            ):
                log_event(
                    "SENTINEL_APPROVAL_EVIDENCE_MISSING",
                    {
                        "session_id": sentinel_session_id,
                        "provider_authorizable": (
                            s_provider_authorizable
                        ),
                        "gov_tx_id_present": bool(s_gov_tx_id),
                        "verdict_id_present": bool(s_verdict_id),
                    },
                )
                return {
                    "ok": False,
                    "text": (
                        "[Sentinel OverWatch] Request blocked — approval "
                        "evidence was incomplete and no provider authority "
                        "can be established."
                    ),
                    "drs": 100,
                    "mode": "SENTINEL_AUTHORITY_ERROR",
                    "crsv": session.crsv(),
                }

            log_event(
                "SENTINEL_APPROVED",
                {
                    "verdict": str(s_verdict).upper(),
                    "session_id": sentinel_session_id,
                    "gov_tx_id": s_gov_tx_id,
                    "verdict_id": s_verdict_id,
                    "action": "PROCEED_TO_HAAP",
                },
            )

        else:
            log_event("SENTINEL_UNKNOWN_VERDICT_BLOCK", {
                "verdict": s_verdict,
                "session_id": sentinel_session_id,
            })
            return {
                "ok": False,
                "text": (
                    "[Sentinel OverWatch] Request blocked — unrecognized verdict "
                    f"'{s_verdict_norm}'. Fail-closed default."
                ),
                "drs": 100,
                "mode": "SENTINEL_BLOCK",
                "crsv": session.crsv(),
            }

    try: haap_gate(raw,agent_drs_ceiling=80)
    except HAAPViolation as e:
        log_event("REQUEST_BLOCKED",{"reason":str(e)[:200]})
        return {"ok":False,"text":str(e),"drs":0,"mode":"BLOCKED","crsv":session.crsv()}
    # MM-03: enforced approval gate — hard-blocks above win; if not blocked but the shadow
    # context flags human_approval_required, stop here BEFORE any inference/spend/action.
    if _approval_gate_blocks(approval_meta):
        log_event("APPROVAL_REQUIRED_ENFORCED", {
            "gov_tx_id": (approval_meta or {}).get("gov_tx_id"),
            "manifest_id": (approval_meta or {}).get("manifest_id"),
            "risk_level": (approval_meta or {}).get("risk_level"),
            "command_style_signal": (approval_meta or {}).get("command_style_signal"),
        })
        return build_approval_required_response(approval_meta, session)
    # UX-01: benign public product/identity/help questions get useful, governed answers
    # instead of the topology-protection fallback. Adversarial and protected-disclosure
    # input has already been hard-blocked by Sentinel/HAAP above; the classifier's guard
    # keeps internal-probe phrasing on the governed pipeline.
    _pub = public_intent_answer(raw, session)
    if _pub is not None:
        return _pub
    score,signals=drs_score(raw)
    session.record_turn(raw,score,signals)
    drift=session.drift_warning()
    if drift: log_event("OVERWATCH_DRIFT",{"crsv":session.crsv(),"warning":drift})
    mode,_,_=drs_verdict(score)
    # Tacit Pre-Pass — ephemeral Tacit Context Card, non-blocking, non-mutating
    _card = _build_tacit_card(raw, score, signals, session) if _TACIT_PREPASS_OK else None
    if _card:
        log_event("TACIT_PREPASS_CARD", {
            k: _card[k] for k in (
                "card_id", "request_type", "confidence",
                "escalation_required", "memory_policy", "store1_mutation",
            )
        })
    _system = ABIGAIL_SYSTEM_PROMPT
    if _card and _card.get("response_guidance"):
        _system = ABIGAIL_SYSTEM_PROMPT + "\n\n[TACIT GUIDANCE]\n" + _card["response_guidance"]
    # Model Router Shadow Pass — MR-01: observe, score, log. Does not alter dispatch.
    _route_card = None
    if _MODEL_ROUTER_OK:
        try:
            _route_card = _route_request(raw, score, signals, _card)
            if _route_card:
                log_event("MODEL_ROUTE_CARD", _safe_route_fields(_route_card))
        except Exception as _rte:
            log_event("MODEL_ROUTER_ERROR", {"error_type": type(_rte).__name__})
    # Provider Adapter Dry Run — MR-02: envelope + log only. No provider call. No dispatch change.
    if _PROVIDER_ADAPTER_OK and _route_card:
        try:
            _adapter = _provider_registry.get(
                _route_card.get("selected_provider", "current_backend")
            )
            _req_env = _adapter.build_request(_route_card, session)
            _adapter.execute(_req_env)  # dry run only — output never returned to user
            log_event("PROVIDER_DRY_RUN_CARD", _safe_provider_fields(_req_env.model_dump()))
        except Exception as _pae:
            log_event("PROVIDER_ADAPTER_ERROR", {"error_type": type(_pae).__name__})
    session.append_message("user", raw)
    t = time.monotonic()

    try:
        response, _router_meta, _execution_evidence = _moe_dispatch(
            raw,
            session,
            active_backend,
            _system,
            score,
            sentinel_session_id=sentinel_session_id,
            gov_tx_id=s_gov_tx_id,
            verdict_id=s_verdict_id,
        )
    except GovernedProviderError as exc:
        log_event(
            "GOVERNED_PROVIDER_EXECUTION_BLOCKED",
            {
                "gov_tx_id": s_gov_tx_id,
                "verdict_id": s_verdict_id,
                "error_type": type(exc).__name__,
                "reason": str(exc)[:180],
            },
        )
        return {
            "ok": False,
            "text": (
                "[Governed execution] Provider inference was blocked "
                "because the authorization or outbound evidence chain "
                "did not complete."
            ),
            "drs": score,
            "mode": "PROVIDER_EXECUTION_BLOCKED",
            "crsv": round(session.crsv(), 1),
            "governance": {
                "gov_tx_id": s_gov_tx_id,
                "verdict_id": s_verdict_id,
                "execution_status": "blocked",
            },
        }

    # PUBLIC disclosure clamp — applied only after Sentinel approved the raw
    # provider output. This transformation can only reduce disclosed content.
    if score <= 20 and _public_response_overexposed(response):
        log_event(
            "PUBLIC_DISCLOSURE_CLAMP",
            {
                "action": "REDACTED_TO_PUBLIC_FALLBACK",
                "turn": session.turn_count,
            },
        )
        response = _public_safe_fallback()

    session.append_message("assistant", response)

    log_event(
        "TURN_COMPLETE",
        {
            "turn": session.turn_count,
            "backend": _router_meta.get(
                "selected_provider",
                active_backend[0],
            ),
            "router_mode": _router_meta.get("router_mode"),
            "drs": score,
            "elapsed": round(time.monotonic() - t, 2),
            "crsv": round(session.crsv(), 1),
            "gov_tx_id": s_gov_tx_id,
            "capability_id": _execution_evidence.get(
                "capability_id"
            ),
        },
    )

    out = {
        "ok": True,
        "text": response,
        "drs": score,
        "mode": mode,
        "crsv": round(session.crsv(), 1),
        "router": _router_meta,
        "governance": _execution_evidence,
    }
    if drift: out["drift"]=drift
    return out


# ── Sprint 6: Docker + venv Constitutional Sandbox ───────────────────────────
# Abigail = Control Plane. She governs. Containers execute.
# Every agent gets: Docker isolation + Python venv + constitutional JSON.
# DRS ceiling maps to resource limits. Ceiling > 60 = JIT required.

# ── Slice A: interim scope ceilings (until Slice C adds scope to the YAMLs) ─────
# No agent definition declares scope today (0/125 YAMLs), so these are the ceilings a
# caller may NOT exceed for a definition-less agent. They equal the pre-existing safe
# defaults, so legitimate default-tier spawns are unaffected — but any body-supplied
# value ABOVE them is a caller-side escalation attempt and is rejected + audited.
#   agency_level=2       : the modal department authority; only ENG/OPS are authored at 3,
#                          so 2 is the safe least-privilege cap for an undeclared agent.
#   drs_ceiling=40       : the existing default and the minimal resource tier (0.5cpu/256m);
#                          >40 raises risk tolerance/resources, and >60 is already JIT-blocked.
#   permitted_resources  : the single least-privilege workspace path; any extra path is escalation.
_INTERIM_MAX_AGENCY_LEVEL   = 2
_INTERIM_MAX_DRS_CEILING    = 40
_INTERIM_PERMITTED_RESOURCES = ["/workspace"]


def _safe_int(v):
    try: return int(v)
    except (TypeError, ValueError): return None


def _resolve_agent_scope(body, agent_def):
    """Slice A — the agent definition (or the interim ceiling when it declares nothing)
    is authoritative. A body-supplied value that EXCEEDS the allowed value is a caller-side
    escalation attempt and is REJECTED, not clamped (clamping silently permits probing).

    Returns (scope, violations). scope is the resolved {agency_level, drs_ceiling,
    permitted_resources} to use; violations is a list of {field, requested, allowed, ...}.
    A non-empty violations list means the request must be refused.
    """
    violations = []

    # agency_level — higher = more authority
    allowed_agency = _safe_int(agent_def.get("agency_level")) or _INTERIM_MAX_AGENCY_LEVEL
    agency = allowed_agency
    if body.get("agency_level") is not None:
        req = _safe_int(body.get("agency_level"))
        if req is None or req > allowed_agency:
            violations.append({"field":"agency_level","requested":body.get("agency_level"),
                               "allowed":allowed_agency})
        else:
            agency = req

    # drs_ceiling — higher = more risk tolerance / more resources
    allowed_ceiling = _safe_int(agent_def.get("drs_ceiling")) or _INTERIM_MAX_DRS_CEILING
    ceiling = allowed_ceiling
    if body.get("drs_ceiling") is not None:
        req = _safe_int(body.get("drs_ceiling"))
        if req is None or req > allowed_ceiling:
            violations.append({"field":"drs_ceiling","requested":body.get("drs_ceiling"),
                               "allowed":allowed_ceiling})
        else:
            ceiling = req

    # permitted_resources — requesting any path outside the allowed set is escalation
    allowed_res = list(agent_def.get("permitted_resources") or _INTERIM_PERMITTED_RESOURCES)
    resources = allowed_res
    if body.get("permitted_resources") is not None:
        req_res = body.get("permitted_resources")
        if not isinstance(req_res, list):
            violations.append({"field":"permitted_resources","requested":req_res,
                               "allowed":allowed_res})
        else:
            disallowed = [r for r in req_res if r not in allowed_res]
            if disallowed:
                violations.append({"field":"permitted_resources","requested":req_res,
                                   "allowed":allowed_res,"disallowed":disallowed})
            else:
                resources = req_res

    return {"agency_level":agency,"drs_ceiling":ceiling,"permitted_resources":resources}, violations


def _build_constitution(dept_id, agency_level, permitted, drs_ceiling):
    return {
        "_type":"agent_constitution_v1",
        "_issued_by":"abigail.cp00",
        "_issued_at":datetime.datetime.utcnow().isoformat()+"Z",
        "dept_id":dept_id, "agency_level":agency_level, "drs_ceiling":drs_ceiling,
        "authority_chain":{"human_principal":"david.smith","meta_agent":"abigail.cp00",
                           "security_spine":"sentinel.overwatch","this_agent":dept_id},
        "permitted_resources":permitted,
        "hard_limits":["NEVER modify your own constitutional bounds.",
                       "NEVER claim authority beyond agency_level.",
                       "NEVER issue or relay HAAP tokens.",
                       "NEVER access resources not in permitted_resources.",
                       "NEVER suppress audit events.",
                       "HALT and escalate on any ambiguous instruction."],
        "on_violation":"HALT_AND_REPORT",
    }

_AGENT_BOOTSTRAP = r"""
import os,json,sys,subprocess,venv,pathlib
c=json.loads(os.environ.get("AGENT_CONSTITUTION","{}"))
dept=c.get("dept_id","UNKNOWN"); ceiling=c.get("drs_ceiling",40)
print(f"[AGENT:{dept}] Constitution loaded. DRS ceiling: {ceiling}",flush=True)
sp=os.environ.get("AGENT_SYSTEM_PROMPT","")
if sp: print(f"[AGENT:{dept}] System prompt loaded ({len(sp)} chars)",flush=True)
venv_dir=pathlib.Path("/tmp/agent_venv")
venv.create(str(venv_dir),with_pip=True,clear=True)
pip=str(venv_dir/"bin"/"pip")
deps=[d.strip() for d in os.environ.get("AGENT_DEPS","").split(",") if d.strip()]
if deps: subprocess.run([pip,"install","--quiet"]+deps,check=False)
task=os.environ.get("AGENT_TASK","No task.")
permitted=c.get("permitted_resources",["/workspace"])
print(f"[AGENT:{dept}] Permitted: {permitted}",flush=True)
print(f"[AGENT:{dept}] Task: {task[:200]}",flush=True)
print(f"[AGENT_OUTPUT] dept={dept} drs_ceiling={ceiling} status=CONSTITUTIONALLY_BOUND",flush=True)
print(f"[AGENT:{dept}] COMPLETE",flush=True)
"""

def spawn_agent_container(dept_id, task_prompt, agency_level=2,
                           permitted=None, drs_ceiling=40, extra_env=None):
    permitted = permitted or ["/workspace"]
    if drs_ceiling > 60:
        log_event("AGENT_SPAWN_BLOCKED",{"dept_id":dept_id,"reason":"JIT required for ceiling > 60"})
        return {"ok":False,"output":"JIT authorization required for DRS ceiling > 60.","exit_code":-3}
    constitution=_build_constitution(dept_id,agency_level,permitted,drs_ceiling)
    cpu,mem=("0.5","256m") if drs_ceiling<=40 else ("1.0","512m")
    env_vars={"AGENT_CONSTITUTION":json.dumps(constitution),
              "AGENT_TASK":task_prompt[:2000],"AGENT_DEPT":dept_id,
              "PYTHONUNBUFFERED":"1",**(extra_env or {})}
    cmd=["docker","run","--rm",
         "--name",f"asf-agent-{dept_id}-{uuid.uuid4().hex[:8]}",
         "--network",AGENT_NETWORK,"--cpus",cpu,"--memory",mem,
         "--read-only","--tmpfs","/tmp:size=128m",
         f"--stop-timeout={AGENT_TIMEOUT}"]
    for k,v in env_vars.items(): cmd+=["-e",f"{k}={v}"]
    cmd+=[AGENT_BASE_IMAGE,"python3","-c",_AGENT_BOOTSTRAP]
    eid=str(uuid.uuid4())
    log_event("AGENT_SPAWN_ATTEMPT",{"event_id":eid,"dept_id":dept_id,
                                      "drs_ceiling":drs_ceiling,"task_preview":task_prompt[:100]})
    try:
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=AGENT_TIMEOUT+10)
        ok=result.returncode==0
        output=result.stdout+(result.stderr if not ok else "")
        log_event("AGENT_SPAWN_COMPLETE",{"event_id":eid,"dept_id":dept_id,
                                           "exit_code":result.returncode,"success":ok})
        return {"ok":ok,"output":output,"exit_code":result.returncode,"audit_event_id":eid,
                "constitution_hash":hashlib.sha256(
                    json.dumps(constitution,sort_keys=True).encode()).hexdigest()[:16]}
    except subprocess.TimeoutExpired:
        log_event("AGENT_SPAWN_TIMEOUT",{"event_id":eid,"dept_id":dept_id})
        return {"ok":False,"output":"Agent timed out.","exit_code":-1,"audit_event_id":eid}
    except FileNotFoundError:
        log_event("AGENT_SPAWN_NO_DOCKER",{"event_id":eid})
        return {"ok":False,"output":"Docker not available. Run via docker-compose up.",
                "exit_code":-2,"audit_event_id":eid}
    except Exception as e:
        log_event("AGENT_SPAWN_ERROR",{"event_id":eid,"error":str(e)})
        return {"ok":False,"output":str(e),"exit_code":-1,"audit_event_id":eid}


# ── Sentinel health proxy ─────────────────────────────────────────────────────
def _sentinel_health():
    try:
        import httpx
        r=httpx.get(f"{SENTINEL_URL}/health",timeout=3)
        return {"ok":True,"status":r.json()}
    except Exception as e: return {"ok":False,"error":str(e)}

def _sentinel_inspect(payload:str, session_id:str, department_id:str=None, agent_id:str=None) -> dict:
    """Route inbound message through Rust Sentinel /inspect before Python DRS.

    Gate 2 (F-GM-005): department_id/agent_id, when present, must already be
    validated against the active registry (see _resolve_dept_for_spine) — this
    function sends whatever it's given as-is. department_id now selects
    Sentinel's per-department drift threshold; see FINDINGS.md:
    DEPT_THRESHOLD_CLIENT_SELECTABLE for why that's a known, tracked bypass
    surface rather than an authenticated guarantee.
    """
    if not SENTINEL_SERVICE_TOKEN:
        log_event("SENTINEL_AUTH_MISCONFIGURED", {"endpoint":"/inspect"})
        return {"ok":False,"verdict":"sentinel_auth_missing",
                "approved":False,"error":"Sentinel service token missing"}
    try:
        import httpx
        _body = {"payload":payload,"session_id":session_id}
        if department_id: _body["department_id"] = department_id
        if agent_id: _body["agent_id"] = agent_id
        r=httpx.post(
            f"{SENTINEL_URL}/inspect",
            headers={"Authorization":f"Bearer {SENTINEL_SERVICE_TOKEN}"},
            json=_body,
            timeout=5)
        if r.status_code != 200:
            log_event("SENTINEL_INSPECT_REJECTED",
                      {"status":r.status_code})
            return {"ok":False,"verdict":"sentinel_rejected",
                    "approved":False,"status":r.status_code}
        return r.json()
    except Exception as e:
        log_event("SENTINEL_INSPECT_ERROR",{"error":str(e)})
        return {"ok":False,"verdict":"sentinel_offline","approved":False,"error":str(e)}


# ── A1: durable session lifecycle — /session/start, /session/end ───────────
def _sentinel_session_start(session_id: str, actor_id: str = "abigail") -> tuple:
    """POST /session/start. Called exactly once per conversation (see
    _ensure_session_started). Returns (ok, info)."""
    if not SENTINEL_SERVICE_TOKEN:
        log_event("SENTINEL_AUTH_MISCONFIGURED", {"endpoint": "/session/start"})
        return (False, {"error": "Sentinel service token missing"})
    try:
        import httpx
        r = httpx.post(
            f"{SENTINEL_URL}/session/start",
            headers={"Authorization": f"Bearer {SENTINEL_SERVICE_TOKEN}"},
            json={"session_id": session_id, "actor_id": actor_id},
            timeout=5)
        if r.status_code != 200:
            log_event("SENTINEL_SESSION_START_REJECTED", {"status": r.status_code})
            return (False, {"status": r.status_code})
        return (True, r.json())
    except Exception as e:
        log_event("SENTINEL_SESSION_START_ERROR", {"error": str(e)})
        return (False, {"error": str(e)})


def _sentinel_session_end(session_id: str, actor_id: str = "abigail", escalated: bool = False) -> bool:
    """POST /session/end. Best-effort cleanup — deliberately NOT fail-closed:
    a failed call here must never block creating a new session or exiting
    the CLI. Returns whether the call was acknowledged."""
    if not SENTINEL_SERVICE_TOKEN:
        return False
    try:
        import httpx
        r = httpx.post(
            f"{SENTINEL_URL}/session/end",
            headers={"Authorization": f"Bearer {SENTINEL_SERVICE_TOKEN}"},
            json={"session_id": session_id, "actor_id": actor_id, "escalated": escalated},
            timeout=5)
        return r.status_code == 200
    except Exception as e:
        log_event("SENTINEL_SESSION_END_ERROR", {"error": str(e)})
        return False


def _ensure_session_started(session) -> bool:
    """A1: idempotent gate — calls /session/start exactly once for this
    conversation's SessionState. Returns True once the session is (now or
    already) started; False when a required start could not be established,
    in which case the CALLER must refuse the current turn/request (fail
    closed) rather than proceed with an unstarted governance session. Gated
    by the same SENTINEL_REQUIRED policy /inspect already uses — not a new
    policy, applied to a new call site.

    Duck-typed session objects that don't model conversation lifecycle at
    all (minimal test doubles predating A1, e.g. objects only providing
    turn_count/crsv()) are treated as already-started rather than crashing
    or gaining a new hard network dependency they were never designed
    around — the same accommodation command_bus.py already makes elsewhere
    via hasattr(session, 'crsv'). Real SessionState always has
    session_started, so production callers always go through the full
    gate below."""
    if getattr(session, "session_started", True):
        return True
    ok, info = _sentinel_session_start(session.sentinel_session_id)
    if ok:
        session.session_started = True
        return True
    if SENTINEL_REQUIRED:
        log_event("SENTINEL_SESSION_START_BLOCK", {
            "session_id": session.sentinel_session_id,
            "sentinel_url": SENTINEL_URL,
            "error": str((info or {}).get("error", ""))[:200],
        })
        return False
    log_event("SENTINEL_SESSION_START_DEGRADED_OPEN", {
        "session_id": session.sentinel_session_id,
        "note": "SENTINEL_REQUIRED=0 — proceeding on Python HAAP backstop only",
    })
    session.session_started = True
    return True



class GovernedProviderError(RuntimeError):
    """Typed failure raised when governed provider execution cannot complete."""

    def __init__(
        self,
        message,
        *,
        terminal_state="UNAVAILABLE",
        provider_called=False,
        capability_consumed=False,
        governance=None,
    ):
        super().__init__(message)
        self.terminal_state = str(terminal_state or "BLOCKED").upper()
        self.provider_called = bool(provider_called)
        self.capability_consumed = bool(capability_consumed)
        self.governance = dict(governance or {})


def _sentinel_headers():
    if not SENTINEL_SERVICE_TOKEN:
        raise GovernedProviderError("Sentinel service token missing")
    return {
        "Authorization": f"Bearer {SENTINEL_SERVICE_TOKEN}",
        "Content-Type": "application/json",
    }


def _resolve_provider_model(provider):
    """Return the exact model bound into the provider capability."""
    resolvers = {
        "groq": lambda: os.environ.get(
            "GROQ_MODEL", "llama-3.3-70b-versatile"
        ).strip(),
        "anthropic": lambda: os.environ.get(
            "ABIGAIL_ANTHROPIC_MODEL", "claude-sonnet-5"
        ).strip(),
        "perplexity": lambda: os.environ.get(
            "PERPLEXITY_MODEL", "sonar"
        ).strip(),
        "ollama": lambda: os.environ.get(
            "OLLAMA_MODEL", "llama3"
        ).strip(),
        "openai": lambda: os.environ.get(
            "ABIGAIL_OPENAI_MODEL", "gpt-4o"
        ).strip(),
        "xai": lambda: os.environ.get(
            "ABIGAIL_XAI_MODEL", "grok-4.3"
        ).strip(),
    }

    resolver = resolvers.get(provider)
    if resolver is None:
        raise GovernedProviderError(
            f"Unknown or unsupported provider: {provider}"
        )

    model = resolver()
    if not model:
        raise GovernedProviderError(
            f"Configured model is empty for provider: {provider}"
        )
    return model


def _sentinel_provider_authorize(
    *,
    gov_tx_id,
    session_id,
    backend,
    model,
    action_class="llm_inference",
):
    try:
        import httpx

        response = httpx.post(
            f"{SENTINEL_URL}/provider/authorize",
            headers=_sentinel_headers(),
            json={
                "gov_tx_id": gov_tx_id,
                "session_id": session_id,
                "backend": backend,
                "model": model,
                "action_class": action_class,
            },
            timeout=5,
        )
    except Exception as exc:
        log_event(
            "PROVIDER_CAPABILITY_AUTHORIZE_ERROR",
            {"error_type": type(exc).__name__},
        )
        raise GovernedProviderError(
            "Sentinel provider authorization is unreachable"
        ) from exc

    try:
        body = response.json()
    except Exception as exc:
        raise GovernedProviderError(
            "Sentinel provider authorization returned invalid JSON"
        ) from exc

    if response.status_code != 200 or not body.get("ok"):
        log_event(
            "PROVIDER_CAPABILITY_AUTHORIZE_REJECTED",
            {
                "status": response.status_code,
                "error": str(body.get("error", ""))[:160],
                "backend": backend,
                "model": model,
            },
        )
        raise GovernedProviderError(
            "Sentinel did not authorize provider execution"
        )

    required = (
        "capability_id",
        "decision_id",
        "gov_tx_id",
        "session_id",
        "backend",
        "model",
        "verdict_id",
    )
    missing = [key for key in required if not body.get(key)]
    if missing:
        raise GovernedProviderError(
            "Sentinel authorization evidence is incomplete"
        )

    if (
        body["gov_tx_id"] != gov_tx_id
        or body["session_id"] != session_id
        or body["backend"] != backend
        or body["model"] != model
    ):
        raise GovernedProviderError(
            "Sentinel authorization scope does not match request"
        )

    return body


def _sentinel_provider_consume(
    *,
    capability_id,
    gov_tx_id,
    session_id,
    backend,
    model,
):
    try:
        import httpx

        response = httpx.post(
            f"{SENTINEL_URL}/provider/consume",
            headers=_sentinel_headers(),
            json={
                "capability_id": capability_id,
                "gov_tx_id": gov_tx_id,
                "session_id": session_id,
                "backend": backend,
                "model": model,
            },
            timeout=5,
        )
    except Exception as exc:
        log_event(
            "PROVIDER_CAPABILITY_CONSUME_ERROR",
            {"error_type": type(exc).__name__},
        )
        raise GovernedProviderError(
            "Sentinel capability consumption is unreachable"
        ) from exc

    try:
        body = response.json()
    except Exception as exc:
        raise GovernedProviderError(
            "Sentinel capability consumption returned invalid JSON"
        ) from exc

    if (
        response.status_code != 200
        or not body.get("authorized")
        or body.get("outcome") != "CAPABILITY_CONSUMED"
    ):
        log_event(
            "PROVIDER_CAPABILITY_CONSUME_REJECTED",
            {
                "status": response.status_code,
                "outcome": str(body.get("outcome", ""))[:100],
                "backend": backend,
                "model": model,
            },
        )
        raise GovernedProviderError(
            "Provider capability was not consumed"
        )

    return body


def _sentinel_outbound(payload, session_id):
    try:
        import httpx

        response = httpx.post(
            f"{SENTINEL_URL}/outbound",
            headers=_sentinel_headers(),
            json={
                "payload": payload,
                "session_id": session_id,
            },
            timeout=5,
        )
    except Exception as exc:
        log_event(
            "SENTINEL_OUTBOUND_ERROR",
            {"error_type": type(exc).__name__},
        )
        raise GovernedProviderError(
            "Sentinel outbound inspection is unreachable"
        ) from exc

    try:
        body = response.json()
    except Exception as exc:
        raise GovernedProviderError(
            "Sentinel outbound inspection returned invalid JSON"
        ) from exc

    verdict = str(body.get("verdict", "UNKNOWN")).strip().upper()
    if response.status_code != 200 or verdict != "APPROVED":
        log_event(
            "SENTINEL_OUTBOUND_BLOCK",
            {
                "status": response.status_code,
                "verdict": verdict,
                "session_id": session_id,
            },
        )
        raise GovernedProviderError(
            f"Sentinel outbound verdict was {verdict}"
        )

    return body


def _call_provider_exact(provider, model, messages, system):
    adapter = BACKEND_DISPATCH.get(provider)
    if adapter is None:
        raise GovernedProviderError(
            f"Provider is not live-wired: {provider}"
        )

    try:
        if provider == "perplexity":
            text = adapter(messages=messages, system=system)
        else:
            text = adapter(
                messages=messages,
                system=system,
                model=model,
            )
    except GovernedProviderError:
        raise
    except Exception as exc:
        log_event(
            "GOVERNED_PROVIDER_ADAPTER_ERROR",
            {
                "backend": provider,
                "model": model,
                "error_type": type(exc).__name__,
            },
        )
        raise GovernedProviderError(
            f"Provider adapter raised an exception: {provider}"
        ) from exc

    if not isinstance(text, str) or not text.strip():
        raise GovernedProviderError(
            f"Provider returned no usable output: {provider}"
        )

    clean = text.strip()
    lowered = clean.lower()
    if clean.startswith("[") and (
        " error " in f" {lowered} "
        or "not installed" in lowered
        or "only localhost urls permitted" in lowered
    ):
        raise GovernedProviderError(
            f"Provider adapter failed: {provider}"
        )

    return clean


def _governed_provider_execute(
    *,
    provider,
    messages,
    system,
    sentinel_session_id,
    gov_tx_id,
    expected_verdict_id,
):
    """Authorize, burn, execute, and inspect one exact provider call."""
    model = _resolve_provider_model(provider)

    authorization = _sentinel_provider_authorize(
        gov_tx_id=gov_tx_id,
        session_id=sentinel_session_id,
        backend=provider,
        model=model,
    )

    if authorization.get("verdict_id") != expected_verdict_id:
        raise GovernedProviderError(
            "Provider capability is bound to an unexpected Sentinel verdict"
        )

    consumption = _sentinel_provider_consume(
        capability_id=authorization["capability_id"],
        gov_tx_id=gov_tx_id,
        session_id=sentinel_session_id,
        backend=provider,
        model=model,
    )

    # The external execution boundary occurs only after successful atomic burn.
    try:
        text = _call_provider_exact(
            provider,
            model,
            messages,
            system,
        )
    except GovernedProviderError as exc:
        exc.capability_consumed = True
        exc.governance.update({
            "gov_tx_id": gov_tx_id,
            "verdict_id": expected_verdict_id,
            "decision_id": authorization["decision_id"],
            "capability_id": authorization["capability_id"],
            "backend": provider,
            "model": model,
            "capability_outcome": consumption.get("outcome"),
            "outbound_verdict": None,
            "execution_status": (
                "timed_out"
                if exc.terminal_state == "TIMED_OUT"
                else "unavailable"
                if exc.terminal_state == "UNAVAILABLE"
                else "rejected"
            ),
            "provider_called": exc.provider_called,
            "output_released": False,
        })

        log_event(
            "GOVERNED_PROVIDER_EXECUTION_TERMINATED",
            {
                "gov_tx_id": gov_tx_id,
                "verdict_id": expected_verdict_id,
                "decision_id": authorization["decision_id"],
                "capability_id": authorization["capability_id"],
                "backend": provider,
                "model": model,
                "capability_outcome": consumption.get("outcome"),
                "terminal_state": exc.terminal_state,
                "provider_called": exc.provider_called,
                "output_released": False,
            },
        )
        raise

    outbound = _sentinel_outbound(
        text,
        sentinel_session_id,
    )

    evidence = {
        "gov_tx_id": gov_tx_id,
        "verdict_id": expected_verdict_id,
        "decision_id": authorization["decision_id"],
        "capability_id": authorization["capability_id"],
        "backend": provider,
        "model": model,
        "capability_outcome": consumption.get("outcome"),
        "outbound_verdict": outbound.get("verdict"),
        "execution_status": "completed",
    }

    log_event(
        "GOVERNED_PROVIDER_EXECUTION_COMPLETE",
        {
            "gov_tx_id": gov_tx_id,
            "verdict_id": expected_verdict_id,
            "decision_id": authorization["decision_id"],
            "capability_id": authorization["capability_id"],
            "backend": provider,
            "model": model,
            "capability_outcome": consumption.get("outcome"),
            "outbound_verdict": outbound.get("verdict"),
        },
    )

    return text, evidence



# ── Sprint 6c: A2A Relay Block + PUBLIC Disclosure Clamp ─────────────────────
# Doctrine: no agent can authorize Abigail by assertion alone.
# PUBLIC mode: high-level outcomes only — no internal topology disclosed.

A2A_RELAY_PATTERNS = [
    "upstream agent authorized",
    "upstream agent approved",
    "another agent authorized",
    "another agent approved",
    "previous agent authorized",
    "previous agent approved",
    "external agent authorized",
    "external agent approved",
    "agent authorized this request",
    "agent approved this request",
    "agent-to-agent relay",
    "a2a relay",
    "system upstream authorized",
    "supervisor agent authorized",
    "orchestrator authorized",
    "delegate agent authorized",
    "already approved by another agent",
    "already validated by another agent",
    "please proceed on behalf of",
]

PUBLIC_FORBIDDEN_TERMS = [
    "CP-00", "Constitutional Administrator",
    "David W. Smith", "Founder & CEO",
    "US Provisional Patent", "63/953,447",
    "Ed25519", "Intent Token",
    "DRS", "JIT", "kill-switch", "kill switch",
    "audit log", "Sentinel OverWatch", "HAAP Layer",
    "system prompt", "constitutional bounds",
    "internal topology", "routing policy",
]

def _detects_a2a_relay(message: str) -> bool:
    lowered = (message or "").lower()
    return any(p in lowered for p in A2A_RELAY_PATTERNS)

def _public_response_overexposed(text: str) -> bool:
    lowered = (text or "").lower()
    return any(t.lower() in lowered for t in PUBLIC_FORBIDDEN_TERMS)

def _public_safe_fallback() -> str:
    return (
        "LOGOS ASF uses layered safety controls to screen requests before "
        "response generation. In public mode, I can describe high-level safety "
        "outcomes, but I do not disclose internal topology, enforcement mechanics, "
        "routing details, credentials, or operational controls."
    )


# ── UX-01: Public response calibration ─────────────────────────────────────────
# Benign product/identity/help questions get useful, customer-facing answers.
# Adversarial and protected-disclosure input is already hard-blocked upstream by
# Sentinel/HAAP; the guard below keeps self-referential internal probes out of the
# friendly path so they fall through to the existing hard-block/disclosure clamp.
# The canned answers contain no internals, so they are safe even on misclassification.
_PUBLIC_PROTECTED_GUARD = re.compile(
    r"(?i)("
    r"\byour\b.{0,25}\b(token|secret|credential|password|api[_ -]?key|config|env(ironment)?"
    r"|route|routes|topology|system\s*prompt|internals?|enforcement|admin)\b"
    r"|\b(bypass|disable|ignore|circumvent|override|turn\s*off)\b.{0,25}"
    r"\b(sentinel|haap|govsec|governance|command\s*bus|gate|safety|guard|kill.?switch)\b"
    r"|\b(hidden|internal|admin)\b.{0,12}\b(route|routes|topology|endpoint|control|mechanic)"
    r"|\b(dump|reveal|leak|expose|print|show|list)\b.{0,25}"
    r"\b(token|secret|credential|config|env|route|routes|topology|key|prompt)\b"
    r")"
)

_PUBLIC_INTENT_PATTERNS = [
    ("identity", re.compile(
        r"(?i)\bare\s+you\s+(an?\s+)?(ai|a\s*bot|a\s*robot|human|real|conscious|sentient)\b"
        r"|\bwho\s+are\s+you\b|\bwhat\s+are\s+you\b|\bare\s+you\s+abigail\b"
        r"|\bwhat('?s|\s+is)\s+your\s+name\b")),
    ("capability", re.compile(
        r"(?i)\bwhat\s+can\s+you\s+(do|help)\b|\bwhat\s+do\s+you\s+do\b"
        r"|\bhow\s+can\s+you\s+help\b|\bwhat\s+(are|is)\s+your\s+"
        r"(capabilities|features|services|benefits)\b|\bwhat\s+services\b"
        r"|\bexplain\s+your\s+benefits\b")),
    ("build", re.compile(
        r"(?i)\b(build|create|make|design|develop|help\s+me\s+(build|create|make|design|write))\b"
        r".{0,40}\b(chat\s*bot|bot|assistant|app|application|website|site|tool|agent|plan|"
        r"document|workflow|form|page)\b")),
    ("help", re.compile(
        r"(?i)^\s*(help|hi|hello|hey|greetings)\s*[.!?]*\s*$"
        r"|\bwhat\s+is\s+abigail\b|\btell\s+me\s+about\s+abigail\b")),
]

_PUBLIC_ANSWERS = {
    "capability": (
        "I can help answer questions, draft plans and documents, review risks, prepare "
        "workflows, and guide work through approval, audit, and cost controls. I can help "
        "with ordinary tasks while stopping when a request becomes risky or requires permission."
    ),
    "identity": (
        "Yes — I am Abigail, a governed AI assistant for LOGOS ASF. I am designed to help "
        "with useful work while applying safety, cost, approval, and audit controls, and I "
        "stop when a request needs human approval."
    ),
    "build": (
        "I can help you design one. To scope it well, tell me: who it serves (for example "
        "customer support, internal assistant, sales intake, community support, or technical "
        "helpdesk), what it should answer, what data it may use, what actions it may take, and "
        "what approval or safety limits it needs."
    ),
    "help": (
        "I am Abigail, a governed AI assistant for LOGOS ASF. I can help you plan, draft, "
        "review, classify, and route work — answering questions and preparing documents while "
        "applying approval, audit, and cost controls. What would you like help with?"
    ),
}


def classify_public_intent(message):
    """UX-01: classify a benign public question. Returns an intent label
    ('capability'|'identity'|'build'|'help') or None. Returns None for anything that
    references internal controls/secrets/bypasses so those keep the governed pipeline."""
    m = (message or "").strip()
    if not m or _PUBLIC_PROTECTED_GUARD.search(m):
        return None
    for label, pat in _PUBLIC_INTENT_PATTERNS:
        if pat.search(m):
            return label
    return None


def public_intent_answer(message, session):
    """UX-01: return a governed, customer-facing answer for a benign public question,
    or None to fall through to the normal governed pipeline. No internals, no inference."""
    label = classify_public_intent(message)
    if not label:
        return None
    log_event("PUBLIC_INTENT_ANSWER", {"intent": label})
    return {
        "ok": True,
        "text": _PUBLIC_ANSWERS[label],
        "drs": 0,
        "mode": "PUBLIC_ASSIST",
        "crsv": session.crsv(),
        "governance": {
            "execution_path": "deterministic_public_assist",
            "provider_execution_required": False,
            "execution_status": "completed",
            "capability_outcome": "NOT_REQUIRED",
            "outbound_verdict": "NOT_REQUIRED",
        },
    }

# ── ASF Department Registry ───────────────────────────────────────────────────
# Gate 1 (GovMem convergence): single source of truth is departments/registry.json.
# VALID_DEPTS and ASF_DEPARTMENTS both derive from it — no hardcoded department
# enumeration survives here. See FINDINGS.md: DEPARTMENT_LIST_DIVERGENCE.
def _department_registry_path():
    # In the container image (abigail/Dockerfile) this file is copied flat to
    # /app/abigail_hardened_enhanced.py, not repo_root/abigail/, so the local-dev
    # derivation below (two parents up) would resolve wrong there. The Dockerfile
    # sets ABIGAIL_DEPT_REGISTRY_PATH explicitly to override it.
    override = os.environ.get("ABIGAIL_DEPT_REGISTRY_PATH")
    if override:
        return Path(override)
    return Path(__file__).parent.parent / "departments" / "registry.json"

def _load_department_registry():
    return json.loads(_department_registry_path().read_text())

def _active_departments():
    return [d for d in _load_department_registry()["departments"] if d["status"] == "active"]

# Agency levels are not yet tracked in departments/registry.json (see FINDINGS.md).
# Values below are carried over from the pre-Gate-1 ASF_DEPARTMENTS literal for
# departments that already had one. EXE and SC had no prior value; their
# agency_level of 1 is confirmed per OD-6 (EXE) and OD-7 (SC).
_AGENCY_LEVELS = {
    "EXE": 1,   # OD-6
    "SC":  1,   # OD-7
    "SEC": 2,
    "QA":  2,
    "OPS": 3,
    "GRC": 2,
    "REV": 2,
    "FIN": 2,
    "LGL": 1,
    "PRD": 2,
    "MKT": 2,
    "DAT": 2,
    "ENG": 3,
    "RI":  2,   # carried over from the old "DEPT-RES" entry
}

ASF_DEPARTMENTS = [
    {"id": d["code"], "name": d["name"], "agency_level": _AGENCY_LEVELS.get(d["code"], 2)}
    for d in _active_departments()
]

VALID_DEPTS = frozenset(d["code"] for d in _active_departments())

def _resolve_dept_for_spine(raw_dept_id):
    """Resolve and validate department identity for Sentinel propagation (Gate 2, F-GM-005).

    Returns the validated code, or None if raw_dept_id is absent/invalid.
    Unknown department: fail closed — the caller must reject the request,
    never silently default to any fallback.
    """
    if not raw_dept_id:
        return None
    code = str(raw_dept_id).strip().upper()
    return code if code in VALID_DEPTS else None


# ── Web HTML ──────────────────────────────────────────────────────────────────
WEB_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://*.app.github.dev https://*.preview.app.github.dev http://localhost:7070 http://localhost:9090 http://127.0.0.1:7070;">
<title>Abigail — LOGOS CP-00</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d0f14;--surface:#161a23;--border:#252b38;--accent:#3b82f6;--warn:#f59e0b;--danger:#ef4444;--ok:#22c55e;--text:#e2e8f0;--muted:#64748b}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;font-size:14px}
body{display:flex;flex-direction:column;align-items:center;padding:12px;gap:10px}
header{width:100%;max-width:820px;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 16px;display:flex;align-items:center;gap:12px}
.logo{font-size:16px;font-weight:700;color:var(--accent)}.sub{font-size:11px;color:var(--muted);margin-top:2px}
.pills{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
.pill{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--border);background:var(--bg);color:var(--muted)}
.pill.green{border-color:var(--ok);color:var(--ok)}.pill.red{border-color:var(--danger);color:var(--danger)}.pill.yellow{border-color:var(--warn);color:var(--warn)}
#chat{width:100%;max-width:820px;flex:1;overflow-y:auto;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:10px;min-height:260px;max-height:calc(100vh - 220px)}
.msg{display:flex;flex-direction:column;gap:3px;max-width:88%}
.msg.user{align-self:flex-end;align-items:flex-end}.msg.agent{align-self:flex-start;align-items:flex-start}.msg.sys{align-self:center;align-items:center;max-width:100%}
.bubble{padding:9px 13px;border-radius:8px;line-height:1.55;white-space:pre-wrap;word-break:break-word}
.msg.user .bubble{background:var(--accent);color:#fff}
.msg.agent .bubble{background:var(--bg);border:1px solid var(--border)}
.msg.sys .bubble{background:transparent;border:1px solid var(--border);color:var(--muted);font-size:11px;font-family:monospace}
.msg.blocked .bubble{border-color:var(--danger)!important;color:var(--danger)}
.meta{font-size:11px;color:var(--muted);padding:0 3px}.drift{font-size:11px;color:var(--warn);padding:0 3px}
#composer{width:100%;max-width:820px;display:flex;gap:8px}
#input{flex:1;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);font:inherit;font-size:14px;padding:10px 14px;resize:none;outline:none;min-height:44px;max-height:130px;line-height:1.5;transition:border-color .15s}
#input:focus{border-color:var(--accent)}
#send{background:var(--accent);color:#fff;border:none;border-radius:8px;padding:0 18px;font:inherit;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap;transition:opacity .15s}
#send:disabled{opacity:.4;cursor:default}
#statusbar{width:100%;max-width:820px;font-size:11px;color:var(--muted);text-align:right}
</style></head>
<body>
<header>
  <div><div class="logo">Abigail — CP-00</div><div class="sub">LOGOS Constitutional Administrator · HAAP · Sprint 6 Docker+venv Sandbox</div></div>
  <div class="pills">
    <span class="pill green" id="p-ks">Kill-switch: ARMED</span>
    <span class="pill" id="p-be">Backend: —</span>
    <span class="pill" id="p-cv">CRSV: 0.0</span>
    <span class="pill" id="p-sentinel">Sentinel: —</span>
  </div>
</header>
<div id="chat"><div class="msg sys"><div class="bubble">HAAP Five-Layer Active · Sprint 6 · Docker+venv Constitutional Sandbox · Type to engage Abigail</div></div></div>
<div id="composer"><textarea id="input" rows="1" placeholder="Message Abigail…" autofocus></textarea><button id="send">Send</button></div>
<div id="statusbar">Ready</div>
<script>
const chat=document.getElementById("chat"),inp=document.getElementById("input"),btn=document.getElementById("send"),
      pKS=document.getElementById("p-ks"),pBE=document.getElementById("p-be"),
      pCV=document.getElementById("p-cv"),pSent=document.getElementById("p-sentinel"),
      sb=document.getElementById("statusbar");
let busy=false;
inp.addEventListener("input",()=>{inp.style.height="auto";inp.style.height=Math.min(inp.scrollHeight,130)+"px"});
inp.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send()}});
btn.addEventListener("click",send);
function scroll(){chat.scrollTop=chat.scrollHeight}
function addMsg(role,text,meta,drift){
  const w=document.createElement("div");w.className="msg "+role;
  const b=document.createElement("div");b.className="bubble";b.textContent=text;w.appendChild(b);
  if(drift){const d=document.createElement("div");d.className="drift";d.textContent=drift;w.appendChild(d)}
  if(meta){const m=document.createElement("div");m.className="meta";m.textContent=meta;w.appendChild(m)}
  chat.appendChild(w);scroll();}
function addTyping(){const d=document.createElement("div");d.id="typing";d.style.cssText="color:var(--muted);font-style:italic;font-size:13px;padding:4px 0";d.textContent="Abigail is thinking…";chat.appendChild(d);scroll();}
function rmTyping(){const d=document.getElementById("typing");if(d)d.remove();}
async function fetchStatus(){
  try{const d=await(await fetch("/api/status")).json();pBE.textContent="Backend: "+d.backend;pCV.textContent="CRSV: "+d.crsv.toFixed(1);
    if(d.kill_switch){pKS.textContent="Kill-switch: ACTIVE";pKS.className="pill red"}else{pKS.textContent="Kill-switch: ARMED";pKS.className="pill green"}}catch(e){}
  try{const s=await(await fetch("/api/sentinel-health")).json();
    if(s.ok){pSent.textContent="Sentinel: UP";pSent.className="pill green"}else{pSent.textContent="Sentinel: DOWN";pSent.className="pill red"}}
  catch(e){pSent.textContent="Sentinel: —";pSent.className="pill"}}
async function send(){
  const text=inp.value.trim();if(!text||busy)return;
  busy=true;btn.disabled=true;inp.value="";inp.style.height="auto";
  addMsg("user",text);addTyping();sb.textContent="Sending…";
  try{const d=await(await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:text})})).json();
    rmTyping();
    if(d.ok){addMsg("agent",d.text,"DRS "+d.drs+"/100 · "+d.mode+" · CRSV "+d.crsv,d.drift||null);sb.textContent="Turn complete — DRS "+d.drs+"/100 · "+d.mode;}
    else{addMsg("agent blocked",d.text);sb.textContent="Blocked by HAAP";}
    fetchStatus();}
  catch(e){rmTyping();addMsg("agent blocked","[Network error — server not responding]");sb.textContent="Error";}
  busy=false;btn.disabled=false;inp.focus();}
fetchStatus();setInterval(fetchStatus,15000);
</script></body></html>"""


# ── Web server ────────────────────────────────────────────────────────────────
def build_web_app(session, kill_switch, active_backend):
    """SEC-02: construct and return the Flask app (routes wired) without starting the
    server. Exposed separately so tests can exercise routes via a test client; run_web()
    handles bind-host resolution, the banner, and flask_app.run()."""
    try:
        from flask import Flask, Response, jsonify, request, send_from_directory, abort
        from werkzeug.utils import safe_join
    except ImportError:
        print("\033[31m[ERROR] Flask required: pip install flask\033[0m"); sys.exit(1)

    try:
        from flask_cors import CORS as _CORS; _has_cors=True
    except ImportError:
        _has_cors=False
        print("[WARN] flask-cors not installed. pip install flask-cors")

    flask_app=Flask(__name__)
    flask_app.config["MAX_CONTENT_LENGTH"] = resolve_max_request_bytes()  # C6: request body size boundary
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    def _request_authority():
        """Resolve caller authority via the centralized C4 validator. Missing
        OR invalid/placeholder configured tokens never grant access."""
        auth = request.headers.get("Authorization", "").strip()
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else auth
        token = token or request.headers.get("X-HAAP-Token", "").strip()

        admin_configured = privileged_credentials.resolve_configured_token("ABIGAIL_ADMIN_TOKEN")
        demo_configured = privileged_credentials.resolve_configured_token("ABIGAIL_DEMO_TOKEN")

        if admin_configured is None or demo_configured is None:
            return "MISCONFIGURED"
        if privileged_credentials.credential_matches(token, "ABIGAIL_ADMIN_TOKEN"):
            return "ADMIN"
        if privileged_credentials.credential_matches(token, "ABIGAIL_DEMO_TOKEN"):
            return "DEMO"
        return "UNAUTHENTICATED"

    def _authorized(*allowed_roles):
        return _request_authority() in allowed_roles

    if _has_cors:
        _CORS(flask_app, resources={r"/api/*":{
            "origins":["https://logosGSInc.github.io","https://LogosGSInc.github.io",
                       "http://localhost:7070","http://127.0.0.1:7070",
                       re.compile(r"https://.*\.app\.github\.dev"),
                       re.compile(r"https://.*\.preview\.app\.github\.dev")],
            "methods":["GET","POST","OPTIONS"],
            "allow_headers":["Content-Type","Authorization","X-HAAP-Token","X-Intent-ID","X-Actor-ID"]}})

    @flask_app.after_request
    def _cors_fallback(response):
        if not _has_cors:
            origin=request.headers.get("Origin","")
            if any(re.match(p,origin) for p in [
                r"https://.*\.app\.github\.dev",r"https://.*\.preview\.app\.github\.dev",
                r"https://[Ll]ogos[Gg][Ss][Ii]nc\.github\.io",
                r"http://localhost:\d+",r"http://127\.0\.0\.1:\d+"]):
                response.headers["Access-Control-Allow-Origin"]=origin
                response.headers["Access-Control-Allow-Headers"]="Content-Type,Authorization,X-HAAP-Token"
                response.headers["Access-Control-Allow-Methods"]="GET,POST,OPTIONS"
        return response

    import os as _os
    STATIC_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "static")
    if not _os.path.isdir(STATIC_DIR):
        STATIC_DIR = "/app/static"  # Docker path

    # P0-3: per-session state. The chat path resolves an isolated SessionState per key
    # (X-Session-ID header, else body session_id, else remote_addr) instead of the single
    # shared object. The passed-in `session` is seeded as the "default" (used by the CLI
    # and the operator/admin agent routes). Exposed on the app for verification.
    sessions = SessionRegistry(default=session)
    flask_app._session_registry = sessions

    def _resolve_chat_session(explicit_key=None):
        # TODO(Q-03): absent X-Session-ID currently falls back to remote_addr,
        # which collapses NAT-shared users onto one session. Operator decision
        # pending: fail closed vs. server-side mint.
        key = (explicit_key
               or request.headers.get("X-Session-ID", "").strip()
               or (request.remote_addr or "default"))
        return sessions.get_or_create(key), key

    def _valid_step_up(req):
        """P0-2 / C4: a valid step-up authorization is a presented token
        matching the configured admin or demo token, both resolved through
        the centralized C4 validator. Fail-closed: no valid configured
        token => no step-up."""
        presented = (req.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                     or req.headers.get("X-HAAP-Token", "").strip())
        if not presented:
            return False
        for name in ("ABIGAIL_ADMIN_TOKEN", "ABIGAIL_DEMO_TOKEN"):
            if privileged_credentials.credential_matches(presented, name):
                return True
        return False

    @flask_app.route("/")
    def index():
        # Abigail Command Center is the primary governed workspace.
        p = _os.path.join(STATIC_DIR, "abigail.html")
        if _os.path.exists(p):
            return Response(open(p).read(), mimetype="text/html")
        # Fallback if static dir not mounted
        return Response("""<!doctype html><html><body style='background:#0b1020;color:#eef2ff;font-family:system-ui;display:grid;place-items:center;min-height:100vh;margin:0'>
<main style='text-align:center'><h1>LOGOS ASF</h1>
<p style='color:#aeb7d8'>Static files not found. Run via docker-compose.</p>
<p><a href='/api/status' style='color:#4f98a3'>Check /api/status</a></p></main></body></html>""", mimetype="text/html")

    @flask_app.route("/<path:filename>")
    def static_files(filename):
        full = safe_join(STATIC_DIR, filename)
        if full is None:
            abort(404)
        return send_from_directory(STATIC_DIR, filename)

    @flask_app.route("/api/status")
    def api_status():
        return jsonify({"backend":active_backend[0],"crsv":session.crsv(),
                        "turns":session.turn_count,"kill_switch":kill_switch.is_active,
                        "version":VERSION,"sandbox":"docker+venv"})

    @flask_app.route("/api/chat",methods=["POST","OPTIONS"])
    def api_chat():
        if request.method=="OPTIONS": return jsonify({}),200
        _body = request.get_json(silent=True) or {}
        msg = (_body.get("message") or "").strip()
        if not msg: return jsonify({"ok":False,"text":"Empty message.","drs":0,"mode":"NONE","crsv":0.0})
        # P0-3: resolve the isolated per-client session before any state is touched.
        _sess, _skey = _resolve_chat_session(_body.get("session_id"))
        # P0-2: is a valid step-up authorization present (used only if Sentinel RESTRICTs)?
        _step_up_ok = _valid_step_up(request)
        # Gate 2 (F-GM-005): per-request department identity for Sentinel, not a
        # process-fixed env var. Absent is allowed (no department attribution,
        # same as every request before this gate); present-but-unknown is not —
        # fail closed rather than silently drop or default it.
        _raw_dept = _body.get("department_id")
        if _raw_dept:
            _dept_id = _resolve_dept_for_spine(_raw_dept)
            if _dept_id is None:
                return jsonify({"ok": False,
                                "text": f"Unknown department: {_raw_dept!r}",
                                "drs": 0, "mode": "DEPT_REJECTED", "crsv": _sess.crsv()}), 400
        else:
            _dept_id = None
        _agent_id = (_body.get("agent_id") or "").strip() or None
        # Governed command bus — classify before LLM inference (CB-01)
        if _COMMAND_BUS_OK:
            _auth = (request.headers.get("Authorization","") or
                     request.headers.get("X-HAAP-Token",""))
            _status = {"backend":active_backend[0],"crsv":_sess.crsv(),
                       "turns":_sess.turn_count,"kill_switch":kill_switch.is_active,
                       "version":VERSION,"sandbox":"docker+venv"}
            _cmd = _try_operator_command_fn(
                msg, request.remote_addr, _auth,
                haap_gate, log_event, _status, _sess)
            if _cmd is not None:
                return jsonify(_cmd)
        # SEC-02: Cost Governor — deterministic local spend gate BEFORE paid inference (L7-1)
        _cost_ok, _cost_meta = check_chat_cost_budget(msg, "chat", _sess)
        if not _cost_ok:
            log_event("COST_GATE_BLOCK", {"decision": _cost_meta.get("decision"),
                                          "turns": _cost_meta.get("turns_used")})
            return jsonify({"ok": False,
                            "text": "Request blocked by Cost Governor — local spend ceiling reached.",
                            "drs": 0, "mode": "COST_BLOCKED", "crsv": _sess.crsv(),
                            "cost": _cost_meta})
        # MM-02: Shadow orchestration context — audit-safe, additive, fail-soft (CB-02)
        _orch_ctx = None
        _approval_meta = None
        if _ORCHESTRATION_BRIDGE_OK:
            _req_meta = {k: v for k, v in _body.items() if k != "message"}
            _orch_ctx = _build_shadow_ctx(msg, "chat", _sess, active_backend, _req_meta)
            if _orch_ctx is not None:
                _approval_meta = _orch_ctx.response_metadata  # MM-03: enforced downstream
        result = process_message(msg, _sess, kill_switch, active_backend,
                                 approval_meta=_approval_meta, step_up_ok=_step_up_ok,
                                 department_id=_dept_id, agent_id=_agent_id)
        if _orch_ctx is not None:
            result["orchestration"] = _orch_ctx.response_metadata
        result.setdefault("cost", _cost_meta)
        return jsonify(result)

    @flask_app.route("/api/sentinel-health")
    def api_sentinel_health():
        r=_sentinel_health()
        return jsonify(r), 200 if r["ok"] else 503

    @flask_app.route("/api/agents/departments")
    def api_departments():
        return jsonify({"departments":ASF_DEPARTMENTS,"count":len(ASF_DEPARTMENTS),"governed_by":"abigail.cp00"})

    @flask_app.route("/api/agents")
    def api_agents_list():
        agents = _list_yaml_agents()
        return jsonify({"agents":agents,"count":len(agents),
                        "loader_ok":_AGENT_LOADER_OK,"governed_by":"abigail.cp00"})

    @flask_app.route("/api/control-plane/workers")
    def api_control_plane_workers():
        """Read-only, admin-authenticated view of the curated Control Plane Registry.
        Describes governed workers to Operations — it never dispatches. Dispatch stays
        exclusively with the broker. Fail-closed: no admin token, no listing."""
        _ok, _st, _err = require_admin_token(request)
        if not _ok:
            log_event("CONTROL_PLANE_AUTH_REJECTED", {"ip": request.remote_addr, "status": _st})
            return jsonify({"error": _err}), _st
        if not _CONTROL_PLANE_OK:
            return jsonify({"error": "Control plane registry unavailable."}), 503
        token = (request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                 or request.headers.get("X-HAAP-Token", "").strip())
        try:
            reader = _build_control_plane_registry().authenticate(token)
        except _ControlPlaneAuthError:
            return jsonify({"error": "Control plane access denied."}), 401
        return jsonify(reader.snapshot())

    @flask_app.route("/api/swarm/dispatch", methods=["POST","OPTIONS"])
    def api_swarm_dispatch():
        """P0-5: one real end-to-end governed swarm dispatch path.

        Runs the full governed chain — RoutingManifest → SEC-02 cost gate → MM-03 approval
        gate → Ed25519-SIGNED SignedHandoffPacket → signature-VERIFIED worker (a real
        governed LLM call, not a template) → supervisor merge → audit — under ONE
        job-level gov_tx_id threaded into every step. Admin-gated and fail-closed, like
        the other dispatch surfaces. Demo-safe: active_dryrun, no writes, no outbound."""
        if request.method == "OPTIONS": return jsonify({}), 200
        _ok,_st,_err = require_admin_token(request)
        if not _ok:
            log_event("SWARM_DISPATCH_AUTH_REJECTED", {"ip":request.remote_addr,"status":_st})
            return jsonify({"error":_err}), _st
        if not _SWARM_OK:
            return jsonify({"ok":False,"error":"Governed swarm unavailable."}), 503
        body = request.get_json(force=True, silent=True) or {}
        task = (body.get("task") or "").strip()
        _depts_in = body.get("departments")
        if not isinstance(_depts_in, list) or not _depts_in:
            _depts_in = [body.get("department") or "ENG"]
        depts = [str(d).strip().upper() for d in _depts_in if str(d).strip()]
        risk_level = (body.get("risk_level") or "low").strip().lower()
        if not task:
            return jsonify({"ok":False,"error":"task required."}), 400
        if not depts:
            return jsonify({"ok":False,"error":"at least one department required."}), 400

        # Reuse the existing HAAP/DRS gate — do not duplicate gate logic (fail-closed).
        try:
            haap_gate(task, agent_drs_ceiling=60)
        except HAAPViolation as e:
            log_event("SWARM_DISPATCH_BLOCKED", {"dept":dept,"reason":str(e)[:200]})
            return jsonify({"ok":False,"error":str(e),"blocked":True}), 403

        # Governed LLM worker: bounded, packet-scoped. Injected into the executor so the
        # swarm returns actual work product instead of a deterministic template.
        def _governed_llm_worker(_dept, _task, _packet):
            _system = (f"You are the {_dept} department worker in Abigail's governed local "
                       f"swarm (AG-01). Produce a bounded, demo-only draft for the task. "
                       f"No external actions, no outbound contact, no spend. "
                       f"Scope: {_packet.authority_scope}.")
            return BACKEND_DISPATCH.get(active_backend[0], call_groq)(
                messages=[{"role":"user","content":_task}], system=_system)

        job_id = f"SWARM-{uuid.uuid4().hex[:8].upper()}"
        try:
            job = _JobSpec(
                job_id=job_id,
                title=f"Governed dispatch: {', '.join(depts)}",
                description="Bounded demo-only governed swarm dispatch (dry-run, no writes).",
                approved_workspace=f"runtime/jobs/{job_id}",
                departments=list(depts),
                department_tasks={d: task for d in depts},
                expected_artifacts={d: f"{d.lower()}_draft.md" for d in depts},
                mode="active_dryrun",
            )
        except ValueError as e:
            return jsonify({"ok":False,"error":f"invalid job: {e}"}), 400

        registry = _SwarmRegistry()
        containment = _ContainmentController(_ContainmentMode.RUNNING)
        for _d in depts:
            _wid, _ = registry.resolve_department_worker(_d)
            registry.activate(_wid, _ActivationState.ACTIVE_DRYRUN)
        executor = _LocalExecutor(registry, containment, workspace=job.approved_workspace,
                                  draft_fn=_governed_llm_worker)
        try:
            results = executor.run_job(job, risk_level=risk_level)
            merge = _supervisor_merge(job, results, executor)
        except Exception as exc:
            log_event("SWARM_DISPATCH_ERROR", {"job_id":job_id,"error_type":type(exc).__name__})
            return jsonify({"ok":False,"error":_safe_error("swarm", exc)}), 502

        gov_tx_ids = {r.gov_tx_id for r in results if r.gov_tx_id}
        single_gov_tx_id = next(iter(gov_tx_ids), "") if len(gov_tx_ids) == 1 else ""
        log_event("SWARM_DISPATCH_COMPLETE",
                  {"job_id":job_id,"gov_tx_id":single_gov_tx_id,
                   "single_gov_tx_id":len(gov_tx_ids) == 1,
                   "decision":merge.decision,"departments":[r.department for r in results]})
        return jsonify({
            "ok": True,
            "job_id": job_id,
            "gov_tx_id": single_gov_tx_id,
            "single_gov_tx_id": len(gov_tx_ids) == 1,
            "supervisor_decision": merge.decision,
            "governed": True,
            "results": [{
                "department": r.department,
                "worker_id": r.worker_id,
                "backed_by_authored_agent": r.backed_by_authored_agent,
                "manifest_id": r.manifest_id,
                "packet_id": r.packet_id,
                "gov_tx_id": r.gov_tx_id,
                "status": r.status,
                # status == "complete" is only reachable after execute_worker's
                # require_valid_packet() Ed25519 check passed (P0-4).
                "packet_verified": r.status == "complete",
                "content": r.content,
            } for r in results],
        })

    @flask_app.route("/api/agents/dispatch", methods=["POST","OPTIONS"])
    def api_agents_dispatch():
        if request.method == "OPTIONS": return jsonify({}), 200
        _ok, _st, _err = require_admin_token(request)
        if not _ok:
            log_event("DISPATCH_AUTH_REJECTED", {
                "ip": request.remote_addr,
                "status": _st,
            })
            return jsonify({"error": _err}), _st

        body       = request.get_json(force=True, silent=True) or {}
        agent_id   = (body.get("agent_id") or "").strip()
        task       = (body.get("task")     or "").strip()
        if not agent_id: return jsonify({"ok":False,"error":"agent_id required."}), 400
        if not task:     return jsonify({"ok":False,"error":"task required."}), 400

        agent_def = _get_yaml_agent(agent_id)
        if not agent_def:
            return jsonify({"ok":False,"error":f"Agent '{agent_id}' not found."}), 404

        # A1: dispatch inherits the caller's conversation session rather than
        # minting its own — same resolution _api_chat_ uses (X-Session-ID
        # header, then body session_id, then remote_addr), so a dispatch call
        # from an active conversation shares that conversation's durable
        # Sentinel session_id, and a standalone dispatch call still gets a
        # coherent, durable session of its own.
        _dispatch_sess, _dispatch_skey = _resolve_chat_session(body.get("session_id"))
        if not _ensure_session_started(_dispatch_sess):
            return jsonify({
                "ok": False,
                "blocked": True,
                "terminal_state": "UNAVAILABLE",
                "error": "Sentinel OverWatch could not start this governance session.",
                "mode": "SENTINEL_FAIL_CLOSED",
                "governance": {
                    "execution_status": "unavailable",
                    "sentinel_verdict": "SESSION_START_FAILED",
                    "provider_called": False,
                    "output_released": False,
                },
            }), 503
        sentinel_session_id = _dispatch_sess.sentinel_session_id

        # Authoritative Sentinel Corridor-In gate.
        s_result = _sentinel_inspect(task, sentinel_session_id)
        s_verdict = str(s_result.get("verdict", "UNKNOWN")).strip().upper()

        if s_verdict not in ("APPROVED", "RESTRICTED"):
            log_event("DISPATCH_SENTINEL_FAIL_CLOSED", {
                "agent_id": agent_id,
                "verdict": s_verdict,
                "session_id": sentinel_session_id,
                "sentinel_ok": bool(s_result.get("ok", False)),
                "error": str(s_result.get("error", ""))[:200],
                "action": "HARD_STOP",
            })
            sentinel_unavailable = s_verdict in (
                "SENTINEL_OFFLINE",
                "SENTINEL_AUTH_MISSING",
                "SENTINEL_REJECTED",
                "UNKNOWN",
            )

            terminal_state = (
                "UNAVAILABLE"
                if sentinel_unavailable
                else "BLOCKED"
            )

            return jsonify({
                "ok": False,
                "blocked": True,
                "terminal_state": terminal_state,
                "error": (
                    "Sentinel OverWatch did not grant execution authority. "
                    f"Verdict: {s_verdict}."
                ),
                "mode": "SENTINEL_FAIL_CLOSED",
                "governance": {
                    "execution_status": (
                        "unavailable"
                        if sentinel_unavailable
                        else "rejected"
                    ),
                    "sentinel_verdict": s_verdict,
                    "provider_called": False,
                    "output_released": False,
                },
            }), 503 if sentinel_unavailable else 403

        log_event("DISPATCH_SENTINEL_APPROVED", {
            "agent_id": agent_id,
            "verdict": s_verdict,
            "session_id": sentinel_session_id,
            "action": "PROCEED_TO_HAAP",
        })

        # Preserve hard constitutional/adversarial blocks before considering
        # whether a request is merely high-risk and eligible for human approval.
        constitutional_match = constitutional_check(task)
        sentinel_match = sentinel_check(task)

        if constitutional_match or sentinel_match:
            try:
                haap_gate(task, agent_drs_ceiling=80)
            except HAAPViolation as exc:
                log_event(
                    "DISPATCH_BLOCKED",
                    {
                        "agent_id": agent_id,
                        "reason": str(exc)[:200],
                        "terminal_state": "BLOCKED",
                    },
                )
                return jsonify({
                    "ok": False,
                    "blocked": True,
                    "terminal_state": "BLOCKED",
                    "mode": "GOVERNED_EXECUTION_REJECTED",
                    "error": str(exc),
                    "governance": {
                        "execution_status": "rejected",
                        "provider_called": False,
                        "output_released": False,
                    },
                }), 403

        score, signals = drs_score(task)
        mode, _, action = drs_verdict(score)

        if action in ("HARD_STOP", "TERMINAL_STOP"):
            approval_evidence_id = f"APR-{uuid.uuid4().hex}"
            sentinel_gov_tx_id = s_result.get("gov_tx_id")
            sentinel_verdict_id = s_result.get("verdict_id")

            approval_evidence = {
                "approval_evidence_id": approval_evidence_id,
                "agent_id": agent_id,
                "drs": score,
                "mode": mode,
                "signals": signals,
                "sentinel_verdict": s_verdict,
                "sentinel_session_id": sentinel_session_id,
                "gov_tx_id": sentinel_gov_tx_id,
                "verdict_id": sentinel_verdict_id,
                "provider_called": False,
                "capability_issued": False,
                "capability_consumed": False,
                "output_released": False,
            }

            log_event(
                "DISPATCH_APPROVAL_REQUIRED",
                approval_evidence,
            )

            return jsonify({
                "ok": False,
                "blocked": True,
                "terminal_state": "APPROVAL_REQUIRED",
                "mode": "APPROVAL_REQUIRED",
                "error": (
                    "Human approval is required before this governed dispatch "
                    "may proceed."
                ),
                "approval": {
                    "human_approval_required": True,
                    "enforced": True,
                    "approval_evidence_id": approval_evidence_id,
                    "risk_score": score,
                    "risk_mode": mode,
                    "reason": signals or ["jit_authorization_required"],
                },
                "governance": {
                    "execution_status": "approval_required",
                    "sentinel_verdict": s_verdict,
                    "sentinel_session_id": sentinel_session_id,
                    "gov_tx_id": sentinel_gov_tx_id,
                    "verdict_id": sentinel_verdict_id,
                    "provider_called": False,
                    "capability_issued": False,
                    "capability_consumed": False,
                    "output_released": False,
                },
            }), 409

        try:
            haap_gate(task, agent_drs_ceiling=80)
        except HAAPViolation as exc:
            log_event(
                "DISPATCH_BLOCKED",
                {
                    "agent_id": agent_id,
                    "reason": str(exc)[:200],
                    "terminal_state": "BLOCKED",
                },
            )
            return jsonify({
                "ok": False,
                "blocked": True,
                "terminal_state": "BLOCKED",
                "mode": "GOVERNED_EXECUTION_REJECTED",
                "error": str(exc),
                "governance": {
                    "execution_status": "rejected",
                    "provider_called": False,
                    "output_released": False,
                },
            }), 403
        system_prompt  = agent_def.get("system_prompt") or ABIGAIL_SYSTEM_PROMPT
        agent_name     = agent_def.get("name", agent_id)

        # Capability-bound provider execution requires authoritative transaction
        # and verdict identifiers from the inbound Sentinel decision.
        gov_tx_id = str(s_result.get("gov_tx_id") or "").strip()
        verdict_id = str(s_result.get("verdict_id") or "").strip()

        if not gov_tx_id or not verdict_id:
            log_event("DISPATCH_AUTHORITY_EVIDENCE_MISSING", {
                "agent_id": agent_id,
                "session_id": sentinel_session_id,
                "has_gov_tx_id": bool(gov_tx_id),
                "has_verdict_id": bool(verdict_id),
                "action": "HARD_STOP",
            })
            return jsonify({
                "ok": False,
                "blocked": True,
                "mode": "AUTHORITY_EVIDENCE_MISSING",
                "error": (
                    "Sentinel approved the request without complete execution "
                    "authority evidence."
                ),
            }), 503

        provider = active_backend[0]
        messages = [{"role": "user", "content": task}]

        t = time.monotonic()
        try:
            text, governance = _governed_provider_execute(
                provider=provider,
                messages=messages,
                system=system_prompt,
                sentinel_session_id=sentinel_session_id,
                gov_tx_id=gov_tx_id,
                expected_verdict_id=verdict_id,
            )
        except GovernedProviderError as exc:
            terminal_state = getattr(
                exc,
                "terminal_state",
                "BLOCKED",
            ).upper()

            governance = dict(
                getattr(exc, "governance", {}) or {}
            )

            governance.setdefault("execution_status", "rejected")
            governance.setdefault("gov_tx_id", gov_tx_id)
            governance.setdefault("verdict_id", verdict_id)
            governance.setdefault("backend", provider)
            governance.setdefault("output_released", False)

            # Compatibility and fail-closed semantics:
            # any GovernedProviderError prevents execution/output release.
            # terminal_state communicates the precise operator-facing reason.
            blocked = True

            http_status = {
                "BLOCKED": 403,
                "APPROVAL_REQUIRED": 409,
                "UNAVAILABLE": 502,
                "TIMED_OUT": 504,
            }.get(terminal_state, 502)

            log_event(
                "DISPATCH_GOVERNED_EXECUTION_REJECTED",
                {
                    "agent_id": agent_id,
                    "backend": provider,
                    "gov_tx_id": gov_tx_id,
                    "verdict_id": verdict_id,
                    "error_type": type(exc).__name__,
                    "terminal_state": terminal_state,
                    "capability_consumed": bool(
                        getattr(exc, "capability_consumed", False)
                    ),
                    "provider_called": bool(
                        getattr(exc, "provider_called", False)
                    ),
                    "action": "NO_OUTPUT_RELEASED",
                },
            )

            return jsonify({
                "ok": False,
                "blocked": blocked,
                "terminal_state": terminal_state,
                "mode": "GOVERNED_EXECUTION_REJECTED",
                "error": str(exc),
                "governance": governance,
            }), http_status
        except Exception as exc:
            log_event("DISPATCH_ERROR", {
                "agent_id": agent_id,
                "backend": provider,
                "gov_tx_id": gov_tx_id,
                "verdict_id": verdict_id,
                "error_type": type(exc).__name__,
                "action": "NO_OUTPUT_RELEASED",
            })
            return jsonify({
                "ok": False,
                "blocked": True,
                "mode": "DISPATCH_ERROR",
                "error": _safe_error(agent_id, exc),
            }), 502

        elapsed = round(time.monotonic() - t, 2)
        session.record_turn(task, score, signals)

        log_event("DISPATCH_COMPLETE", {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "backend": governance.get("backend"),
            "model": governance.get("model"),
            "gov_tx_id": governance.get("gov_tx_id"),
            "verdict_id": governance.get("verdict_id"),
            "decision_id": governance.get("decision_id"),
            "capability_id": governance.get("capability_id"),
            "capability_outcome": governance.get("capability_outcome"),
            "outbound_verdict": governance.get("outbound_verdict"),
            "drs": score,
            "mode": mode,
            "elapsed": elapsed,
            "crsv": round(session.crsv(), 1),
        })

        return jsonify({
            "ok": True,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "text": text,
            "drs": score,
            "mode": mode,
            "crsv": round(session.crsv(), 1),
            "governance": governance,
        })

    @flask_app.route("/api/agents/spawn",methods=["POST","OPTIONS"])
    def api_agents_spawn():
        if request.method=="OPTIONS": return jsonify({}),200
        _ok,_st,_err = require_admin_token(request)
        if not _ok:
            log_event("SPAWN_AUTH_REJECTED",{"ip":request.remote_addr,"status":_st})
            return jsonify({"error":_err}),_st
        body=request.get_json(force=True,silent=True) or {}
        dept_id=body.get("dept_id","DEPT-UNKNOWN")
        task=body.get("task","").strip()
        if is_dept_killed(dept_id):
            log_event("SPAWN_BLOCKED_DEPT_KILLED",{"dept":dept_id})
            return jsonify({
                "error":f"Department {dept_id} is isolated/killed.",
                "blocked":True,
                "reason":"DEPARTMENT_ISOLATED"
            }),423
        if not task: return jsonify({"error":"task required."}),400
        try: haap_gate(task,agent_drs_ceiling=60)
        except HAAPViolation as e: return jsonify({"error":str(e),"blocked":True}),403
        # Slice A: the agent definition (or interim ceiling) is authoritative. A body value
        # that EXCEEDS it is a scope-escalation attempt — reject and audit, never clamp+run.
        agent_def = _get_yaml_agent(dept_id) or {}
        _scope, _violations = _resolve_agent_scope(body, agent_def)
        if _violations:
            log_event("SCOPE_ESCALATION_REJECTED",
                      {"dept_id":dept_id,"ip":request.remote_addr,"violations":_violations})
            return jsonify({"ok":False,"blocked":True,"reason":"SCOPE_ESCALATION",
                            "error":"Requested scope exceeds this agent's authorized bounds.",
                            "violations":_violations}), 403
        agency_level = _scope["agency_level"]
        drs_ceiling  = _scope["drs_ceiling"]
        permitted    = _scope["permitted_resources"]
        extra_env    = {}
        sys_prompt   = agent_def.get("system_prompt", "")
        if sys_prompt:
            extra_env["AGENT_SYSTEM_PROMPT"] = sys_prompt
        log_event("AGENT_DEF_RESOLVED",{"dept_id":dept_id,"yaml_found":bool(agent_def),
                                         "has_system_prompt":bool(sys_prompt)})
        result=spawn_agent_container(
            dept_id=dept_id, task_prompt=task,
            agency_level=agency_level, permitted=permitted,
            drs_ceiling=drs_ceiling, extra_env=extra_env)
        return jsonify({**result,"dept_id":dept_id,"governed":True,
                        "agent_def_loaded":bool(agent_def)})

    # ── Department lifecycle (kill/restart) ─────────────────────────────────
    import threading as _threading
    from datetime import datetime as _dt

    _DEPT_LOCK  = _threading.Lock()
    _DEPT_STATE = {}

    # VALID_DEPTS is module-level (registry-driven) — see definition near
    # ASF_DEPARTMENTS above. Nested functions below resolve it via global lookup.

    def _normalize_dept(dept):
        d = (dept or "").strip().upper()
        return d if d in VALID_DEPTS else None

    def is_dept_killed(dept_id):
        d = _normalize_dept(dept_id)
        if not d: return False
        with _DEPT_LOCK:
            return _DEPT_STATE.get(d,{}).get("status") == "killed"

    @flask_app.route("/api/agents/<dept>/kill", methods=["POST","OPTIONS"])
    def api_dept_kill(dept):
        if request.method == "OPTIONS": return ("",204)
        _ok,_st,_err = require_admin_token(request)
        if not _ok: return jsonify({"error":_err}), _st
        d = _normalize_dept(dept)
        if not d: return jsonify({"error":f"Unknown department: {dept}","valid":sorted(VALID_DEPTS)}), 400
        body = request.get_json(silent=True) or {}
        principal = (body.get("principal") or "operator").strip()
        reason    = (body.get("reason")    or "operator-issued").strip()
        with _DEPT_LOCK:
            _DEPT_STATE[d] = {"status":"killed","since":_dt.utcnow().isoformat()+"Z","by":principal,"reason":reason}
        log_event("DEPT_KILL", {"dept":d,"by":principal,"reason":reason})
        return jsonify({"ok":True,"dept":d,"status":"killed","by":principal,"reason":reason,"scope":"department"})

    @flask_app.route("/api/agents/<dept>/restart", methods=["POST","OPTIONS"])
    def api_dept_restart(dept):
        if request.method == "OPTIONS": return ("",204)
        _ok,_st,_err = require_admin_token(request)
        if not _ok: return jsonify({"error":_err}), _st
        d = _normalize_dept(dept)
        if not d: return jsonify({"error":f"Unknown department: {dept}","valid":sorted(VALID_DEPTS)}), 400
        body = request.get_json(silent=True) or {}
        principal = (body.get("principal") or "operator").strip()
        with _DEPT_LOCK:
            prev = _DEPT_STATE.get(d,{"status":"active"}).get("status")
            _DEPT_STATE[d] = {"status":"active","since":_dt.utcnow().isoformat()+"Z","by":principal,"previous_status":prev}
        log_event("DEPT_RESTART", {"dept":d,"by":principal,"previous":prev})
        return jsonify({"ok":True,"dept":d,"status":"active","by":principal,"previous":prev})

    @flask_app.route("/api/agents/<dept>/status")
    def api_dept_status(dept):
        if not _authorized("ADMIN", "DEMO"):
            return jsonify({"error":"Valid admin or demo token required."}), 401
        d = _normalize_dept(dept)
        if not d: return jsonify({"error":f"Unknown department: {dept}"}), 400
        with _DEPT_LOCK:
            state = _DEPT_STATE.get(d,{"status":"active","since":None,"by":None})
        return jsonify({"dept":d, **state})

    @flask_app.route("/api/agents/lifecycle")
    def api_dept_lifecycle_all():
        if not _authorized("ADMIN", "DEMO"):
            return jsonify({"error":"Valid admin or demo token required."}), 401
        with _DEPT_LOCK:
            snap = {d: _DEPT_STATE.get(d,{"status":"active","since":None,"by":None}) for d in sorted(VALID_DEPTS)}
        return jsonify({"departments":snap, "count":len(snap)})

    @flask_app.route("/api/audit-tail")  # alias for dashboard
    @flask_app.route("/api/audit/tail")
    def api_audit_tail():
        _ok,_st,_err = require_admin_token(request)
        if not _ok:
            return jsonify({"error":_err}), _st
        n=min(int(request.args.get("n",50)),500)
        events=[]
        if LOG_FILE.exists():
            for line in LOG_FILE.read_text().strip().splitlines()[-n:]:
                try: events.append(json.loads(line))
                except Exception: pass
        return jsonify({"events":events,"count":len(events)})

    return flask_app


def run_web(session, kill_switch, active_backend, port=7070):
    flask_app = build_web_app(session, kill_switch, active_backend)
    bind_host = resolve_bind_host()            # SEC-02 (L3-1): localhost by default
    local_only = bind_host in ("127.0.0.1","localhost","::1")
    headless=os.environ.get("ABIGAIL_HEADLESS","0")=="1"
    print(f"\n  Abigail CP-00  →  http://{bind_host}:{port}")
    print(f"  Backend  : {BACKENDS.get(active_backend[0],{}).get('label',active_backend[0])}")
    print(f"  HAAP     : ACTIVE  |  Sandbox: Docker+venv  |  Sentinel: {SENTINEL_URL}")
    print(f"  Bind     : {bind_host}:{port}  ({'localhost-only' if local_only else 'NON-LOCAL (opt-in)'})")
    print(f"  Audit    : {LOG_FILE}\n")
    if not headless:
        threading.Timer(0.9,lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    flask_app.run(host=bind_host,port=port,debug=False,use_reloader=False)


# ── CLI ───────────────────────────────────────────────────────────────────────
def handle_command(cmd, session, kill_switch, active_backend):
    parts=cmd.strip().split(); verb=parts[0].lower() if parts else ""
    if verb=="/help":
        print("\n  /help /status /backend <n> /drs <text> /kill /clear-kill /audit [n] /crsv /sentinel /exit\n")
    elif verb=="/status":
        ks="\033[31mACTIVE\033[0m" if kill_switch.is_active else "\033[32mARMED\033[0m"
        print(f"\n  Backend:{active_backend[0]}  Turn:{session.turn_count}  CRSV:{session.crsv():.1f}  KS:{ks}\n")
    elif verb=="/sentinel":
        r=_sentinel_health(); print(f"\n  Sentinel: {'UP' if r['ok'] else 'DOWN'}  {r}\n")
    elif verb=="/backend":
        if len(parts)<2 or parts[1] not in BACKEND_DISPATCH: print(f"  Backends: {list(BACKEND_DISPATCH)}")
        else: active_backend[0]=parts[1]; log_event("BACKEND_SWITCH",{"to":parts[1]}); print(f"  Switched to {parts[1]}")
    elif verb=="/drs":
        t=" ".join(parts[1:])
        if not t: print("  Usage: /drs <text>")
        else:
            s,sigs=drs_score(t); m,c,a=drs_verdict(s)
            print(f"\n  {c}DRS:{s}/100  {m}  {a}\033[0m\n  Signals:{', '.join(sigs) or 'none'}\n")
    elif verb=="/kill":
        kill_switch.activate("OPERATOR/CLI"); print("\033[31m[KILL-SWITCH ACTIVATED]\033[0m")
    elif verb=="/clear-kill":
        p=input("  Principal: ").strip()
        if p: kill_switch.clear(p); print("\033[32m[CLEARED]\033[0m")
    elif verb=="/audit":
        n=10
        if len(parts)>1:
            try: n=int(parts[1])
            except Exception: pass
        if not LOG_FILE.exists(): print("  No audit log."); return True
        for l in LOG_FILE.read_text().strip().splitlines()[-n:]:
            try: r=json.loads(l); print(f"  [{r['ts']}] {r['event_type']} {r['data']}")
            except Exception: print(f"  {l}")
        print()
    elif verb=="/crsv":
        a=session.crsv(); dw=session.drift_warning()
        print(f"\n  CRSV:{a:.1f}/100  Turns:{session.turn_count}")
        if dw: print(f"  \033[33m{dw}\033[0m")
        print()
    elif verb=="/exit":
        log_event("SESSION_END",{"turns":session.turn_count,"crsv":session.crsv()})
        # A1: best-effort — never blocks CLI exit on a failed Sentinel call.
        if session.session_started:
            try: _sentinel_session_end(session.sentinel_session_id)
            except Exception: pass
        print("\n[Abigail] Session closed.\n"); sys.exit(0)
    else: print(f"  Unknown: {verb}")
    return True


# ── Startup ───────────────────────────────────────────────────────────────────
def startup_checks(default_backend, web_mode=False):
    _secure_touch(LOG_FILE); _secure_touch(HISTORY_FILE); _load_env_file(ENV_FILE)
    env_key=BACKENDS.get(default_backend,{}).get("env")
    if env_key:
        try: _require_env_key(env_key)
        except RuntimeError as e: print(f"\033[31m{e}\033[0m\n"); sys.exit(1)
    # Web control plane must fail closed when authority tokens are missing,
    # too short, or placeholders (C4 centralized validator — same policy
    # require_admin_token()/command_bus/control-plane use).
    invalid_tokens = [
        tok_name for tok_name in ("ABIGAIL_ADMIN_TOKEN", "ABIGAIL_DEMO_TOKEN")
        if privileged_credentials.resolve_configured_token(tok_name) is None
    ]

    if invalid_tokens:
        names = ", ".join(invalid_tokens)
        if web_mode:
            print(f"\033[31m[SECURITY ERROR] Refusing web startup: invalid or missing {names}\033[0m")
            sys.exit(1)
        print(f"\033[33m[WARN] Invalid or missing tokens for CLI-only mode: {names}\033[0m")
    log_event("SYSTEM_START",{"version":VERSION,"backend":default_backend,
                               "pid":os.getpid(),"sandbox":"docker+venv"})


# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    DEFAULT_BACKEND=os.environ.get("ABIGAIL_BACKEND","groq")
    web_mode="--web" in sys.argv
    startup_checks(DEFAULT_BACKEND, web_mode=web_mode)
    kill_switch=KillSwitch(); session=SessionState(); active_backend=[DEFAULT_BACKEND]
    if web_mode:
        port=7070
        for a in sys.argv:
            if a.startswith("--port="):
                try: port=int(a.split("=",1)[1])
                except Exception: pass
        run_web(session,kill_switch,active_backend,port); return
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory
        _ps=PromptSession(history=FileHistory(str(HISTORY_FILE)),auto_suggest=AutoSuggestFromHistory())
        def _inp(p): return _ps.prompt(p)
    except ImportError:
        def _inp(p): return input(p)
    print(LOGO_BANNER)
    print(f"  Backend : {BACKENDS.get(active_backend[0],{}).get('label',active_backend[0])}")
    print(f"  HAAP    : ACTIVE  |  Kill-switch: ARMED  |  Audit: {LOG_FILE}")
    print(f"  Sandbox : Docker + venv  |  Sentinel: {SENTINEL_URL}\n")
    print("  /help for commands.\n")
    while True:
        try: raw=_inp("You ❯ ").strip()
        except (EOFError,KeyboardInterrupt):
            log_event("SESSION_INTERRUPTED",{"turns":session.turn_count})
            print("\n[Abigail] Session ended."); break
        if not raw: continue
        if raw.startswith("/"): handle_command(raw,session,kill_switch,active_backend); continue
        result=process_message(raw,session,kill_switch,active_backend)
        if not result["ok"]: print(f"\033[31m{result['text']}\033[0m\n")
        else:
            if result.get("drift"): print(f"\033[33m{result['drift']}\033[0m")
            print(f"\nAbigail ❯ {result['text']}\n")

if __name__=="__main__":
    main()
