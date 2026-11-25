#!/usr/bin/env bash
# Benchmarks behind the README numbers. Each scenario runs N times from the same starting state.
# Usage: scripts/bench.sh <capacity|hpa|keda|all> [runs]      default runs: 3
#   capacity  one api pod, autoscaling off, load stepped 1 -> 8 VUs: where a pod saturates
#   hpa       autoscaling on CPU only: low load, a burst, then low again
#   keda      the same load with KEDA on CPU and requests in flight per pod
# Results: results/raw/<scenario>-r<n>.{k6,prom,host}.json, summaries in results/raw/bench.log.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need helm kubectl
SCENARIO="${1:?scenario: capacity, hpa, keda or all}"
RUNS="${2:-3}"
[[ "$SCENARIO" =~ ^(capacity|hpa|keda|all)$ ]] || die "unknown scenario: $SCENARIO"
[[ "$RUNS" =~ ^[1-9][0-9]?$ ]] || die "runs must be 1-99"
CHART="$REPO_ROOT/charts/rail-rag"
LOG="$REPO_ROOT/results/raw/bench.log"
mkdir -p "$(dirname "$LOG")"

# 75 s holds, so each plateau outlasts the 1-minute rate windows.
CAPACITY_STAGES='[{"duration":"15s","target":1},{"duration":"75s","target":1},{"duration":"10s","target":2},{"duration":"75s","target":2},{"duration":"10s","target":4},{"duration":"75s","target":4},{"duration":"10s","target":6},{"duration":"75s","target":6},{"duration":"10s","target":8},{"duration":"75s","target":8},{"duration":"10s","target":0}]'
# Low, a 4-minute burst, then low for long enough to watch the scale-down (120 s window + 60 s/pod).
SCALE_STAGES='[{"duration":"30s","target":2},{"duration":"90s","target":2},{"duration":"30s","target":10},{"duration":"240s","target":10},{"duration":"30s","target":2},{"duration":"330s","target":2},{"duration":"10s","target":0}]'

deploy() { # deploy <helm --set args...>; replicas through Helm only (kubectl scale conflicts with SSA)
  helm upgrade --install rail-rag "$CHART" --kube-context "$KUBE_CONTEXT" -n rail --create-namespace \
    -f "$CHART/values-dev.yaml" -f "$CHART/values-bench.yaml" "$@" \
    --force-conflicts --wait --timeout 20m >/dev/null
}

wait_replicas() { # wait_replicas <n>: desired and ready both n, so every run starts the same way
  local want="$1" i spec ready
  for ((i = 0; i < 120; i++)); do
    spec="$(kc -n rail get deploy rail-rag-api -o jsonpath='{.spec.replicas}')"
    ready="$(kc -n rail get deploy rail-rag-api -o jsonpath='{.status.readyReplicas}')"
    [ "$spec" = "$want" ] && [ "${ready:-0}" = "$want" ] && return 0
    sleep 5
  done
  die "api did not settle at ${want} replicas (desired ${spec}, ready ${ready:-0})"
}

run_n() { # run_n <name> <stages> <replicas to settle at between runs>
  local name="$1" stages="$2" settle="$3" r
  for ((r = 1; r <= RUNS; r++)); do
    wait_replicas "$settle"
    log "${name} run ${r}/${RUNS}"
    "$REPO_ROOT/scripts/k6-run.sh" "${name}-r${r}" "$stages" | tee -a "$LOG"
  done
}

if [[ "$SCENARIO" =~ ^(capacity|all)$ ]]; then
  log "capacity: one pod, autoscaling off"
  deploy --set api.autoscaling.enabled=false --set api.replicas=1
  run_n capacity "$CAPACITY_STAGES" 1
fi
if [[ "$SCENARIO" =~ ^(hpa|all)$ ]]; then
  log "hpa: CPU only"
  deploy --set api.autoscaling.enabled=true --set api.autoscaling.mode=hpa
  run_n hpa "$SCALE_STAGES" 1
  kc -n rail describe hpa rail-rag-api > "$REPO_ROOT/results/raw/hpa-describe.txt" 2>&1 || true
fi
if [[ "$SCENARIO" =~ ^(keda|all)$ ]]; then
  log "keda: CPU and requests in flight per pod"
  deploy --set api.autoscaling.enabled=true --set api.autoscaling.mode=keda
  run_n keda "$SCALE_STAGES" 1
  kc -n rail describe hpa keda-hpa-rail-rag-api > "$REPO_ROOT/results/raw/keda-hpa-describe.txt" 2>&1 || true
  kc -n rail describe scaledobject rail-rag-api >> "$REPO_ROOT/results/raw/keda-hpa-describe.txt" 2>&1 || true
fi
log "bench done: $(grep -c '^run:' "$LOG") run summaries in ${LOG}"
