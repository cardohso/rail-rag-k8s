#!/usr/bin/env bash
# Failure tests under steady load: does the api keep answering while pods go away?
# Usage: scripts/chaos.sh <kill|crash|rollout|drain|all> [runs]      default runs: 3
#   kill     delete one api pod (graceful: preStop, SIGTERM, in-flight requests drain)
#   crash    SIGKILL one api container through the node's container runtime (no warning)
#   rollout  rolling restart of the api Deployment (maxSurge 1, maxUnavailable 0)
#   drain    drain the worker without Qdrant, as for node maintenance (honours the PDB)
# Each run: 3 api pods, 16 VUs for 5 minutes, the fault 90 s after k6 starts.
# Results: results/raw/chaos-<scenario>-r<n>.{k6,prom,chaos}.json, summaries in results/raw/chaos.log.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need helm kubectl docker jq
SCENARIO="${1:?scenario: kill, crash, rollout, drain or all}"
RUNS="${2:-3}"
[[ "$SCENARIO" =~ ^(kill|crash|rollout|drain|all)$ ]] || die "unknown scenario: $SCENARIO"
[[ "$RUNS" =~ ^[1-9][0-9]?$ ]] || die "runs must be 1-99"
CHART="$REPO_ROOT/charts/rail-rag"
OUT="$REPO_ROOT/results/raw"
LOG="$OUT/chaos.log"
REPLICAS=3
FAULT_AFTER=90
# 16 VUs is about 8.4 requests/s: 2.8 per pod with 3 pods and 4.2 with 2, both well under the
# 14.5 one pod can serve (D17), so a failure here is the fault's doing, not overload.
STAGES='[{"duration":"30s","target":16},{"duration":"300s","target":16},{"duration":"10s","target":0}]'
mkdir -p "$OUT"

helm upgrade --install rail-rag "$CHART" --kube-context "$KUBE_CONTEXT" -n rail --create-namespace \
  -f "$CHART/values-dev.yaml" -f "$CHART/values-bench.yaml" \
  --set api.autoscaling.enabled=false --set api.replicas="$REPLICAS" \
  --force-conflicts --wait --timeout 20m >/dev/null

api_pods() { # running, not terminating: name and node
  kc -n rail get pods -l app.kubernetes.io/component=api -o json |
    jq -r '.items[] | select(.metadata.deletionTimestamp == null and .status.phase == "Running")
           | "\(.metadata.name) \(.spec.nodeName)"'
}

settled() { # all replicas ready and up to date, and no api pod terminating
  local d
  d="$(kc -n rail get deploy rail-rag-api -o json)"
  [ "$(jq -r '.status.readyReplicas // 0' <<<"$d")" = "$REPLICAS" ] &&
    [ "$(jq -r '.status.updatedReplicas // 0' <<<"$d")" = "$REPLICAS" ] &&
    [ "$(jq -r '.status.replicas // 0' <<<"$d")" = "$REPLICAS" ] &&
    [ "$(kc -n rail get pods -l app.kubernetes.io/component=api -o json |
      jq '[.items[] | select(.metadata.deletionTimestamp != null)] | length')" = 0 ]
}

wait_settled() { # wait_settled <deadline s>; prints seconds taken
  local t0=$SECONDS
  until settled; do
    ((SECONDS - t0 < $1)) || die "api did not settle at ${REPLICAS} ready pods within $1 s"
    sleep 2
  done
  echo $((SECONDS - t0))
}

QDRANT_NODE="$(kc -n rail get pod rail-rag-qdrant-0 -o jsonpath='{.spec.nodeName}')"
# Qdrant's volume is bound to its node (local-path), so the drained worker is the other one, and
# k6 runs on Qdrant's node so the test never drains its own client.
DRAIN_NODE="$(kc get nodes -l '!node-role.kubernetes.io/control-plane' -o name |
  sed 's|node/||' | grep -vx "$QDRANT_NODE" | head -1)"
[ -n "$DRAIN_NODE" ] || die "no worker without Qdrant to drain"
export K6_NODE="$QDRANT_NODE"

inject() { # inject <scenario> <run name>: apply the fault, wait for recovery, write <run>.chaos.json
  local s="$1" name="$2" target="" node="" at recovered t0
  case "$s" in
    kill)
      read -r target node < <(api_pods | head -1)
      at="$(date -u +%FT%TZ)"; t0=$SECONDS
      kc -n rail delete pod "$target" --wait=false >/dev/null ;;
    crash)
      read -r target node < <(api_pods | head -1)
      local cid
      cid="$(kc -n rail get pod "$target" -o jsonpath='{.status.containerStatuses[0].containerID}')"
      at="$(date -u +%FT%TZ)"; t0=$SECONDS
      # kind nodes are Docker containers; a 0 s timeout makes the runtime send SIGKILL at once.
      docker exec "$node" crictl stop --timeout 0 "${cid#containerd://}" >/dev/null ;;
    rollout)
      at="$(date -u +%FT%TZ)"; t0=$SECONDS
      kc -n rail rollout restart deploy/rail-rag-api >/dev/null ;;
    drain)
      node="$DRAIN_NODE"
      at="$(date -u +%FT%TZ)"; t0=$SECONDS
      kc drain "$node" --ignore-daemonsets --delete-emptydir-data --timeout=300s >/dev/null ;;
  esac
  sleep 3 # let the controllers see the change before checking for recovery
  recovered="$(wait_settled 400)"
  # From the fault itself: kubectl drain blocks until its evictions finish, so the wait above
  # alone reads 0 s for a drain.
  local fault_to_ready=$((SECONDS - t0))
  log "${s}: fault at ${at} on ${target:-deployment} ${node}, ${REPLICAS} pods ready ${fault_to_ready} s after it"
  jq -n --arg s "$s" --arg at "$at" --arg target "$target" --arg node "$node" \
    --argjson recovered "$recovered" --argjson ftr "$fault_to_ready" \
    '{scenario: $s, fault_at: $at, target_pod: $target, node: $node, recovered_s: $recovered,
      fault_to_ready_s: $ftr}' \
    > "$OUT/${name}.chaos.json"
}

restore() { # put the cluster back as it was before the next run
  if [ "$1" = drain ]; then
    kc uncordon "$DRAIN_NODE" >/dev/null
    # Every api pod is now on one node; restart them so the spread constraint places them again.
    kc -n rail rollout restart deploy/rail-rag-api >/dev/null
    kc -n rail rollout status deploy/rail-rag-api --timeout=600s >/dev/null
  fi
  wait_settled 600 >/dev/null
}

run_one() { # run_one <scenario> <run>
  local s="$1" r="$2" name="chaos-$1-r$2" k6pid
  wait_settled 600 >/dev/null
  log "chaos ${s} run ${r}/${RUNS}: pods $(api_pods | awk '{print $2}' | sort | uniq -c | tr -s ' \n' ' ')"
  "$REPO_ROOT/scripts/k6-run.sh" "$name" "$STAGES" > "$OUT/${name}.summary.txt" &
  k6pid=$!
  until [ "$(kc -n rail get pod "k6-${name}" -o jsonpath='{.status.phase}' 2>/dev/null)" = Running ]; do
    sleep 1
  done
  sleep "$FAULT_AFTER"
  inject "$s" "$name"
  wait "$k6pid"
  tee -a "$LOG" < "$OUT/${name}.summary.txt"
  restore "$s"
}

for s in kill crash rollout drain; do
  [[ "$SCENARIO" =~ ^($s|all)$ ]] || continue
  for ((r = 1; r <= RUNS; r++)); do run_one "$s" "$r"; done
done
log "chaos done: $(grep -c '^run:' "$LOG") run summaries in ${LOG}"
