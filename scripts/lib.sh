#!/usr/bin/env bash
# Shared settings and helpers. Source this file; do not run it.
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-rail-k8s}"
# Pinned: kubectl on the dev machine is 1.36, and one minor of skew is the supported maximum.
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.36.4}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_ROOT
KUBE_CONTEXT="kind-${CLUSTER_NAME}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

need() {
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || die "missing required tool: $tool"
  done
}

cluster_exists() { kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; }

# Always pass the context, so a command can never hit another cluster by accident.
kc() { kubectl --context "$KUBE_CONTEXT" "$@"; }
