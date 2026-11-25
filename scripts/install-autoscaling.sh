#!/usr/bin/env bash
# Install what autoscaling needs: metrics-server (CPU and memory for HPAs, `kubectl top`) and KEDA
# (scaling on a Prometheus query). Usage: scripts/install-autoscaling.sh     Idempotent.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need helm kubectl

METRICS_SERVER_VERSION="3.14.0"
KEDA_VERSION="2.21.1"
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ >/dev/null 2>&1 || true
helm repo add kedacore https://kedacore.github.io/charts >/dev/null 2>&1 || true
helm repo update metrics-server kedacore >/dev/null

log "installing metrics-server ${METRICS_SERVER_VERSION}"
# kind's kubelets serve self-signed certificates, so metrics-server cannot verify them.
# Acceptable on a local cluster only.
helm upgrade --install metrics-server metrics-server/metrics-server \
  --kube-context "$KUBE_CONTEXT" --namespace kube-system --version "$METRICS_SERVER_VERSION" \
  --set 'args={--kubelet-insecure-tls}' \
  --set resources.requests.cpu=20m --set resources.requests.memory=48Mi \
  --set resources.limits.memory=128Mi \
  --wait --timeout 5m

log "installing KEDA ${KEDA_VERSION}"
helm upgrade --install keda kedacore/keda \
  --kube-context "$KUBE_CONTEXT" --namespace keda --create-namespace --version "$KEDA_VERSION" \
  --set resources.operator.requests.cpu=20m --set resources.operator.requests.memory=64Mi \
  --set resources.operator.limits.memory=256Mi \
  --set resources.metricServer.requests.cpu=20m --set resources.metricServer.requests.memory=64Mi \
  --set resources.metricServer.limits.memory=256Mi \
  --set resources.webhooks.requests.cpu=10m --set resources.webhooks.requests.memory=32Mi \
  --set resources.webhooks.limits.memory=128Mi \
  --wait --timeout 5m

log "waiting for the resource metrics API"
for _ in $(seq 1 40); do
  kc top nodes >/dev/null 2>&1 && { kc top nodes; log "autoscaling prerequisites are up"; exit 0; }
  sleep 3
done
die "metrics.k8s.io did not become available"
