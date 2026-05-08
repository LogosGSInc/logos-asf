/// LOGOS Governance Systems Inc.
/// Sentinel OverWatch HTTP Server
///
/// Endpoints:
///   GET  /health
///   POST /inspect
///   POST /outbound
///   GET  /session/{id}/state
///   POST /session/reset
///   POST /session/start
///   POST /session/end
///   GET  /audit

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

fn read_body(reader: &mut BufReader<&mut TcpStream>) -> String {
    let mut headers = HashMap::new();
    let mut line = String::new();
    loop {
        line.clear();
        reader.read_line(&mut line).unwrap_or(0);
        let t = line.trim();
        if t.is_empty() { break; }
        if let Some(p) = t.find(':') {
            headers.insert(t[..p].trim().to_lowercase(), t[p+1..].trim().to_string());
        }
    }
    let len: usize = headers.get("content-length")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0)
        .min(MAX_BODY_BYTES); // enforce ceiling
    let mut body = vec![0u8; len];
    use std::io::Read;
    reader.read_exact(&mut body).unwrap_or(());
    String::from_utf8_lossy(&body).to_string()
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

fn handle(stream: &mut TcpStream, pipeline: &Arc<GovernancePipeline>) {
    let mut reader = BufReader::new(stream as &mut TcpStream);
    let mut req = String::new();
    reader.read_line(&mut req).unwrap_or(0);
    let parts: Vec<&str> = req.trim().split_whitespace().collect();
    if parts.len() < 2 { return; }
    let method = parts[0];
    let path   = parts[1];

    let response = match (method, path) {

        ("GET", "/health") => ok_json(&format!(
            "{{\"ok\":true,\"service\":\"sentinel-overwatch\",\"audit_entries\":{},\"chain_length\":{}}}",
            pipeline.audit_entry_count(), pipeline.chain_length()
        )),

        ("POST", "/inspect") => {
            let body       = read_body(&mut reader);
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
            let body       = read_body(&mut reader);
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
            let body  = read_body(&mut reader);
            let sid   = parse_json_field(&body, "session_id").unwrap_or_default();
            let token = parse_json_field(&body, "operator_token").unwrap_or_default();
            match pipeline.operator_reset(&sid, &token) {
                Ok(_)  => ok_json(&format!(
                    "{{\"ok\":true,\"session_id\":\"{}\",\"reset\":true}}", sid)),
                Err(e) => err_json(403, e),
            }
        }

        ("POST", "/session/start") => {
            let body       = read_body(&mut reader);
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
            let body       = read_body(&mut reader);
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

fn main() {
    let addr = std::env::var("SENTOW_BIND")
        .unwrap_or_else(|_| "0.0.0.0:8080".into());
    let industry = std::env::var("SENTOW_INDUSTRY_PROFILE")
        .unwrap_or_else(|_| "consumer".into());
    let arbiter_config = match industry.as_str() {
        "medical" => ArbiterConfig::medical(),
        _         => ArbiterConfig::default(),
    };
    let pipeline = Arc::new(
        GovernancePipeline::new(arbiter_config, None)
            .expect("Pipeline init failed")
    );
    eprintln!("[SENTINEL-SERVER] Listening on http://{}", addr);
    eprintln!("[SENTINEL-SERVER] SENTOW_MEMORY_PATH={}",
        std::env::var("SENTOW_MEMORY_PATH").unwrap_or_else(|_| "(in-memory only)".into()));
    let listener = TcpListener::bind(&addr).expect("Failed to bind");
    for stream in listener.incoming() {
        if let Ok(mut s) = stream {
            let p = pipeline.clone();
            thread::spawn(move || handle(&mut s, &p));
        }
    }
}
