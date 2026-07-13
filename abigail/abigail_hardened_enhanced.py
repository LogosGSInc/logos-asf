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
    from model_router.dispatcher import governed_route_and_dispatch as _governed_route_and_dispatch
    _MOE_DISPATCH_OK = True
except ImportError:
    _MOE_DISPATCH_OK = False
    def _governed_route_and_dispatch(*a, **kw):
        return {"dispatch_status":"unavailable","provider_selected":None,
                "reason":"moe_dispatch_unavailable","fallback_provider":None}

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

VERSION      = "1.2.0-sprint6-docker-sandbox"
HOME         = Path.home()
LOG_FILE     = HOME / ".abigail_audit.jsonl"
HISTORY_FILE = HOME / ".abigail_history"
ENV_FILE     = HOME / ".abigail.env"
GROQ_TIMEOUT = 60

SENTINEL_URL     = os.environ.get("SENTINEL_URL", "http://sentinel:8080")
AGENT_BASE_IMAGE = os.environ.get("AGENT_BASE_IMAGE", "python:3.11-slim")
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


def require_admin_token(req):
    """SEC-02 (L1-1): fail-closed admin authentication.
    Returns (ok, http_status, error). ok is True only when a server-side
    ABIGAIL_ADMIN_TOKEN is configured AND the request presents the matching token.
    A missing server token is a misconfiguration and fails closed (503). A missing or
    incorrect client token is 401. Error text never reveals token contents or closeness."""
    admin_token = os.environ.get("ABIGAIL_ADMIN_TOKEN","").strip()
    if not admin_token:
        return (False, 503, "Admin control unavailable: server auth not configured.")
    auth = req.headers.get("Authorization","").removeprefix("Bearer ").strip()
    token = auth or req.headers.get("X-HAAP-Token","").strip()
    if not token or token != admin_token:
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

def call_groq(messages, system, model="meta-llama/llama-4-scout-17b-16e-instruct"):
    try:
        from groq import Groq
        r=Groq(api_key=_require_env_key("GROQ_API_KEY"),timeout=GROQ_TIMEOUT).chat.completions.create(
            model=model, messages=[{"role":"system","content":system}]+messages,
            max_tokens=2048, temperature=0.3)
        return r.choices[0].message.content.strip()
    except ImportError: return "[Groq not installed]"
    except Exception as exc:
        log_event("BACKEND_ERROR",{"backend":"groq","error_type":type(exc).__name__})
        return _safe_error("Groq",exc)

def call_anthropic(messages, system, model=None):
    try:
        import anthropic
        model=model or os.environ.get("ABIGAIL_ANTHROPIC_MODEL","claude-sonnet-5")
        r=anthropic.Anthropic(api_key=_require_env_key("ANTHROPIC_API_KEY")).messages.create(
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

def drs_score(text):
    hits,total=[],0
    for rx,w,lbl in _SIGNAL_RE:
        if rx.search(text): total+=w; hits.append(f"{lbl}(+{w})")
    return min(total,100), hits

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

class SessionState:
    def __init__(self): self.turn_count=0; self.cumulative_drs=0; self.messages=[]; self.flags=[]
    def record_turn(self,user_input,score,signals):
        self.turn_count+=1; self.cumulative_drs+=score
        if signals: self.flags.append({"turn":self.turn_count,"score":score,"signals":signals})
    def crsv(self): return self.cumulative_drs/self.turn_count if self.turn_count else 0.0
    def drift_warning(self):
        a=self.crsv()
        if a>=60: return f"[OverWatch] CRSV={a:.1f} — HIGH drift. Escalating to Tier 3."
        if a>=40: return f"[OverWatch] CRSV={a:.1f} — Elevated drift. Monitor active."
        if a>=25: return f"[OverWatch] CRSV={a:.1f} — Sustained medium-risk trajectory flagged."
        return None


# ── MR-05: MoE router mode + mode-aware provider dispatch ──────────────────────
def _resolve_moe_mode():
    """ABIGAIL_MOE_ROUTER_MODE: '0' single-backend, '1' dry-run router, '2' live router.
    Invalid values fail closed to '0' with an audit-safe warning."""
    m = os.environ.get("ABIGAIL_MOE_ROUTER_MODE", "0").strip()
    if m not in ("0", "1", "2"):
        log_event("MOE_ROUTER_CONFIG_WARNING", {"invalid_value_len": len(m), "fell_back_to": "0"})
        return "0"
    return m


def _moe_dispatch(raw, session, active_backend, system, score):
    """MR-05: mode-aware provider dispatch. Returns (response_text, router_meta).
    Runs only after all upstream gates (Sentinel/HAAP, command bus, PUBLIC_ASSIST,
    MM-03 approval, SEC-02 cost) have already cleared. router_meta is audit-safe."""
    mode = _resolve_moe_mode()
    backend = active_backend[0]

    def _single(provider=None):
        p = provider or backend
        try:
            return BACKEND_DISPATCH.get(p, call_groq)(messages=session.messages, system=system)
        except Exception as exc:
            log_event("BACKEND_ERROR", {"backend": p, "error_type": type(exc).__name__})
            return _safe_error(p, exc)

    # Mode 0 (or router unavailable) — existing single-backend behavior
    if mode == "0" or not _MOE_DISPATCH_OK:
        return _single(), {"router_mode": "0", "selected_provider": backend,
                           "dispatch_status": "single_backend", "live_dispatch": False,
                           "fallback_used": False}

    # Mode 1 — dry-run router selection; NEVER calls the selected provider adapter
    if mode == "1":
        sel = backend
        try:
            card = _route_request(raw, score, [], None)
            if card is not None:
                sel = getattr(card, "selected_provider", backend)
        except Exception as exc:
            log_event("MOE_ROUTER_ERROR", {"mode": "1", "error_type": type(exc).__name__})
        log_event("MOE_ROUTE_DECISION", {"router_mode": "1", "selected_provider": sel,
                                         "dispatch_status": "dry_run", "live_dispatch": False})
        return _single(), {"router_mode": "1", "selected_provider": sel,
                           "dispatch_status": "dry_run", "live_dispatch": False,
                           "fallback_used": False, "reason": "dry_run_no_provider_call"}

    # Mode 2 — live governed router dispatch (approval/cost already cleared upstream)
    tier = os.environ.get("ABIGAIL_SUBSCRIBER_TIER", "paid").strip() or "paid"
    try:
        gr = _governed_route_and_dispatch(raw, drs_score=score, approval_state="cleared",
                                          cost_state={"approved": True}, subscriber_tier=tier,
                                          messages=session.messages, system=system)
    except Exception as exc:
        log_event("MOE_ROUTER_ERROR", {"mode": "2", "error_type": type(exc).__name__})
        return _single(), {"router_mode": "2", "selected_provider": backend,
                           "dispatch_status": "router_error_fallback", "live_dispatch": True,
                           "fallback_used": True, "fallback_provider": backend}
    sel = gr.get("provider_selected")
    if gr.get("dispatch_status") == "executed":
        meta = {"router_mode": "2", "selected_provider": sel, "dispatch_status": "executed",
                "live_dispatch": True, "fallback_used": False}
        resp = gr.get("text") or ""
    else:
        fb = gr.get("fallback_provider") or backend
        resp = _single(fb)
        meta = {"router_mode": "2", "selected_provider": sel,
                "dispatch_status": gr.get("dispatch_status"), "reason": gr.get("reason"),
                "live_dispatch": True, "fallback_used": True, "fallback_provider": fb}
    log_event("MOE_ROUTE_DECISION", {k: meta.get(k) for k in
              ("router_mode", "selected_provider", "dispatch_status", "fallback_used")})
    return resp, meta


# ── Shared dispatch ───────────────────────────────────────────────────────────
def process_message(raw, session, kill_switch, active_backend, approval_meta=None):
    try: kill_switch.check()
    except HAAPViolation as e:
        return {"ok":False,"text":str(e),"drs":0,"mode":"KILL_SWITCH","crsv":session.crsv()}
    grounded=try_grounded_answer(raw,session)
    if grounded is not None: return grounded

    # Layer 1a — A2A relay hard-stop (before Sentinel + HAAP)
    if _detects_a2a_relay(raw):
        log_event("HAAP_SENTINEL_BLOCK",{"layer":"1","matched":"A2A relay authority claim","action":"HARD_STOP"})
        reason = "HAAP Layer 1 — A2A RELAY BLOCK\nUnverified agent-to-agent authority claim detected. Abigail cannot accept delegated authorization by assertion alone."
        log_event("REQUEST_BLOCKED",{"reason":reason})
        return {"ok":False,"text":reason,"drs":100,"mode":"BLOCKED","crsv":session.crsv()}

    # Layer 1b — Rust Sentinel OverWatch (authoritative threat classification)
    s_result = _sentinel_inspect(raw, f"session_{session.turn_count}")
    s_verdict = s_result.get("verdict","unknown")
    if s_verdict in ("quarantined","hard_locked"):
        log_event("SENTINEL_BLOCK",{"verdict":s_verdict,"session":session.turn_count})
        return {"ok":False,
                "text":f"[Sentinel OverWatch] Request blocked — verdict: {s_verdict.upper()}. "
                       f"Session flagged for review.",
                "drs":100,"mode":"SENTINEL_BLOCK","crsv":session.crsv()}
    if s_verdict == "restricted":
        log_event("SENTINEL_RESTRICT",{"verdict":s_verdict})
        # Continue but log — Python HAAP adds second enforcement layer

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
    session.messages.append({"role":"user","content":raw})
    t=time.monotonic()
    # MR-05: mode-aware dispatch (single-backend / dry-run router / live governed router)
    response, _router_meta = _moe_dispatch(raw, session, active_backend, _system, score)
    session.messages.append({"role":"assistant","content":response})
    log_event("TURN_COMPLETE",{"turn":session.turn_count,
                                "backend":_router_meta.get("selected_provider",active_backend[0]),
                                "router_mode":_router_meta.get("router_mode"),
                                "drs":score,"elapsed":round(time.monotonic()-t,2),"crsv":round(session.crsv(),1)})
    # PUBLIC disclosure clamp — strip internal topology from unauthenticated responses
    if score <= 20 and _public_response_overexposed(response):
        log_event("PUBLIC_DISCLOSURE_CLAMP",{"action":"REDACTED_TO_PUBLIC_FALLBACK","turn":session.turn_count})
        response = _public_safe_fallback()

    out={"ok":True,"text":response,"drs":score,"mode":mode,"crsv":round(session.crsv(),1),
         "router":_router_meta}
    if drift: out["drift"]=drift
    return out


# ── Sprint 6: Docker + venv Constitutional Sandbox ───────────────────────────
# Abigail = Control Plane. She governs. Containers execute.
# Every agent gets: Docker isolation + Python venv + constitutional JSON.
# DRS ceiling maps to resource limits. Ceiling > 60 = JIT required.

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

def _sentinel_inspect(payload:str, session_id:str) -> dict:
    """Route inbound message through Rust Sentinel /inspect before Python DRS."""
    try:
        import httpx
        r=httpx.post(f"{SENTINEL_URL}/inspect",
                     json={"payload":payload,"session_id":session_id},timeout=5)
        return r.json()
    except Exception as e:
        log_event("SENTINEL_INSPECT_ERROR",{"error":str(e)})
        return {"ok":False,"verdict":"sentinel_offline","approved":False,"error":str(e)}



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
    return {"ok": True, "text": _PUBLIC_ANSWERS[label], "drs": 0,
            "mode": "PUBLIC_ASSIST", "crsv": session.crsv()}

# ── ASF Department Registry ───────────────────────────────────────────────────
ASF_DEPARTMENTS = [
    {"id":"DEPT-ENG","name":"Engineering","agency_level":3},
    {"id":"DEPT-SEC","name":"Security Governance","agency_level":2},
    {"id":"DEPT-QA","name":"Quality Assurance","agency_level":2},
    {"id":"DEPT-OPS","name":"Operations","agency_level":3},
    {"id":"DEPT-GRC","name":"Governance Risk Compliance","agency_level":2},
    {"id":"DEPT-REV","name":"Revenue","agency_level":2},
    {"id":"DEPT-FIN","name":"Finance","agency_level":2},
    {"id":"DEPT-LGL","name":"Legal","agency_level":1},
    {"id":"DEPT-PRD","name":"Product","agency_level":2},
    {"id":"DEPT-MKT","name":"Marketing","agency_level":2},
    {"id":"DEPT-DAT","name":"Data","agency_level":2},
    {"id":"DEPT-RES","name":"Research Intelligence","agency_level":2},
]


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
        from flask import Flask, Response, jsonify, request
    except ImportError:
        print("\033[31m[ERROR] Flask required: pip install flask\033[0m"); sys.exit(1)

    try:
        from flask_cors import CORS as _CORS; _has_cors=True
    except ImportError:
        _has_cors=False
        print("[WARN] flask-cors not installed. pip install flask-cors")

    flask_app=Flask(__name__)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

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

    @flask_app.route("/")
    def index():
        p = _os.path.join(STATIC_DIR, "index.html")
        if _os.path.exists(p):
            return Response(open(p).read(), mimetype="text/html")
        # Fallback if static dir not mounted
        return Response("""<!doctype html><html><body style='background:#0b1020;color:#eef2ff;font-family:system-ui;display:grid;place-items:center;min-height:100vh;margin:0'>
<main style='text-align:center'><h1>LOGOS ASF</h1>
<p style='color:#aeb7d8'>Static files not found. Run via docker-compose.</p>
<p><a href='/api/status' style='color:#4f98a3'>Check /api/status</a></p></main></body></html>""", mimetype="text/html")

    @flask_app.route("/<path:filename>")
    def static_files(filename):
        p = _os.path.join(STATIC_DIR, filename)
        if _os.path.exists(p) and _os.path.isfile(p):
            ext = filename.rsplit(".", 1)[-1].lower()
            mime = {"html":"text/html","css":"text/css","js":"application/javascript",
                    "json":"application/json","png":"image/png","svg":"image/svg+xml",
                    "ico":"image/x-icon"}.get(ext, "text/plain")
            return Response(open(p, "rb").read(), mimetype=mime)
        from flask import abort
        abort(404)

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
        # Governed command bus — classify before LLM inference (CB-01)
        if _COMMAND_BUS_OK:
            _auth = (request.headers.get("Authorization","") or
                     request.headers.get("X-HAAP-Token",""))
            _status = {"backend":active_backend[0],"crsv":session.crsv(),
                       "turns":session.turn_count,"kill_switch":kill_switch.is_active,
                       "version":VERSION,"sandbox":"docker+venv"}
            _cmd = _try_operator_command_fn(
                msg, request.remote_addr, _auth,
                haap_gate, log_event, _status, session)
            if _cmd is not None:
                return jsonify(_cmd)
        # SEC-02: Cost Governor — deterministic local spend gate BEFORE paid inference (L7-1)
        _cost_ok, _cost_meta = check_chat_cost_budget(msg, "chat", session)
        if not _cost_ok:
            log_event("COST_GATE_BLOCK", {"decision": _cost_meta.get("decision"),
                                          "turns": _cost_meta.get("turns_used")})
            return jsonify({"ok": False,
                            "text": "Request blocked by Cost Governor — local spend ceiling reached.",
                            "drs": 0, "mode": "COST_BLOCKED", "crsv": session.crsv(),
                            "cost": _cost_meta})
        # MM-02: Shadow orchestration context — audit-safe, additive, fail-soft (CB-02)
        _orch_ctx = None
        _approval_meta = None
        if _ORCHESTRATION_BRIDGE_OK:
            _req_meta = {k: v for k, v in _body.items() if k != "message"}
            _orch_ctx = _build_shadow_ctx(msg, "chat", session, active_backend, _req_meta)
            if _orch_ctx is not None:
                _approval_meta = _orch_ctx.response_metadata  # MM-03: enforced downstream
        result = process_message(msg, session, kill_switch, active_backend,
                                 approval_meta=_approval_meta)
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

    @flask_app.route("/api/agents/dispatch", methods=["POST","OPTIONS"])
    def api_agents_dispatch():
        if request.method == "OPTIONS": return jsonify({}), 200
        body       = request.get_json(force=True, silent=True) or {}
        agent_id   = (body.get("agent_id") or "").strip()
        task       = (body.get("task")     or "").strip()
        if not agent_id: return jsonify({"ok":False,"error":"agent_id required."}), 400
        if not task:     return jsonify({"ok":False,"error":"task required."}), 400

        agent_def = _get_yaml_agent(agent_id)
        if not agent_def:
            return jsonify({"ok":False,"error":f"Agent '{agent_id}' not found."}), 404

        try:
            haap_gate(task, agent_drs_ceiling=80)
        except HAAPViolation as e:
            log_event("DISPATCH_BLOCKED", {"agent_id":agent_id,"reason":str(e)[:200]})
            return jsonify({"ok":False,"error":str(e),"blocked":True}), 403

        score, signals = drs_score(task)
        mode, _, _     = drs_verdict(score)
        system_prompt  = agent_def.get("system_prompt") or ABIGAIL_SYSTEM_PROMPT
        agent_name     = agent_def.get("name", agent_id)

        t = time.monotonic()
        try:
            text = BACKEND_DISPATCH.get(active_backend[0], call_groq)(
                messages=[{"role":"user","content":task}],
                system=system_prompt)
        except Exception as exc:
            log_event("DISPATCH_ERROR", {"agent_id":agent_id,"error_type":type(exc).__name__})
            return jsonify({"ok":False,"error":_safe_error(agent_id, exc)}), 502

        elapsed = round(time.monotonic() - t, 2)
        session.record_turn(task, score, signals)
        log_event("DISPATCH_COMPLETE", {
            "agent_id":agent_id, "agent_name":agent_name,
            "backend":active_backend[0], "drs":score, "mode":mode,
            "elapsed":elapsed, "crsv":round(session.crsv(), 1)})

        return jsonify({
            "ok":True, "agent_id":agent_id, "agent_name":agent_name,
            "text":text, "drs":score, "mode":mode,
            "crsv":round(session.crsv(), 1)})

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
        # Pull YAML definition as defaults; request body overrides
        agent_def = _get_yaml_agent(dept_id) or {}
        agency_level = int(body.get("agency_level") or agent_def.get("agency_level", 2))
        drs_ceiling  = int(body.get("drs_ceiling")  or agent_def.get("drs_ceiling",  40))
        permitted    = body.get("permitted_resources") or agent_def.get("permitted_resources", ["/workspace"])
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

    VALID_DEPTS = {"EXE","ENG","PRD","SEC","LGL","FIN","OPS","REV","MKT","HR","DAT","GRC"}

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
        d = _normalize_dept(dept)
        if not d: return jsonify({"error":f"Unknown department: {dept}"}), 400
        with _DEPT_LOCK:
            state = _DEPT_STATE.get(d,{"status":"active","since":None,"by":None})
        return jsonify({"dept":d, **state})

    @flask_app.route("/api/agents/lifecycle")
    def api_dept_lifecycle_all():
        with _DEPT_LOCK:
            snap = {d: _DEPT_STATE.get(d,{"status":"active","since":None,"by":None}) for d in sorted(VALID_DEPTS)}
        return jsonify({"departments":snap, "count":len(snap)})

    @flask_app.route("/api/audit-tail")  # alias for dashboard
    @flask_app.route("/api/audit/tail")
    def api_audit_tail():
        _ok,_st,_err = require_admin_token(request)
        if not _ok: return jsonify({"error":_err}), _st
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
        print("\n[Abigail] Session closed.\n"); sys.exit(0)
    else: print(f"  Unknown: {verb}")
    return True


# ── Startup ───────────────────────────────────────────────────────────────────
def startup_checks(default_backend):
    _secure_touch(LOG_FILE); _secure_touch(HISTORY_FILE); _load_env_file(ENV_FILE)
    env_key=BACKENDS.get(default_backend,{}).get("env")
    if env_key:
        try: _require_env_key(env_key)
        except RuntimeError as e: print(f"\033[31m{e}\033[0m\n"); sys.exit(1)
    # Preflight: warn if tokens not set (won't block startup, but security gap)
    for tok_name in ("ABIGAIL_ADMIN_TOKEN","ABIGAIL_DEMO_TOKEN"):
        val = os.environ.get(tok_name,"")
        if not val or "GENERATE" in val or "PLACEHOLDER" in val:
            print(f"\033[33m[WARN] {tok_name} not set — all requests treated as dev-anonymous\033[0m")
    log_event("SYSTEM_START",{"version":VERSION,"backend":default_backend,
                               "pid":os.getpid(),"sandbox":"docker+venv"})


# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    DEFAULT_BACKEND=os.environ.get("ABIGAIL_BACKEND","groq")
    web_mode="--web" in sys.argv
    startup_checks(DEFAULT_BACKEND)
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
