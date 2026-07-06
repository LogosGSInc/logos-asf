/// LOGOS Governance Systems Inc.
/// Sentinel OverWatch HTTP Server
///
/// Endpoints:
///   GET  /health              (unauthenticated; safe status only)
///   POST /inspect             (X-Sentinel-Token required)
///   POST /outbound            (X-Sentinel-Token required)
///   GET  /session/{id}/state  (X-Sentinel-Token required)
///   POST /session/reset       (X-Sentinel-Token required + operator_token)
///   POST /session/start       (X-Sentinel-Token required)
///   POST /session/end         (X-Sentinel-Token required)
///   GET  /audit               (X-Sentinel-Token required)
///
/// SEC-03 DOCK-01B / DOCK-02: every non-/health route requires a constant-time
/// match of the `X-Sentinel-Token` header against `SENTINEL_ADMIN_TOKEN`. If the
/// token is unset the server fails CLOSED (503) on authed routes. `/health` is
/// unauthenticated and returns only `{ok, service}` (no internal counters).

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::Arc;
use std::thread;

use governance_spine::{
    GovernancePipeline,
    EnforcementResult,
    ArbiterConfig,
};
use governance_spine::crypto::constant_time_eq;

fn ok_json(body: &str) -> String {
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nAccess-Control-Allow-Origin: http://localhost:7070\r\nX-Content-Type-Options: nosniff\r\n\r\n{}",
        body.len(), body
    )
}

fn err_json(status: u16, msg: &str) -> String {
    let body = format!("{{\"ok\":false,\"error\":\"{}\"}}", msg.replace('"', "'"));
    format!(
        "HTTP/1.1 {} Error\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
        status, body.len(), body
    )
}

fn parse_json_field(json: &str, key: &str) -> Option<String> {
    let search = format!("\"{}\"", key);
    let pos = json.find(&search)?;
    let after = &json[pos + search.len()..];
    let colon = after.find(':')? + 1;
    let val = after[colon..].trim_start();
    if val.starts_with('"') {
        let inner = &val[1..];
        let end = inner.find('"')?;
        Some(inner[..end].to_string())
    } else {
        let end = val.find(|c: char| c == ',' || c == '}' || c == '\n')
            .unwrap_or(val.len());
        Some(val[..end].trim().to_string())
    }
}

const MAX_BODY_BYTES: usize = 262_144; // 256 KB — prevents OOM on adversarial oversized payloads

/// Read request headers (until the blank line) into a lowercased-key map.
fn read_headers(reader: &mut BufReader<&mut TcpStream>) -> HashMap<String, String> {
    let mut headers = HashMap::new();
    let mut line = String::new();
    loop {
        line.clear();
        if reader.read_line(&mut line).unwrap_or(0) == 0 { break; }
        let t = line.trim();
        if t.is_empty() { break; }
        if let Some(p) = t.find(':') {
            headers.insert(t[..p].trim().to_lowercase(), t[p+1..].trim().to_string());
        }
    }
    headers
}

/// Read the request body using the already-parsed Content-Length header.
fn read_body(reader: &mut BufReader<&mut TcpStream>, headers: &HashMap<String, String>) -> String {
    let len: usize = headers.get("content-length")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0)
        .min(MAX_BODY_BYTES); // enforce ceiling
    let mut body = vec![0u8; len];
    use std::io::Read;
    reader.read_exact(&mut body).unwrap_or(());
    String::from_utf8_lossy(&body).to_string()
}

#[derive(Debug, PartialEq)]
enum AuthResult { Ok, Denied, NotConfigured }

/// SEC-03 route auth: require an exact, constant-time `X-Sentinel-Token` match.
/// Fails closed (`NotConfigured`) when no expected token is configured.
fn authorize(headers: &HashMap<String, String>, expected: &str) -> AuthResult {
    if expected.is_empty() {
        return AuthResult::NotConfigured;
    }
    match headers.get("x-sentinel-token") {
        Some(t) if constant_time_eq(t.as_bytes(), expected.as_bytes()) => AuthResult::Ok,
        _ => AuthResult::Denied,
    }
}

fn verdict_json(result: &EnforcementResult, session_id: &str) -> String {
    match result {
        EnforcementResult::Approved(_) =>
            format!("{{\"ok\":true,\"verdict\":\"APPROVED\",\"session_id\":\"{}\"}}",
                session_id),
        EnforcementResult::Restricted(_, r) =>
            format!("{{\"ok\":true,\"verdict\":\"RESTRICTED\",\"session_id\":\"{}\",\"tool_calls_disabled\":{},\"enhanced_logging\":{}}}",
                session_id, r.tool_calls_disabled, r.enhanced_logging),
        EnforcementResult::Quarantined(msg) =>
            format!("{{\"ok\":false,\"verdict\":\"QUARANTINED\",\"session_id\":\"{}\",\"message\":\"{}\"}}",
                session_id, msg.replace('"', "'")),
        EnforcementResult::HardLocked(msg) =>
            format!("{{\"ok\":false,\"verdict\":\"HARD_LOCKED\",\"session_id\":\"{}\",\"message\":\"{}\"}}",
                session_id, msg.replace('"', "'")),
        EnforcementResult::HaapGated { reason, agency, drs } =>
            format!("{{\"ok\":false,\"verdict\":\"HAAP_GATED\",\"session_id\":\"{}\",\"reason\":\"{}\",\"agency\":\"{}\",\"drs\":{}}}",
                session_id, reason.replace('"', "'"), agency, drs),
    }
}

fn handle(stream: &mut TcpStream, pipeline: &Arc<GovernancePipeline>, token: &str) {
    let mut reader = BufReader::new(stream as &mut TcpStream);
    let mut req = String::new();
    reader.read_line(&mut req).unwrap_or(0);
    let parts: Vec<&str> = req.trim().split_whitespace().collect();
    if parts.len() < 2 { return; }
    let method = parts[0].to_string();
    let path   = parts[1].to_string();

    // Headers must be read before route dispatch so the auth token is available
    // to every route (including bodyless GET routes).
    let headers = read_headers(&mut reader);

    // /health is the only unauthenticated route; all others require the token.
    let is_health = method == "GET" && path == "/health";
    if !is_health {
        match authorize(&headers, token) {
            AuthResult::Ok => {}
            AuthResult::NotConfigured => {
                let r = err_json(503, "sentinel auth not configured");
                let s = reader.get_mut(); let _ = s.write_all(r.as_bytes());
                return;
            }
            AuthResult::Denied => {
                let r = err_json(401, "unauthorized");
                let s = reader.get_mut(); let _ = s.write_all(r.as_bytes());
                return;
            }
        }
    }

    let response = match (method.as_str(), path.as_str()) {

        // SEC-03: safe status only — no audit_entries / chain_length disclosure.
        ("GET", "/health") =>
            ok_json("{\"ok\":true,\"service\":\"sentinel-overwatch\"}"),

        ("POST", "/inspect") => {
            let body       = read_body(&mut reader, &headers);
            let payload    = parse_json_field(&body, "payload").unwrap_or_default();
            let session_id = parse_json_field(&body, "session_id")
                .unwrap_or_else(|| "default".into());
            if payload.is_empty() {
                err_json(400, "payload required")
            } else {
                let r = pipeline.inbound(&payload, &session_id);
                ok_json(&verdict_json(&r, &session_id))
            }
        }

        ("POST", "/outbound") => {
            let body       = read_body(&mut reader, &headers);
            let payload    = parse_json_field(&body, "payload").unwrap_or_default();
            let session_id = parse_json_field(&body, "session_id")
                .unwrap_or_else(|| "default".into());
            if payload.is_empty() {
                err_json(400, "payload required")
            } else {
                let r = pipeline.outbound(&payload, &session_id);
                ok_json(&verdict_json(&r, &session_id))
            }
        }

        ("GET", p) if p.starts_with("/session/") && p.ends_with("/state") => {
            let sid   = p.trim_start_matches("/session/").trim_end_matches("/state");
            let state = pipeline.current_state(sid);
            let drs   = pipeline.session_drs(sid);
            ok_json(&format!(
                "{{\"ok\":true,\"session_id\":\"{}\",\"state\":\"{}\",\"drs\":{}}}",
                sid, state, drs
            ))
        }

        ("POST", "/session/reset") => {
            let body  = read_body(&mut reader, &headers);
            let sid   = parse_json_field(&body, "session_id").unwrap_or_default();
            let op    = parse_json_field(&body, "operator_token").unwrap_or_default();
            // operator_reset now compares op against the configured secret.
            match pipeline.operator_reset(&sid, &op, token) {
                Ok(_)  => ok_json(&format!(
                    "{{\"ok\":true,\"session_id\":\"{}\",\"reset\":true}}", sid)),
                Err(e) => err_json(403, e),
            }
        }

        ("POST", "/session/start") => {
            let body       = read_body(&mut reader, &headers);
            let actor_id   = parse_json_field(&body, "actor_id")
                .unwrap_or_else(|| "anonymous".into());
            let session_id = parse_json_field(&body, "session_id")
                .unwrap_or_else(|| actor_id.clone());

            // Return real session state from pipeline memory (not hardcoded "Clean")
            let state = pipeline.current_state(&session_id);
            let drs   = pipeline.session_drs(&session_id);
            let starting_state = match state {
                governance_spine::arbiter::SecurityState::S1 => "Clean",
                governance_spine::arbiter::SecurityState::S2 => "Watching",
                governance_spine::arbiter::SecurityState::S3 => "Elevated",
                governance_spine::arbiter::SecurityState::S4 => "Locked",
            };

            ok_json(&format!(
                "{{\"ok\":true,\"actor_id\":\"{}\",\"session_id\":\"{}\",\"starting_state\":\"{}\",\"drs\":{},\"threshold_modifier\":{:.2},\"prior_escalations\":{}}}",
                actor_id, session_id, starting_state, drs, 1.0, 0,
            ))
        }

        ("POST", "/session/end") => {
            let body       = read_body(&mut reader, &headers);
            let actor_id   = parse_json_field(&body, "actor_id")
                .unwrap_or_else(|| "anonymous".into());
            let session_id = parse_json_field(&body, "session_id")
                .unwrap_or_else(|| actor_id.clone());
            let escalated  = parse_json_field(&body, "escalated")
                .map(|v| v == "true").unwrap_or(false);
            pipeline.end_session(&session_id, &actor_id);
            ok_json(&format!(
                "{{\"ok\":true,\"actor_id\":\"{}\",\"session_id\":\"{}\",\"persisted\":true,\"escalated\":{}}}",
                actor_id, session_id, escalated
            ))
        }

        ("GET", p) if p.starts_with("/audit") => {
            let entries = pipeline.export_audit_log();
            let last_50: Vec<_> = entries.iter().rev().take(50).collect();
            let items: Vec<String> = last_50.iter().map(|e| format!(
                "{{\"event_id\":\"{}\",\"session_id\":\"{}\",\"source\":\"{}\",\"severity\":\"{}\"}}",
                e.event_id, e.session_id, e.source, e.severity
            )).collect();
            ok_json(&format!("{{\"ok\":true,\"count\":{},\"entries\":[{}]}}",
                items.len(), items.join(",")))
        }

        _ => err_json(404, "not found"),
    };

    let s = reader.get_mut();
    let _ = s.write_all(response.as_bytes());
}

fn serve(listener: TcpListener, pipeline: Arc<GovernancePipeline>, token: Arc<String>) {
    for stream in listener.incoming() {
        if let Ok(mut s) = stream {
            let p = pipeline.clone();
            let tk = token.clone();
            thread::spawn(move || handle(&mut s, &p, &tk));
        }
    }
}

fn main() {
    let addr = std::env::var("SENTOW_BIND")
        .unwrap_or_else(|_| "0.0.0.0:8080".into());
    let industry = std::env::var("SENTOW_INDUSTRY_PROFILE")
        .unwrap_or_else(|_| "consumer".into());
    let arbiter_config = match industry.as_str() {
        "medical" => ArbiterConfig::medical(),
        _         => ArbiterConfig::default(),
    };
    let token = std::env::var("SENTINEL_ADMIN_TOKEN").unwrap_or_default();
    let pipeline = Arc::new(
        GovernancePipeline::new(arbiter_config, None)
            .expect("Pipeline init failed")
    );
    eprintln!("[SENTINEL-SERVER] Listening on http://{}", addr);
    if token.is_empty() {
        eprintln!("[SENTINEL-SERVER] WARNING: SENTINEL_ADMIN_TOKEN unset — authed routes fail closed (503). Only /health is served.");
    } else {
        eprintln!("[SENTINEL-SERVER] Route auth ENABLED — X-Sentinel-Token required on all non-/health routes.");
    }
    eprintln!("[SENTINEL-SERVER] SENTOW_MEMORY_PATH={}",
        std::env::var("SENTOW_MEMORY_PATH").unwrap_or_else(|_| "(in-memory only)".into()));
    let listener = TcpListener::bind(&addr).expect("Failed to bind");
    serve(listener, pipeline, Arc::new(token));
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    use std::time::Duration;

    // ── unit: auth decision ─────────────────────────────────────────────────
    #[test]
    fn authorize_not_configured_when_expected_empty() {
        let h = HashMap::new();
        assert_eq!(authorize(&h, ""), AuthResult::NotConfigured);
    }

    #[test]
    fn authorize_denied_when_missing_or_wrong() {
        let mut h = HashMap::new();
        assert_eq!(authorize(&h, "secret"), AuthResult::Denied);
        h.insert("x-sentinel-token".into(), "wrong".into());
        assert_eq!(authorize(&h, "secret"), AuthResult::Denied);
    }

    #[test]
    fn authorize_ok_on_exact_match() {
        let mut h = HashMap::new();
        h.insert("x-sentinel-token".into(), "secret".into());
        assert_eq!(authorize(&h, "secret"), AuthResult::Ok);
    }

    #[test]
    fn constant_time_eq_semantics() {
        assert!(constant_time_eq(b"abc", b"abc"));
        assert!(!constant_time_eq(b"abc", b"abd"));
        assert!(!constant_time_eq(b"abc", b"abcd")); // length mismatch
        assert!(constant_time_eq(b"", b""));
    }

    // ── integration: real server on an ephemeral port ───────────────────────
    fn spawn_server(token: &str) -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let pipeline = Arc::new(
            GovernancePipeline::new(ArbiterConfig::default(), None).unwrap());
        let tk = Arc::new(token.to_string());
        thread::spawn(move || serve(listener, pipeline, tk));
        thread::sleep(Duration::from_millis(50));
        port
    }

    fn raw(port: u16, request: &str) -> (u16, String) {
        let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
        s.write_all(request.as_bytes()).unwrap();
        let mut buf = String::new();
        s.read_to_string(&mut buf).unwrap();
        let code = buf.lines().next()
            .and_then(|l| l.split_whitespace().nth(1))
            .and_then(|c| c.parse().ok())
            .unwrap_or(0);
        let body = buf.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
        (code, body)
    }

    fn post(port: u16, path: &str, extra_headers: &str, body: &str) -> (u16, String) {
        let req = format!(
            "POST {} HTTP/1.1\r\nHost: x\r\n{}Content-Length: {}\r\n\r\n{}",
            path, extra_headers, body.len(), body);
        raw(port, &req)
    }

    #[test]
    fn health_is_unauthenticated_and_trimmed() {
        let port = spawn_server("secret");
        let (code, body) = raw(port, "GET /health HTTP/1.1\r\nHost: x\r\n\r\n");
        assert_eq!(code, 200);
        assert!(body.contains("sentinel-overwatch"));
        assert!(!body.contains("chain_length"));
        assert!(!body.contains("audit_entries"));
    }

    #[test]
    fn inspect_denied_without_token() {
        let port = spawn_server("secret");
        let (code, _) = post(port, "/inspect", "",
            "{\"payload\":\"hi\",\"session_id\":\"s\"}");
        assert_eq!(code, 401);
    }

    #[test]
    fn inspect_denied_with_wrong_token() {
        let port = spawn_server("secret");
        let (code, _) = post(port, "/inspect", "X-Sentinel-Token: nope\r\n",
            "{\"payload\":\"hi\",\"session_id\":\"s\"}");
        assert_eq!(code, 401);
    }

    #[test]
    fn inspect_ok_with_correct_token() {
        let port = spawn_server("secret");
        let (code, resp) = post(port, "/inspect", "X-Sentinel-Token: secret\r\n",
            "{\"payload\":\"hello\",\"session_id\":\"s\"}");
        assert_eq!(code, 200);
        assert!(resp.contains("verdict"));
    }

    #[test]
    fn audit_fails_closed_when_token_not_configured() {
        let port = spawn_server(""); // no SENTINEL_ADMIN_TOKEN
        let (code, _) = raw(port, "GET /audit HTTP/1.1\r\nHost: x\r\n\r\n");
        assert_eq!(code, 503);
    }

    #[test]
    fn audit_denied_without_token_when_configured() {
        let port = spawn_server("secret");
        let (code, _) = raw(port, "GET /audit HTTP/1.1\r\nHost: x\r\n\r\n");
        assert_eq!(code, 401);
    }
}
