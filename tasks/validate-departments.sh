#!/bin/bash
set -e

API_URL="http://localhost:7070/api/chat"

declare -A PROMPTS
PROMPTS["EXE"]="Give me a 7-day execution plan for launching the intake console."
PROMPTS["ENG"]="What's the next backend endpoint I should build and a patch plan?"
PROMPTS["PRD"]="Convert the intake UI requirements into product requirements."
PROMPTS["SEC"]="Threat model the /api/intake submit flow."
PROMPTS["LGL"]="What legal/compliance language do I need before a paid demo?"
PROMPTS["FIN"]="Cost/pricing/margin for a manual pilot at $50K."
PROMPTS["OPS"]="Deployment runbook steps for a pilot client deployment."
PROMPTS["REV"]="Pilot offer structure for a $50K-$150K pilot."
PROMPTS["MKT"]="Landing-page message for the LOGOS Governance Standard."
PROMPTS["HR"]="Operator responsibilities for a 1-person LOGOS deployment."
PROMPTS["DAT"]="What telemetry should be real vs scaffold in the dashboard?"
PROMPTS["GRC"]="Audit/control requirements for SOC 2 readiness."

echo "Starting 12-department validation..."

for dept in EXE ENG PRD SEC LGL FIN OPS REV MKT HR DAT GRC; do
  prompt="${PROMPTS[$dept]}"
  echo "----------------------------------------"
  echo "Testing Department: $dept"
  echo "Prompt: $prompt"
  response=$(curl -s -X POST "$API_URL" -H "Content-Type: application/json" -d "{\"message\": \"As $dept: $prompt\"}")
  
  if echo "$response" | grep -q '"ok":true' || echo "$response" | grep -q '"ok": true'; then
    echo "Result: PASS"
    text=$(echo "$response" | grep -o '"text":"[^"\\]*' | cut -d'"' -f4 | cut -c1-100)
    echo "Snippet: $text..."
  else
    echo "Result: FAIL / BLOCKED"
    echo "Response: $response"
  fi
  sleep 1
done

echo "----------------------------------------"
echo "Fetching latest audit tail (last 12 events) to verify logging..."
curl -s "http://localhost:7070/api/audit-tail?n=12"
echo ""
echo "Validation complete."
