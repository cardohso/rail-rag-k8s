#!/usr/bin/env bash
# One command: create the kind cluster (idempotent). Later steps append installs here.
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need docker kind kubectl helm

docker info >/dev/null 2>&1 || die "Docker is not running"

if cluster_exists; then
  log "cluster ${CLUSTER_NAME} already exists, reusing it"
else
  log "creating kind cluster ${CLUSTER_NAME} (${KIND_NODE_IMAGE})"
  kind create cluster --name "$CLUSTER_NAME" --image "$KIND_NODE_IMAGE" \
    --config "${REPO_ROOT}/cluster/kind-config.yaml" --wait 120s
fi

kc wait --for=condition=Ready nodes --all --timeout=120s
kc get nodes -o wide
log "cluster up. context: ${KUBE_CONTEXT}"
