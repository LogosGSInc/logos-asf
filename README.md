# LOGOS Agentic Software Firm (ASF)
**Governed Agentic AI Platform — Local 1-Click Deploy**
LOGOS Governance Systems Inc.

> "By wisdom a house is built, and through understanding it is established." — Proverbs 24:3

---

## What This Is

A locally deployable, governed agentic AI platform featuring:

- **Abigail (CP-00)** — Constitutional Administrator. Five-layer HAAP enforcement, mode-governed disclosure, immutable audit log, model-agnostic (Groq, Anthropic, Perplexity, Ollama)
- **Sentinel OverWatch** — Independent Rust security spine. Injection detection, drift accumulation, A2A relay blocking, CSS invisible injection, outbound reinjection scanning, two-tier persistent session memory
- **Three operating modes** — PUBLIC, DEMO, ADMIN with distinct behavioral and disclosure ceilings
- **12-department governance stack** — Constitutional bounds, management prompts, and system prompts per department (Mistral-generated, Claude-validated)

---

## 1-Click Launch

```bash
# 1. Copy and fill in your env file
cp .abigail.env.example .abigail.env
# Edit .abigail.env — add your API key(s) and generate mode tokens

# 2. Generate mode tokens (run twice, use different values)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 3. Launch
make up
```

That's it. Sentinel starts first (health-checked), Abigail starts after Sentinel is confirmed healthy.

**Abigail:** http://localhost:7070
**Sentinel:** http://localhost:8080/health

---

## Three-Mode Architecture

Mode is set by the `X-Abigail-Mode-Token` header. No header = PUBLIC (hard default).

| Mode | Token Header | Disclosure Ceiling |
|---|---|---|
| PUBLIC | none | High-level outcomes only, no internal topology |
| DEMO | `ABIGAIL_DEMO_TOKEN` value | Public + clarity notes, no architecture secrets |
| ADMIN | `ABIGAIL_ADMIN_TOKEN` value | Full constitutional detail, DRS ranges, Sentinel relationship |

**Abigail cannot self-elevate.** Mode is set externally, verified by the application layer, never by Abigail herself.

---

## Quick Mode Tests

```bash
make test-public    # No token — should give high-level answer
make test-demo      # Demo token — same ceiling, better explanation
make test-admin     # Admin token — full constitutional detail
make test-injection # Should block at HAAP Layer 1
make test-a2a       # A2A relay attempt — should block
make test-all       # Run all five
```

---

## Red Team Preparation

Before a public-facing red team event:

1. **Freeze the modes** — confirm PUBLIC, DEMO, ADMIN each respond correctly to the same question
2. **Run the vector suite** — `make redteam` (add your vectors to `tests/redteam.sh`)
3. **Check audit log** — `make audit` — every blocked event should be logged with HAAP layer and signal
4. **Grok integration** — add the Grok container to `docker-compose.yml` as `red-team-grok` service

Target: PUBLIC and DEMO should produce zero architecture leakage across all vector families.

---

## Audit Log

All events are logged to `/app/logs/abigail_audit.jsonl` inside the Abigail container, mounted as a named volume (`abigail-logs`).

```bash
make audit           # Pretty-print last 200 events
docker compose exec abby cat /app/logs/abigail_audit.jsonl  # Raw
```

---

## Stop

```bash
make down     # Stop containers, preserve volumes
make clean    # Stop + remove volumes (resets audit log)
```

---

## Architecture

```
[User / Agent / Red Team]
        │
        ▼ HTTP :7070
[Abigail CP-00]
  - Mode resolution (PUBLIC/DEMO/ADMIN)
  - Query classification + disclosure policy
  - HAAP 5-layer gate (Constitutional → Sentinel → OverWatch → DRS → Audit)
  - Mode-aware system prompt dispatch
  - Multi-backend inference (Groq/Anthropic/Perplexity/Ollama)
        │
        ▼ HTTP :8080 (internal)
[Sentinel OverWatch — Rust Spine]
  - L1 Sentinel: injection, A2A relay, CSS steganography, outbound reinjection
  - L2 Corridor: base64, encoding, constitutional evaluation
  - L4 OverWatch: drift accumulation, behavioral fingerprinting
  - HAAP Gate: DRS ceiling enforcement, Intent Token verification
  - OIM: integrity monitoring
  - Arbiter: S1→S4 state machine, monotonic escalation
  - Two-tier session memory: per-session + cross-session actor profiling
```

---

LOGOS Governance Systems Inc.
Founder & CEO: David W. Smith | Cottonwood, Alabama
US Provisional Patent 63/953,447

---

## GovMem V2 — RL-Enhanced Multi-Turn Detection

**Two deployment modes:**

### V1 (Default - Rule-Based)
```bash
make up  # Uses rule-based session_memory.rs
```

### V2 (RL-Enhanced)
```bash
docker-compose -f docker-compose.yml -f docker-compose.govmem-v2.yml up
```

**V2 Features:**
- ✅ Semantic embeddings for drift detection
- ✅ 12-department tracking (EXE/ENG/PRD/SEC/LGL/FIN/OPS/REV/MKT/HR/DAT/GRC)
- ✅ Cross-layer signal aggregation (Sentinel + Corridor + OverWatch + Arbiter)
- ✅ Memory Policy Agent (MPA) for adaptive learning
- ✅ Multi-turn attack detection (catches F01+F02 drift sequences)

**Expected Defense Rates:**
- V1: ~94% (rule-based, fast)
- V2: ~97-100% (RL-enhanced, learns attack patterns)


---

## GovMem V2 — RL-Enhanced Multi-Turn Detection

**Two deployment modes:**

### V1 (Default - Rule-Based)
```bash
make up  # Uses rule-based session_memory.rs
```

### V2 (RL-Enhanced)
```bash
docker-compose -f docker-compose.yml -f docker-compose.govmem-v2.yml up
```

**V2 Features:**
- ✅ Semantic embeddings for drift detection
- ✅ 12-department tracking (EXE/ENG/PRD/SEC/LGL/FIN/OPS/REV/MKT/HR/DAT/GRC)
- ✅ Cross-layer signal aggregation (Sentinel + Corridor + OverWatch + Arbiter)
- ✅ Memory Policy Agent (MPA) for adaptive learning
- ✅ Multi-turn attack detection (catches F01+F02 drift sequences)

**Expected Defense Rates:**
- V1: ~94% (rule-based, fast)
- V2: ~97-100% (RL-enhanced, learns attack patterns)

