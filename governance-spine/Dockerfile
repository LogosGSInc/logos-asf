# LOGOS ASF — Sentinel OverWatch Governance Spine
# Multi-stage build: compile Rust → minimal runtime image
# Exposes HTTP API on port 8080 for pipeline evaluation

FROM rust:1.82-slim AS builder

WORKDIR /build
COPY Cargo.toml .
COPY src/ ./src/

# Cache deps layer separately
RUN cargo build --release 2>&1

# ── Runtime stage ──────────────────────────────────────────────────────────
FROM debian:bookworm-slim AS runtime

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /build/target/release/governance_spine_demo ./governance_spine_demo

# Audit volume mount point
RUN mkdir -p /app/audit

# Simple HTTP wrapper around the governance spine library
# The demo binary validates the pipe is working — the actual HTTP
# service binary (governance_spine_server) is added in next sprint
# For now: health check passes if binary runs without error
COPY sentinel_server.py ./sentinel_server.py
RUN apt-get update && apt-get install -y python3 python3-pip \
    && pip3 install flask --break-system-packages \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8080

ENV RUST_LOG=info

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["python3", "sentinel_server.py"]
