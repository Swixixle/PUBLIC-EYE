#!/bin/bash
# Frame end-to-end test script
# Tests every live endpoint against the deployment (default: production).
# Usage: bash scripts/e2e-test.sh [base_url]
# Default base_url: https://frame-2yxu.onrender.com
#
# Expect 15 PASS when the deployed API matches main (routes + signing pipeline).
# If many tests fail with 404 or signing errors, redeploy Render with latest build
# (npm run build, pip install, FRAME_REPO_ROOT) or run: npm run e2e:local against local uvicorn.

BASE_URL="${1:-https://frame-2yxu.onrender.com}"
PASS=0
FAIL=0
FAILURES=()

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

check() {
  local name="$1"
  local result="$2"
  local expect="$3"

  if echo "$result" | grep -q "$expect"; then
    echo -e "${GREEN}PASS${NC} $name"
    PASS=$((PASS + 1))
  else
    echo -e "${RED}FAIL${NC} $name"
    echo "  Expected to find: $expect"
    echo "  Got: ${result:0:200}"
    FAIL=$((FAIL + 1))
    FAILURES+=("$name")
  fi
}

echo ""
echo "Frame E2E Test"
echo "Base URL: $BASE_URL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Health check
result=$(curl -s "$BASE_URL/health")
check "GET /health" "$result" '"ok"'

# 2. Demo page loads
result=$(curl -s "$BASE_URL/demo")
check "GET /demo" "$result" "Frame"

# 3. Pitch page loads
result=$(curl -s "$BASE_URL/pitch")
check "GET /pitch" "$result" "Frame"

# 4. FEC name search
result=$(curl -s "$BASE_URL/v1/fec-search?name=Ted%20Cruz")
check "GET /v1/fec-search" "$result" "S2TX00312"

# 5. FEC receipt — signed
result=$(curl -s -X POST "$BASE_URL/v1/generate-receipt" \
  -H "Content-Type: application/json" \
  -d '{"candidateId": "S2TX00312"}')
check "POST /v1/generate-receipt (signed)" "$result" '"signature"'

# 6. FEC receipt has unknowns
check "POST /v1/generate-receipt (unknowns)" "$result" '"unknowns"'

# 7. Verify the FEC receipt
receipt=$(curl -s -X POST "$BASE_URL/v1/generate-receipt" \
  -H "Content-Type: application/json" \
  -d '{"candidateId": "S2TX00312"}')
verify_result=$(echo "$receipt" | curl -s -X POST "$BASE_URL/v1/verify-receipt" \
  -H "Content-Type: application/json" \
  -d @-)
check "POST /v1/verify-receipt" "$verify_result" '"ok"'

# 8. Lobbying receipt
result=$(curl -s -X POST "$BASE_URL/v1/generate-lobbying-receipt" \
  -H "Content-Type: application/json" \
  -d '{"name": "Exxon"}')
check "POST /v1/generate-lobbying-receipt" "$result" '"signature"'

# 9. 990 receipt
result=$(curl -s -X POST "$BASE_URL/v1/generate-990-receipt" \
  -H "Content-Type: application/json" \
  -d '{"orgName": "Gates Foundation", "ein": "562618866"}')
check "POST /v1/generate-990-receipt" "$result" '"signature"'

# 10. Wikidata receipt
result=$(curl -s -X POST "$BASE_URL/v1/generate-wikidata-receipt" \
  -H "Content-Type: application/json" \
  -d '{"personName": "Tucker Carlson"}')
check "POST /v1/generate-wikidata-receipt" "$result" '"signature"'

# 11. Ad Library receipt (should work even without token — returns partial receipt)
result=$(curl -s -X POST "$BASE_URL/v1/generate-ad-library-receipt" \
  -H "Content-Type: application/json" \
  -d '{"name": "Ted Cruz", "country": "US"}')
check "POST /v1/generate-ad-library-receipt" "$result" '"signature"'

# 12. Async job — submit returns job_id immediately
result=$(curl -s -X POST "$BASE_URL/v1/jobs" \
  -H "Content-Type: application/json" \
  -d '{"receipt_type": "fec", "name": "Ted Cruz"}')
check "POST /v1/jobs (returns job_id)" "$result" '"job_id"'

# 13. Async job — unknown id returns 404
result=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/v1/jobs/job_doesnotexist00000")
check "GET /v1/jobs/nonexistent (404)" "$result" "404"

# 14. Schema baselines endpoint
result=$(curl -s "$BASE_URL/v1/schema-baselines")
check "GET /v1/schema-baselines" "$result" '"baselines"'

# 15. Poll FEC job to completion (wait up to 60s)
echo ""
echo -e "${YELLOW}Polling FEC job to completion (max 60s)...${NC}"
job_submit=$(curl -s -X POST "$BASE_URL/v1/jobs" \
  -H "Content-Type: application/json" \
  -d '{"receipt_type": "fec", "name": "Ted Cruz"}')
job_id=$(echo "$job_submit" | python3 -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))" 2>/dev/null)

if [ -n "$job_id" ]; then
  for i in $(seq 1 20); do
    sleep 3
    poll=$(curl -s "$BASE_URL/v1/jobs/$job_id")
    status=$(echo "$poll" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
    if [ "$status" = "complete" ]; then
      check "FEC job completes with receipt" "$poll" '"signature"'
      break
    elif [ "$status" = "failed" ]; then
      echo -e "${RED}FAIL${NC} FEC job failed: $poll"
      FAIL=$((FAIL + 1))
      FAILURES+=("FEC job completion")
      break
    fi
    if [ $i -eq 20 ]; then
      echo -e "${RED}FAIL${NC} FEC job did not complete within 60s"
      FAIL=$((FAIL + 1))
      FAILURES+=("FEC job timeout")
    fi
  done
else
  echo -e "${RED}FAIL${NC} Could not extract job_id for polling test"
  FAIL=$((FAIL + 1))
  FAILURES+=("FEC job id extraction")
fi

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "Results: ${GREEN}${PASS} passed${NC} / ${RED}${FAIL} failed${NC}"

if [ ${#FAILURES[@]} -gt 0 ]; then
  echo ""
  echo "Failed tests:"
  for f in "${FAILURES[@]}"; do
    echo -e "  ${RED}✗${NC} $f"
  done
  exit 1
else
  echo -e "${GREEN}All tests passed.${NC}"
  exit 0
fi
