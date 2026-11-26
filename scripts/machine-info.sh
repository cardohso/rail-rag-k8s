#!/usr/bin/env bash
# Print the machine and tool versions as JSON, on macOS or Linux (GitHub Actions). Every benchmark
# result stores this next to its numbers, so a figure is never separated from its hardware.
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need docker python3

json_escape() { python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))'; }
v() { "$@" 2>/dev/null | head -1 | json_escape; }

if [ "$(uname)" = Darwin ]; then
  CPU="$(sysctl -n machdep.cpu.brand_string)"
  CORES="$(sysctl -n hw.ncpu)"
  RAM_GIB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
  OS="macOS $(sw_vers -productVersion)"
else
  CPU="$(lscpu 2>/dev/null | awk -F: '/Model name/{gsub(/^ +/,"",$2); print $2; exit}')"
  CORES="$(nproc)"
  RAM_GIB=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 / 1024 ))
  OS="$(awk -F= '/^PRETTY_NAME=/{gsub(/"/,"",$2); print $2}' /etc/os-release)"
fi

cat <<JSON
{
  "date_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "cpu": $(printf '%s' "${CPU:-unknown}" | json_escape),
  "arch": "$(uname -m)",
  "cpu_cores": ${CORES},
  "ram_gib": ${RAM_GIB},
  "os": $(printf '%s' "$OS" | json_escape),
  "github_runner": $(printf '%s' "${RUNNER_NAME:-} ${ImageOS:-} ${ImageVersion:-}" | json_escape),
  "docker_vm_cpus": $(docker info --format '{{.NCPU}}'),
  "docker_vm_mem_gib": $(docker info --format '{{.MemTotal}}' | awk '{printf "%.1f", $1/1024/1024/1024}'),
  "docker": $(v docker --version),
  "kind": $(v kind version),
  "kubectl": $(v kubectl version --client),
  "helm": $(v helm version --short),
  "node_image": "${KIND_NODE_IMAGE}"
}
JSON
