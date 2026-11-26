#!/usr/bin/env bash
# goldpass quality gate against the api in the kind cluster, with the REAL generator: shows the
# Kubernetes deployment did not change how the assistant answers. Run by hand, never in CI.
# It switches the release to Gemini, asks the 20 golden questions (about 5 minutes, at most 60
# generator calls of your own quota) and switches back to the fake generator.
# Needs a running release and a Secret you create yourself, from your own .env:
#   kubectl --context kind-rail-k8s -n rail create secret generic rail-rag-secrets \
#     --from-env-file=<file with only the GEMINI_API_KEY=... line>
# This script only checks that the Secret exists; it never reads its value.
# Usage: scripts/quality-gate.sh [extra helm args]
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need kubectl helm uvx curl
# The goldpass commit the golden set and thresholds in eval/ were copied from.
GOLDPASS="git+https://github.com/cardohso/goldpass@b10c0a923a6f8d8a8b2edad8b363d31be47f872a"
CHART="$REPO_ROOT/charts/rail-rag"

kc -n rail get secret rail-rag-secrets >/dev/null 2>&1 ||
  die "Secret rail-rag-secrets not found in namespace rail: create it first (see the top of this script)"

set_provider() { # set_provider <fake|gemini> [extra helm args]
  local provider="$1"; shift
  helm upgrade rail-rag "$CHART" --kube-context "$KUBE_CONTEXT" -n rail --reuse-values \
    --set generator.provider="$provider" "$@" --force-conflicts --wait --timeout 10m >/dev/null
}

pf=""
restore() {
  [ -z "$pf" ] || kill "$pf" 2>/dev/null || true
  log "switching back to the fake generator"
  set_provider fake || log "restore failed: run 'make deploy' to return to the fake generator"
}
trap restore EXIT

log "switching the release to the real generator"
set_provider gemini "$@"
kc -n rail rollout status deploy/rail-rag-api --timeout=600s >/dev/null
kc -n rail port-forward svc/rail-rag-api 18080:80 >/dev/null 2>&1 &
pf=$!
for _ in $(seq 1 30); do curl -sf localhost:18080/readyz >/dev/null && break; sleep 1; done
curl -sf localhost:18080/readyz >/dev/null || die "api not reachable on localhost:18080"

mkdir -p "$REPO_ROOT/results"
log "running goldpass (about 5 minutes)"
(cd "$REPO_ROOT/eval" && uvx --from "$GOLDPASS" goldpass run --config goldpass.yaml)
