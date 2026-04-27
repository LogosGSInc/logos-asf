#!/bin/sh
set -eu

echo "[ABIGAIL-ENTRYPOINT] starting"

mkdir -p /root

if [ -n "${GROQ_API_KEY:-}" ]; then
  echo "[ABIGAIL-ENTRYPOINT] GROQ_API_KEY found in container environment"
else
  echo "[ABIGAIL-ENTRYPOINT] GROQ_API_KEY missing from container environment"
fi

cat > /root/.abigail.env <<EOF
GROQ_API_KEY=${GROQ_API_KEY:-}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
ABIGAIL_ADMIN_TOKEN=${ABIGAIL_ADMIN_TOKEN:-}
ABIGAIL_DEMO_TOKEN=${ABIGAIL_DEMO_TOKEN:-}
DEFAULT_MODEL=${DEFAULT_MODEL:-llama-3.1-70b-versatile}
SENTINEL_URL=${SENTINEL_URL:-http://sentinel:8080}
ABIGAIL_HEADLESS=${ABIGAIL_HEADLESS:-1}
EOF

chmod 600 /root/.abigail.env || true

if grep -q '^GROQ_API_KEY=.' /root/.abigail.env; then
  echo "[ABIGAIL-ENTRYPOINT] /root/.abigail.env created with GROQ_API_KEY present"
else
  echo "[ABIGAIL-ENTRYPOINT] /root/.abigail.env created but GROQ_API_KEY is empty"
fi

exec "$@"
