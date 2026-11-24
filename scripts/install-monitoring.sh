#!/usr/bin/env bash
# Install kube-prometheus-stack (Prometheus, Alertmanager, Grafana) into the "monitoring" namespace.
# Usage: scripts/install-monitoring.sh        Idempotent: running it twice upgrades in place.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need helm kubectl

CHART_VERSION="93.10.0"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update prometheus-community >/dev/null

log "installing kube-prometheus-stack ${CHART_VERSION} into namespace monitoring"
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  --kube-context "$KUBE_CONTEXT" --namespace monitoring --create-namespace \
  --version "$CHART_VERSION" \
  -f "$REPO_ROOT/observability/kube-prometheus-stack-values.yaml" \
  --wait --timeout 10m
log "monitoring is up. Grafana: kubectl -n monitoring port-forward svc/kps-grafana 3000:80"
