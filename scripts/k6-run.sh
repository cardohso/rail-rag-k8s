#!/usr/bin/env bash
# Run tests/load/ask.js inside the cluster (so requests go through the Service and reach every
# pod), then save the k6 summary and the Prometheus series for the run window.
# Usage: scripts/k6-run.sh <run-name> '<stages JSON>' [think_ms]
#   e.g. scripts/k6-run.sh hpa-1 '[{"duration":"1m","target":4},{"duration":"3m","target":16}]'
# Writes results/raw/<run-name>.k6.json and results/raw/<run-name>.prom.json.
# K6_NODE=<node> pins the k6 pod to a node, so a failure test never drains or kills its own client.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need kubectl python3 curl
NAME="${1:?run name}"
STAGES="${2:?stages JSON}"
THINK_MS="${3:-0}"
NODE_SELECTOR="{}"
[ -n "${K6_NODE:-}" ] && NODE_SELECTOR="{kubernetes.io/hostname: ${K6_NODE}}"
NS="rail"
POD="k6-${NAME}"
OUT="$REPO_ROOT/results/raw"
mkdir -p "$OUT"

kc -n "$NS" delete pod "$POD" --ignore-not-found --wait=true >/dev/null
kc -n "$NS" create configmap k6-script --from-file=ask.js="$REPO_ROOT/tests/load/ask.js" \
  --dry-run=client -o yaml | kc apply -f - >/dev/null

# Every core the host gives to something else is a core the cluster loses, so record the host's
# load before and after: a run with a busy host is visible in its own results.
host_load() { sysctl -n vm.loadavg 2>/dev/null || cut -d' ' -f1-3 /proc/loadavg; }
LOAD_BEFORE="$(host_load)"
START=$(date +%s)
log "starting k6 pod ${POD} at $(date -u +%H:%M:%SZ)"
kc -n "$NS" apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: ${POD}
  labels: {app: k6}
spec:
  restartPolicy: Never
  nodeSelector: ${NODE_SELECTOR}
  automountServiceAccountToken: false
  securityContext: {runAsNonRoot: true, runAsUser: 12345, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: k6
      image: grafana/k6:2.4.0
      args: ["run", "--quiet", "/scripts/ask.js"]
      env:
        - {name: TARGET, value: "http://rail-rag-api.${NS}.svc"}
        - {name: STAGES, value: '${STAGES}'}
        - {name: THINK_MS, value: "${THINK_MS}"}
        - {name: RUN_NAME, value: "${NAME}"}
      resources:
        requests: {cpu: 200m, memory: 128Mi}
        limits: {memory: 512Mi}
      securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      volumeMounts: [{name: script, mountPath: /scripts}, {name: tmp, mountPath: /tmp}]
  volumes:
    - {name: script, configMap: {name: k6-script}}
    - {name: tmp, emptyDir: {}}
YAML

kc -n "$NS" wait --for=jsonpath='{.status.phase}'=Running "pod/${POD}" --timeout=180s >/dev/null || true
until phase=$(kc -n "$NS" get pod "$POD" -o jsonpath='{.status.phase}') && [[ "$phase" =~ ^(Succeeded|Failed)$ ]]; do
  sleep 5
done
END=$(date +%s)
log "k6 finished (${phase}) after $((END - START)) s"
kc -n "$NS" logs "$POD" > "$OUT/${NAME}.k6.log"
sed -n '/===K6_SUMMARY_BEGIN===/,/===K6_SUMMARY_END===/p' "$OUT/${NAME}.k6.log" | sed '1d;$d' > "$OUT/${NAME}.k6.json"
log "failed requests logged: $(grep -c 'ASK_FAIL' "$OUT/${NAME}.k6.log" || true) (${NAME}.k6.log)"
[ -s "$OUT/${NAME}.k6.json" ] || { kc -n "$NS" logs "$POD" | tail -20; die "no k6 summary"; }
printf '{"host_load_before": "%s", "host_load_after": "%s"}\n' "$LOAD_BEFORE" "$(host_load)" \
  > "$OUT/${NAME}.host.json"
log "host load average before: ${LOAD_BEFORE}  after: $(host_load)"

# Prometheus series for the run window, 15 s apart, for the analysis and the README tables.
kc -n monitoring port-forward svc/kps-prometheus 19092:9090 >/dev/null 2>&1 &
pf=$!
trap 'kill $pf 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -sf localhost:19092/-/ready >/dev/null && break; sleep 1; done
python3 "$REPO_ROOT/scripts/prom_range.py" http://localhost:19092 "$START" "$END" > "$OUT/${NAME}.prom.json"
kc -n "$NS" delete pod "$POD" --wait=false >/dev/null
python3 "$REPO_ROOT/scripts/summarize_run.py" "$OUT/${NAME}.k6.json" "$OUT/${NAME}.prom.json"
