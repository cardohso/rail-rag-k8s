#!/usr/bin/env bash
# One command: delete the cluster and everything in it. Safe to run twice.
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need kind

if cluster_exists; then
  log "deleting kind cluster ${CLUSTER_NAME}"
  kind delete cluster --name "$CLUSTER_NAME"
else
  log "cluster ${CLUSTER_NAME} does not exist, nothing to do"
fi
