"""Query the Prometheus series a load-test run is judged on, for one time window, as JSON.

Usage: python3 scripts/prom_range.py <prometheus-url> <start-unix> <end-unix>
"""

import json
import sys
import urllib.parse
import urllib.request

NS = 'namespace="rail"'
QUERIES = {
    "replicas_desired": f'sum(kube_deployment_spec_replicas{{{NS},deployment="rail-rag-api"}})',
    "replicas_ready": f'sum(kube_deployment_status_replicas_available{{{NS},deployment="rail-rag-api"}})',
    "in_flight_total": f'sum(rail_http_requests_in_flight{{{NS}}})',
    "in_flight_per_pod_avg": f'avg(rail_http_requests_in_flight{{{NS}}})',
    "rps": 'sum(rate(rail_http_requests_total{route="/ask"}[1m]))',
    "rps_5xx": 'sum(rate(rail_http_requests_total{route="/ask",status=~"5.."}[1m]))',
    "p95_s": 'histogram_quantile(0.95, sum by (le) (rate(rail_http_request_duration_seconds_bucket{route="/ask"}[1m])))',
    "api_cpu_cores_total": f'sum(rate(container_cpu_usage_seconds_total{{{NS},container="api"}}[1m]))',
    "api_cpu_cores_per_pod_avg": f'avg(rate(container_cpu_usage_seconds_total{{{NS},container="api"}}[1m]))',
    "qdrant_cpu_cores": f'sum(rate(container_cpu_usage_seconds_total{{{NS},container="qdrant"}}[1m]))',
    "k6_cpu_cores": f'sum(rate(container_cpu_usage_seconds_total{{{NS},container="k6"}}[1m]))',
    "grafana_cpu_cores": 'sum(rate(container_cpu_usage_seconds_total{namespace="monitoring",container="grafana"}[1m]))',
    "node_cpu_busy_cores": 'sum(rate(node_cpu_seconds_total{mode!="idle"}[1m]))',
    # 1 while the alert fires, absent otherwise: the evidence that the rules work under load.
    **{f"alert_{a}": f'max(ALERTS{{alertname="{a}",alertstate="firing"}})'
       for a in ("RailApiAtMaxReplicas", "RailApiHighLatency", "RailApiHighErrorRate",
                 "RailQdrantDown", "RailQdrantErrors", "RailApiDown")},
}


def query_range(base: str, expr: str, start: int, end: int) -> list[list[float]]:
    qs = urllib.parse.urlencode({"query": expr, "start": start, "end": end, "step": 15})
    with urllib.request.urlopen(f"{base}/api/v1/query_range?{qs}", timeout=30) as r:
        result = json.load(r)["data"]["result"]
    return [[float(t), float(v)] for t, v in result[0]["values"]] if result else []


def main() -> None:
    base, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    out = {"start": start, "end": end, "step_s": 15, "queries": QUERIES, "series": {}}
    for name, expr in QUERIES.items():
        out["series"][name] = query_range(base, expr, start, end)
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
