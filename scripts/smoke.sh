#!/usr/bin/env bash
# Exercise the deployed API the way a student does. Run after every deploy.
#   scripts/smoke.sh [base-url]
# Makes one real /api/query, so it costs one LLM call.
set -euo pipefail

BASE="${1:-https://backend-winter-smoke-307.fly.dev}"
ORIGIN="https://nystateregentsprep.netlify.app"
SID="smoke-$(date +%s)-$RANDOM"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; curl -s -o /dev/null -X POST "$BASE/api/end_session" -H "Content-Type: application/json" -d "{\"session_id\":\"$SID\"}" || true' EXIT

fail() { echo "[smoke] FAIL: $*" >&2; exit 1; }
json() { python3 -c "import json,sys; d=json.load(open('$1')); print($2)"; }

code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/healthz")
[[ "$code" == 200 ]] || fail "/healthz returned $code"

code=$(curl -s -o "$TMP/ready.json" -w "%{http_code}" "$BASE/readyz")
[[ "$code" == 200 ]] || fail "/readyz returned $code: $(cat "$TMP/ready.json")"
echo "[smoke] ready: $(json "$TMP/ready.json" 'd["questions"], "schema", d["schema_version"]')"

curl -s -D "$TMP/q.headers" -o "$TMP/q.json" -X POST "$BASE/api/query" \
  -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d "{\"session_id\":\"$SID\",\"query\":\"Give me 2 Algebra I multiple choice questions\"}"
n=$(json "$TMP/q.json" 'len(d.get("questions", []))')
[[ "$n" -ge 1 ]] || fail "query returned no questions: $(head -c 300 "$TMP/q.json")"
leaked=$(json "$TMP/q.json" '[k for q in d["questions"] for k in ("correct_answer","explanation","rubric") if k in q]')
[[ "$leaked" == "[]" ]] || fail "query leaked $leaked"
grep -qi "^access-control-allow-origin: $ORIGIN" "$TMP/q.headers" || fail "CORS header missing for $ORIGIN"
grep -qi "^x-robots-tag: noindex" "$TMP/q.headers" || fail "X-Robots-Tag missing"
echo "[smoke] query: $n questions, nothing hidden leaked"

QID=$(json "$TMP/q.json" 'd["questions"][0]["id"]')
IMG=$(json "$TMP/q.json" 'd["questions"][0]["question_image_path"]')
curl -s -o "$TMP/c.json" -X POST "$BASE/api/check" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SID\",\"question_id\":$QID,\"answer\":\"1\"}"
json "$TMP/c.json" '"correct" in d and "explanation" in d' | grep -q True || fail "check: $(head -c 300 "$TMP/c.json")"
echo "[smoke] check: graded question $QID"

code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/static/$IMG")
[[ "$code" == 200 ]] || fail "image $IMG returned $code"

code=$(curl -s -o "$TMP/p.pdf" -w "%{http_code}" "$BASE/api/download?ids=$QID")
[[ "$code" == 200 ]] && head -c 4 "$TMP/p.pdf" | grep -q "%PDF" || fail "download returned $code"
echo "[smoke] image and PDF ok"
echo "[smoke] passed"
