#!/usr/bin/env bash
# Smoke test of a running release through its Service: probes, one answered question with
# citations, one invalid request and the metrics. Expects the fake generator.
# Usage: tests/smoke-test.sh
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib.sh"
need kubectl curl python3
PORT=18081
BASE="http://127.0.0.1:${PORT}"

kc -n rail port-forward svc/rail-rag-api "${PORT}:80" >/dev/null 2>&1 &
pf=$!
body="$(mktemp)"
trap 'kill $pf 2>/dev/null || true; rm -f "$body"' EXIT
for _ in $(seq 1 30); do curl -sf "$BASE/livez" >/dev/null && break; sleep 1; done

for path in livez readyz startupz; do
  curl -sf --max-time 5 "$BASE/$path" >/dev/null || die "/$path failed"
  log "PASS /$path"
done

ask() { # ask <json body>: prints the HTTP status, leaves the answer in $body
  curl -s -o "$body" -w '%{http_code}' --max-time 30 -H 'Content-Type: application/json' \
    -d "$1" "$BASE/ask"
}

code="$(ask '{"question":"How many wheelchair spaces must a unit longer than 205 metres have?"}')"
[ "$code" = 200 ] || { cat "$body"; die "/ask returned ${code}"; }
python3 - "$body" <<'PY' || die "/ask answer is not as expected"
import json, sys
a = json.load(open(sys.argv[1]))
print(json.dumps(a)[:600])
assert not a["refused"] and a["answer"] and a["citations"], "expected an answer with citations"
PY
log "PASS /ask answers with citations"

code="$(ask '{"question":""}')"
[ "$code" = 422 ] || die "an empty question returned ${code}, expected 422"
log "PASS /ask rejects an empty question"

metrics="$(curl -sf --max-time 5 "$BASE/metrics")"
grep -q '^rail_ready 1' <<<"$metrics" || die "rail_ready is not 1"
grep -q '^rail_http_requests_total{.*route="/ask"' <<<"$metrics" || die "no /ask request in the metrics"
log "PASS /metrics"
