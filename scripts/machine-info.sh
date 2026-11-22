#!/usr/bin/env bash
# Print the machine and tool versions as JSON. Every benchmark result stores this next to its
# numbers, so a figure is never separated from the hardware it was measured on.
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need docker kubectl kind helm

json_escape() { python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))'; }
v() { "$@" 2>/dev/null | head -1 | json_escape; }

cat <<JSON
{
  "date_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "cpu": $(sysctl -n machdep.cpu.brand_string | json_escape),
  "cpu_cores": $(sysctl -n hw.ncpu),
  "ram_gib": $(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 )),
  "os": $(sw_vers -productVersion | json_escape),
  "docker_vm_cpus": $(docker info --format '{{.NCPU}}'),
  "docker_vm_mem_gib": $(docker info --format '{{.MemTotal}}' | awk '{printf "%.1f", $1/1024/1024/1024}'),
  "docker": $(v docker --version),
  "kind": $(v kind version),
  "kubectl": $(v kubectl version --client),
  "helm": $(v helm version --short),
  "k6": $(v k6 version),
  "node_image": "${KIND_NODE_IMAGE}"
}
JSON
