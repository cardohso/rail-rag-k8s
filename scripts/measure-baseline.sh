#!/usr/bin/env bash
# Measure what the empty cluster costs, so the memory plan in docs/DESIGN.md (D1) is a number,
# not a guess. Usage: scripts/measure-baseline.sh [label]   (writes results/baseline-<label>.json)
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need docker kind kubectl python3
cluster_exists || die "cluster ${CLUSTER_NAME} is not up (run: make up)"

label="${1:-empty-cluster}"
out="${REPO_ROOT}/results/baseline-${label}.json"
sleep 30  # let the control plane settle after startup

# xargs, not mapfile: macOS ships bash 3.2, which has no mapfile.
stats="$(docker ps --filter "label=io.x-k8s.kind.cluster=${CLUSTER_NAME}" -q \
  | xargs docker stats --no-stream --format '{{json .}}')"
docker_mem="$(docker info --format '{{.MemTotal}}')"

STATS="$stats" DOCKER_MEM="$docker_mem" LABEL="$label" \
MACHINE="$("${REPO_ROOT}/scripts/machine-info.sh")" python3 - "$out" <<'PY'
import json, os, re, sys

def mib(s):  # "412.3MiB / 7.75GiB" -> 412.3
    used = s.split("/")[0].strip()
    n = float(re.match(r"[\d.]+", used).group())
    return n * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[re.search(r"[KMG]iB", used).group()]

rows = [json.loads(line) for line in os.environ["STATS"].splitlines() if line.strip()]
nodes = {r["Name"]: round(mib(r["MemUsage"]), 1) for r in rows}
doc = {
    "label": os.environ["LABEL"],
    "node_container_mem_mib": nodes,
    "total_mib": round(sum(nodes.values()), 1),
    "docker_vm_mem_mib": round(int(os.environ["DOCKER_MEM"]) / 1024 / 1024),
    "machine": json.loads(os.environ["MACHINE"]),
}
open(sys.argv[1], "w").write(json.dumps(doc, indent=2) + "\n")
print(json.dumps({k: doc[k] for k in ("label", "node_container_mem_mib", "total_mib", "docker_vm_mem_mib")}, indent=2))
PY
log "wrote ${out}"
