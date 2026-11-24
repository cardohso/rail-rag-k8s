#!/usr/bin/env bash
# Proves the NetworkPolicies are enforced, not just accepted by the API server (docs/DESIGN.md, D9).
# Every "must be blocked" check has a control that must succeed, so a block cannot be a broken test.
# Usage: tests/netpol-test.sh [release] [namespace]
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib.sh"
need kubectl

REL="${1:-rail-rag}"
NS="${2:-rail}"
# Unique per run, so back-to-back runs never collide with pods still terminating.
RUN="$$"
OTHER_NS="netpol-other-${RUN}"
INTRUDER="intruder-${RUN}"
VICTIM="victim-${RUN}"
OUTSIDER="outsider-${RUN}"
IMG="${TEST_IMAGE:-python:3.12-slim}"
QDRANT="http://${REL}-qdrant.${NS}.svc:6333/readyz"
API="http://${REL}-api.${NS}.svc:80/livez"
failures=0

cleanup() {
  kc -n "$NS" delete pod "$INTRUDER" "$VICTIM" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kc delete namespace "$OTHER_NS" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

# probe <namespace> <pod> <url> [container args]: exit 0 if the URL answers within 3 s.
probe() {
  local ns="$1" pod="$2" url="$3"; shift 3
  kc -n "$ns" exec "$pod" "$@" -- python -c \
    'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=3)' "$url" >/dev/null 2>&1
}

expect() { # expect <allow|block> <description> <namespace> <pod> <url> [kubectl exec args]
  local want="$1" desc="$2"; shift 2
  local got=block
  probe "$@" && got=allow
  if [ "$got" = "$want" ]; then
    printf '  PASS  %-5s %s\n' "$want" "$desc"
  else
    printf '  FAIL  wanted %s, got %s: %s\n' "$want" "$got" "$desc"; failures=$((failures + 1))
  fi
}

log "creating test pods"
kc create namespace "$OTHER_NS" >/dev/null
kc -n "$NS" run "$INTRUDER" --image="$IMG" --restart=Never --command -- sleep 600 >/dev/null
kc -n "$NS" run "$VICTIM" --image="$IMG" --restart=Never --port=8000 --command -- python -m http.server 8000 >/dev/null
kc -n "$OTHER_NS" run "$OUTSIDER" --image="$IMG" --restart=Never --command -- sleep 600 >/dev/null
kc -n "$NS" wait --for=condition=Ready pod/"$INTRUDER" pod/"$VICTIM" --timeout=120s >/dev/null
kc -n "$OTHER_NS" wait --for=condition=Ready pod/"$OUTSIDER" --timeout=120s >/dev/null
VICTIM_IP="$(kc -n "$NS" get pod "$VICTIM" -o jsonpath='{.status.podIP}')"
# A pod that is being deleted (right after a rollout) cannot exec, which would look like a block.
API_POD="$(kc -n "$NS" get pod -l "app.kubernetes.io/instance=${REL},app.kubernetes.io/component=api" \
  -o custom-columns=NAME:.metadata.name,DELETING:.metadata.deletionTimestamp --no-headers \
  | awk '$2 == "<none>" { print $1; exit }')"
[ -n "$API_POD" ] || die "no running api pod in ${NS}"

log "qdrant: only api and index may connect"
expect allow "control: unlabelled pod reaches another unlabelled pod" "$NS" "$INTRUDER" "http://${VICTIM_IP}:8000/"
expect block "unlabelled pod -> qdrant"                               "$NS" "$INTRUDER" "$QDRANT"
expect block "pod in another namespace -> qdrant"                      "$OTHER_NS" "$OUTSIDER" "$QDRANT"
expect allow "api pod -> qdrant"                                       "$NS" "$API_POD" "$QDRANT" -c api

log "api: egress is limited to qdrant, DNS and (if enabled) public HTTPS"
expect block "api pod -> unrelated pod in the namespace"               "$NS" "$API_POD" "http://${VICTIM_IP}:8000/" -c api

log "api: ingress from this namespace and the allow-listed namespaces only"
expect allow "control: pod in the same namespace -> api"               "$NS" "$INTRUDER" "$API"
expect block "pod in another namespace -> api"                         "$OTHER_NS" "$OUTSIDER" "$API"

echo
if [ "$failures" -eq 0 ]; then log "all NetworkPolicy checks passed"; else die "$failures check(s) failed"; fi
