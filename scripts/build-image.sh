#!/usr/bin/env bash
# Build the api image (running the wrapper tests inside it) and load it into the kind cluster.
# Usage: scripts/build-image.sh [tag]      default tag: dev
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need docker
TAG="${1:-dev}"
IMAGE="rail-rag-k8s:${TAG}"

log "running the wrapper tests inside the image (target: test)"
docker build --target test -f "$REPO_ROOT/image/Dockerfile" "$REPO_ROOT"

log "building ${IMAGE}"
docker build -f "$REPO_ROOT/image/Dockerfile" -t "$IMAGE" "$REPO_ROOT"
docker image inspect "$IMAGE" --format 'size: {{.Size}} bytes, arch: {{.Architecture}}'

if cluster_exists; then
  need kind
  log "loading ${IMAGE} into kind cluster ${CLUSTER_NAME}"
  kind load docker-image "$IMAGE" --name "$CLUSTER_NAME"
else
  log "cluster ${CLUSTER_NAME} is not up; skipping kind load"
fi
