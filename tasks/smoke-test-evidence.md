=== /api/status ===
{"backend":"groq","crsv":0.0,"kill_switch":false,"turns":0,"version":"1.2.0-mode-governed"}

=== /api/sentinel-health ===
{"ok":true,"service":"sentinel-overwatch","audit_entries":0,"chain_length":1}
=== /api/audit-tail?n=5 ===
{"count":3,"entries":[{"data":{"backend":"groq","pid":1,"version":"1.2.0-mode-governed"},"event_type":"SYSTEM_START","ts":"2026-04-27T22:39:51.523730Z"},{"data":{"activated_by":"DASHBOARD-OPERATOR","at":"2026-04-27T20:28:33.586885Z"},"event_type":"KILL_SWITCH_ACTIVATED","ts":"2026-04-27T20:28:33.586893Z"},{"data":{"backend":"groq","pid":1,"version":"1.2.0-mode-governed"},"event_type":"SYSTEM_START","ts":"2026-04-27T20:07:27.643462Z"}],"log_path":"/root/.abigail_audit.jsonl"}

=== POST /api/ebrake ===
{"active":true,"ok":true,"principal":"TEST"}

=== /api/status (after ebrake) ===
{"backend":"groq","crsv":0.0,"kill_switch":true,"turns":0,"version":"1.2.0-mode-governed"}

=== POST /api/ebrake/clear ===
{"active":false,"cleared_by":"TEST-CLEAR","ok":true}

=== POST /api/dept/EXE/kill ===
{"department":"EXE","error":"not_implemented","message":"Department-level kill is scheduled for Sprint 6. Use /api/ebrake for global halt.","ok":false,"sprint":"Sprint 6"}

=== GET / ===
HTTP/1.1 200 OK
Server: Werkzeug/3.1.8 Python/3.11.14
Date: Mon, 27 Apr 2026 22:41:19 GMT
Content-Type: text/html; charset=utf-8
Content-Length: 115
Connection: close

<meta http-equiv="refresh" content="0; url=/dashboard"><p>Redirecting to <a href="/dashboard">/dashboard</a>…</p>