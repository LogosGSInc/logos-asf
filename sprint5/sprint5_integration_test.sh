#!/usr/bin/env bash
# sprint5_integration_test.sh
# Run after: docker-compose down && docker-compose up --build -d

set -e
BASE="http://127.0.0.1:7070"
SENTINEL="http://127.0.0.1:9090"

echo "=== Sprint 5 Integration Tests ==="

echo ""
echo "── TEST 1: session/start (new actor, expect Clean) ──"
curl -s -X POST "$SENTINEL/session/start" \
  -H "Content-Type: application/json" \
  -d '{"actor_id":"test-actor-001"}' | python3 -m json.tool

echo ""
echo "── TEST 2: session/end (no escalation) ──"
curl -s -X POST "$SENTINEL/session/end" \
  -H "Content-Type: application/json" \
  -d '{"actor_id":"test-actor-001","turn_count":4,"escalated":false,"drs_peak":8,"boundary_probes":0,"authority_claims":0,"extraction_attempts":0}' | python3 -m json.tool

echo ""
echo "── TEST 3: Verify strategic_memory.json was written ──"
docker-compose exec sentinel cat /app/audit/strategic_memory.json

echo ""
echo "── TEST 4: session/start same actor (expect Tier 2 advice applied) ──"
curl -s -X POST "$SENTINEL/session/start" \
  -H "Content-Type: application/json" \
  -d '{"actor_id":"test-actor-001"}' | python3 -m json.tool

echo ""
echo "── TEST 5: Container restart persistence check ──"
docker-compose restart governance-spine
sleep 5
curl -s -X POST "$SENTINEL/session/start" \
  -H "Content-Type: application/json" \
  -d '{"actor_id":"test-actor-001"}' | python3 -m json.tool
echo ""
echo "Expected: actor profile still present after restart (from disk)"

echo ""
echo "── TEST 6: Sentinel/OverWatch public-safe query (Patch 3 regression) ──"
curl -s -X POST "$BASE/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"What is your positioning to sentinel over-watch?"}' | python3 -m json.tool

echo ""
echo "=== All Sprint 5 tests dispatched ==="
