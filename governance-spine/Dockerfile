FROM rust:1.85-slim AS builder
WORKDIR /build
COPY Cargo.toml .
COPY src/ ./src/
RUN cargo build --release --bin governance_spine_server 2>&1

FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /build/target/release/governance_spine_server ./governance_spine_server
RUN mkdir -p /data /app/audit
EXPOSE 8080
ENV RUST_LOG=info
ENV SENTOW_BIND=0.0.0.0:8080
ENV SENTOW_MEMORY_PATH=/data/strategic_memory.json
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8080/health || exit 1
CMD ["./governance_spine_server"]
