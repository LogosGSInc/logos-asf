# Sentinel Health Proxy — Abigail Patch

## Why this exists

The dashboard cannot fetch `http://127.0.0.1:9090/health` directly from the
operator's browser when running in:

- GitHub Codespaces preview
- Any reverse-proxy deployment
- Any VPS / cloud deployment
- Any environment where the operator's browser ≠ the host running the containers

The browser's `127.0.0.1` is the operator's *own* machine, not the container.
Solution: proxy the Sentinel health call **server-side** through Abigail.
Abigail can reach Sentinel over the Docker network at `http://sentinel:8080`.

The dashboard hits same-origin `/api/sentinel-health` — works everywhere.

---

## Patch

### File: `abigail/abigail_hardened_enhanced.py`

Add this route inside `run_web()`, alongside the existing routes
(near `/api/status` for clarity).

```python
    @app.route("/api/sentinel-health")
    def sentinel_health_proxy():
        """
        Server-side proxy to Sentinel /health.
        Browser cannot reach Sentinel directly in Codespaces / VPS / proxy
        deployments. Abigail reaches Sentinel over the Docker network.
        """
        import urllib.request
        import urllib.error
        sentinel_url = os.environ.get("SENTINEL_URL", "http://sentinel:8080")
        try:
            req = urllib.request.Request(
                f"{sentinel_url}/health",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = resp.read().decode("utf-8")
                payload = json.loads(body) if body else {}
                return jsonify(payload), 200
        except urllib.error.URLError as e:
            return jsonify({
                "ok": False,
                "error": "sentinel_unreachable",
                "detail": str(e.reason) if hasattr(e, "reason") else str(e),
            }), 200  # 200 so dashboard treats it as "unavailable" not "broken"
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }), 200
```

### Notes

- `SENTINEL_URL` env var is **already set** in `docker-compose.yml`
  (line `SENTINEL_URL=http://sentinel:8080`) — no compose changes needed.
- Returns HTTP 200 even on failure so the dashboard frontend reads
  `state.sentinel.ok === false` and renders the "Unavailable" badge cleanly
  instead of a fetch error.
- Timeout is 3s (Sentinel is on the local Docker network; anything slower
  is a real problem worth surfacing to the operator).
- No `requests` library dependency — uses stdlib `urllib.request` to keep
  the Abigail container's pip footprint unchanged.

---

## Bonus: enrich Sentinel `/health`

Currently `sentinel_server.py` returns `{"ok": True}`. The dashboard wants
`audit_entries` and `chain_length` for the metrics row. Patch:

### File: `governance-spine/sentinel_server.py`

Replace the existing `/health` handler:

```python
@app.route("/health", methods=["GET"])
def health():
    """
    Enriched health response for dashboard metrics.
    Forwards to the Rust spine for chain length when available.
    """
    payload = {"ok": True, "service": "sentinel-overwatch"}
    try:
        resp = requests.get(f"{SPINE_URL}/health", timeout=2)
        if resp.ok:
            spine_data = resp.json()
            payload["chain_length"] = spine_data.get("chain_length", 0)
            payload["audit_entries"] = spine_data.get("audit_entries", 0)
            payload["spine"] = "online"
        else:
            payload["spine"] = "degraded"
    except Exception:
        payload["spine"] = "unreachable"
    return jsonify(payload), 200
```

If the Rust spine doesn't yet expose `chain_length` / `audit_entries` on its
own `/health`, that's fine — the dashboard handles missing fields gracefully
(shows "Recent Events" instead of "Audit Chain Length" with an explanatory
sub-label).

---

## Verification

After Claude Code applies the patch:

```bash
docker compose up --build -d

# Test the proxy
curl http://localhost:7070/api/sentinel-health
# Expected: {"ok": true, "service": "sentinel-overwatch", ...}

# Test fail-soft (stop sentinel, verify graceful response)
docker compose stop sentinel
curl http://localhost:7070/api/sentinel-health
# Expected: {"ok": false, "error": "sentinel_unreachable", ...}
docker compose start sentinel
```

The dashboard should show:
- Sentinel badge: green "Healthy" when up, red "Unavailable" when down
- Firm Health metric: 96% both up, 72% one up, 38% both down
- Refresh status line in header: warning color when service unreachable
