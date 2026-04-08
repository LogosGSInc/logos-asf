#!/usr/bin/env sh
set -eu

# Load .abigail.env if mounted (contains API keys)
if [ -f /app/.abigail.env ]; then
  cp /app/.abigail.env "$HOME/.abigail.env"
  chmod 600 "$HOME/.abigail.env"
fi

# Ensure audit log directory exists with correct permissions
mkdir -p "$HOME"
mkdir -p /app/logs
touch /app/logs/abigail_audit.jsonl
chmod 600 /app/logs/abigail_audit.jsonl

# Symlink audit log to home for compatibility with abigail_hardened_enhanced.py
ln -sf /app/logs/abigail_audit.jsonl "$HOME/.abigail_audit.jsonl" 2>/dev/null || true

exec "$@"
