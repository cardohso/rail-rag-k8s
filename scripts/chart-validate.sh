#!/usr/bin/env bash
# Static checks for the chart, run identically on a laptop and in CI: helm lint, then every values
# overlay rendered and validated against the Kubernetes API schemas (strict: unknown fields fail).
# chart-testing (`ct lint`) runs separately because it needs yamllint.
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need helm kubeconform

CHART="${REPO_ROOT}/charts/rail-rag"
K8S_VERSION="${K8S_VERSION:-1.36.0}"
failed=0

for overlay in "" values-dev.yaml values-ci.yaml; do
  label="${overlay:-values.yaml}"
  args=()
  [ -n "$overlay" ] && args=(-f "${CHART}/${overlay}")

  log "helm lint (${label})"
  helm lint "$CHART" ${args[@]+"${args[@]}"} || failed=1

  log "kubeconform, Kubernetes ${K8S_VERSION} (${label})"
  helm template rail-rag "$CHART" ${args[@]+"${args[@]}"} \
    | kubeconform -strict -summary -kubernetes-version "$K8S_VERSION" || failed=1
done

[ "$failed" -eq 0 ] || die "chart validation failed"
log "chart validation passed"
