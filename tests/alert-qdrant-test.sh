#!/usr/bin/env bash
# Takes Qdrant down and checks what DESIGN D5 promises, then brings it back:
#   1. the api pods stay Ready (readiness ignores Qdrant)
#   2. /ask answers 503 quickly, not a hang or a 500
#   3. the RailQdrantDown alert fires in Prometheus
#   4. after Qdrant returns, /ask works again and the alert clears
# Usage: tests/alert-qdrant-test.sh [release] [namespace]      Takes about 5 minutes.
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib.sh"
need kubectl curl python3
REL="${1:-rail-rag}"
NS="${2:-rail}"
failed=0
pids=()

cleanup() {
  kc -n "$NS" scale statefulset "${REL}-qdrant" --replicas=1 >/dev/null 2>&1 || true
  [ "${#pids[@]}" -eq 0 ] || kill "${pids[@]}" 2>/dev/null || true
}
trap cleanup EXIT

check() { # check <description> <command...>
  local what="$1"; shift
  if "$@"; then printf '  PASS  %s\n' "$what"; else printf '  FAIL  %s\n' "$what"; failed=1; fi
}
wait_for() { # wait_for <seconds> <command...>
  local limit="$1" i; shift
  for ((i = 0; i < limit; i += 3)); do "$@" && return 0; sleep 3; done
  return 1
}
ask_status() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H 'content-type: application/json' \
    -d '{"question":"What are the requirements for wheelchair spaces?"}' localhost:18090/ask
}
alert_state() { # prints firing, pending or none
  curl -s localhost:19091/api/v1/alerts | python3 -c "
import sys, json
a = [x for x in json.load(sys.stdin)['data']['alerts'] if x['labels']['alertname'] == 'RailQdrantDown']
print(a[0]['state'] if a else 'none')"
}
# These re-evaluate on every call, so wait_for sees changes (a $(...) argument would be fixed once).
alert_is() { [ "$(alert_state)" = "$1" ]; }
ask_is() { [ "$(ask_status)" = "$1" ]; }
qdrant_pod_gone() { ! kc -n "$NS" get pod "${REL}-qdrant-0" >/dev/null 2>&1; }
api_ready_count() {
  kc -n "$NS" get deploy "${REL}-api" -o jsonpath='{.status.readyReplicas}'
}

kc -n "$NS" port-forward "svc/${REL}-api" 18090:80 >/dev/null 2>&1 & pids+=($!)
kc -n monitoring port-forward svc/kps-prometheus 19091:9090 >/dev/null 2>&1 & pids+=($!)
wait_for 30 curl -sf localhost:18090/livez >/dev/null || die "cannot reach the api"
wait_for 30 curl -sf localhost:19091/-/ready >/dev/null || die "cannot reach Prometheus"
check "baseline: /ask returns 200" test "$(ask_status)" = 200
check "baseline: no RailQdrantDown alert" alert_is none

log "scaling Qdrant to 0"
kc -n "$NS" scale statefulset "${REL}-qdrant" --replicas=0 >/dev/null
wait_for 60 qdrant_pod_gone || die "Qdrant pod did not go away"

start=$SECONDS
code="$(ask_status)"
elapsed=$((SECONDS - start))
check "Qdrant down: /ask answers 503 (got ${code})" test "$code" = 503
check "Qdrant down: the 503 came back within 5 s (took ${elapsed} s)" test "$elapsed" -lt 5
sleep 15
check "Qdrant down: api pods still Ready ($(api_ready_count))" test "$(api_ready_count)" -ge 1

log "waiting for RailQdrantDown to fire (rule has for: 1m)"
fired_at=$SECONDS
check "RailQdrantDown fires" wait_for 240 alert_is firing
log "alert took $((SECONDS - fired_at)) s to fire"

log "restoring Qdrant"
kc -n "$NS" scale statefulset "${REL}-qdrant" --replicas=1 >/dev/null
kc -n "$NS" rollout status "statefulset/${REL}-qdrant" --timeout=180s >/dev/null
check "Qdrant back: /ask returns 200" wait_for 60 ask_is 200
check "Qdrant back: alert clears" wait_for 180 alert_is none

[ "$failed" -eq 0 ] || die "alert test failed"
log "alert test passed"
