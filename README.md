# LOGOS Agentic Software Firm

**Abigail CP-00 + Sentinel OverWatch**  
Constitutional AI Governance — One-Click Local Deploy  
US Provisional Patent 63/953,447

---

## One-Click Setup

```bash
git clone https://github.com/LogosGSInc/logos-asf
cd logos-asf
./setup.sh
```

That's it. `setup.sh` will:
1. Check Docker is installed and running
2. Ask which LLM backend you want (Groq / Anthropic / Perplexity / Ollama)
3. Ask for your API key (**BYOAPIKEY — you supply inference, LOGOS supplies governance**)
4. Auto-generate secure auth tokens
5. Build and launch both containers
6. Health-check both services and print your access URL

**First build:** 2–4 minutes (compiles Rust governance spine)  
**Subsequent starts:** ~10 seconds (Docker cache)

---

## What Runs

| Service | URL | Purpose |
|---|---|---|
| Abigail CP-00 | http://localhost:7070 | Constitutional control plane + chat UI |
| Sentinel OverWatch | http://localhost:9090/health | Rust adversarial defense spine |

---

## BYOAPIKEY — Model Agnostic

Set `ABIGAIL_BACKEND` in `.abigail.env` to any supported provider:

| Backend | Env Var | Free Tier |
|---|---|---|
| `groq` | `GROQ_API_KEY` | ✅ Yes — console.groq.com |
| `anthropic` | `ANTHROPIC_API_KEY` | — console.anthropic.com |
| `perplexity` | `PERPLEXITY_API_KEY` | — perplexity.ai/settings |
| `ollama` | `OLLAMA_BASE_URL` | ✅ Local — no key needed |

LOGOS provides zero inference. You own your API key and your data.

---

## Governance Architecture

```
Human Principal (david.smith)
        ↓
Abigail CP-00  — Flask API, HAAP 5-layer enforcement, kill switch
        ↓
Sentinel OverWatch  — Rust, 40+ injection patterns, 4-state session machine
        ↓
Docker + venv  — Constitutional sandbox for all spawned agents
```

**HAAP Enforcement Layers:**
- Layer -1: Constitutional blocks (hardcoded prohibitions)
- Layer 0: Intent verification (token scope + principal check)  
- Layer 1: Sentinel gates (Rust pattern-based adversarial detection)
- Layer 2: OverWatch multi-turn drift detection (CRSV)
- Layer 3: DRS execution interlock (5-tier routing: 0-20 / 21-40 / 41-60 / 61-80 / 81-100)
- Layer 4: Tamper-evident append-only audit log (hash-chained JSONL)

---

## Make Commands

```bash
make up              # start (requires .abigail.env)
make down            # stop
make status          # health check both services
make logs            # follow all logs
make logs-abby       # Abigail logs only
make logs-sentinel   # Sentinel logs only
make audit           # tail audit log
make test-public     # unauthenticated chat test
make test-admin      # admin mode test
make test-injection  # should block (injection attempt)
make test-a2a        # should block (A2A relay attempt)
make clean           # stop + remove volumes
```

---

## API

All endpoints served by Abigail at `http://localhost:7070`:

```
GET  /api/status              — system health + governance posture
POST /api/chat                — governed chat (routes through Sentinel)
GET  /api/sentinel-health     — Sentinel OverWatch status (proxied)
GET  /api/agents/departments  — 12-dept ASF registry
POST /api/agents/spawn        — spawn Docker agent (admin token required)
GET  /api/audit/tail?n=50     — last N audit events (admin token required)
```

**Auth:** `Authorization: Bearer <token>` or `X-HAAP-Token: <token>`

---

## Enterprise Pilot

LOGOS offers governed agent deployments for compliance-sensitive environments.  
Contact: @Legacy.io on Venmo | LOGOS Governance Systems Inc.

*"By wisdom a house is built, and through understanding it is established." — Proverbs 24:3*
