"""Print the headline numbers of one load-test run from its k6 summary and Prometheus series.

Usage: python3 scripts/summarize_run.py results/raw/<run>.k6.json results/raw/<run>.prom.json
"""

import json
import sys


def main() -> None:
    k6 = json.load(open(sys.argv[1]))
    prom = json.load(open(sys.argv[2]))
    m = k6["metrics"]
    reqs = m["http_reqs"]["values"]["count"]
    failed = m["http_req_failed"]["values"]["rate"]
    d = m["http_req_duration"]["values"]
    print(f"run: {k6['run']}  stages: {json.dumps(k6['stages'])}")
    print(f"requests: {reqs:.0f}  failed: {failed:.2%}  "
          f"answered: {m.get('ask_answered', {}).get('values', {}).get('count', 0):.0f}  "
          f"refused: {m.get('ask_refused', {}).get('values', {}).get('count', 0):.0f}")
    print("latency ms: " + "  ".join(f"{k}={d[k]:.0f}" for k in ("med", "p(95)", "p(99)", "max")))
    s = prom["series"]
    t0 = prom["start"]

    def peak(name):
        vals = [v for _, v in s.get(name, []) if v == v]
        return max(vals) if vals else float("nan")

    for name in ("replicas_desired", "replicas_ready", "in_flight_per_pod_avg", "rps",
                 "api_cpu_cores_per_pod_avg", "api_cpu_cores_total", "k6_cpu_cores",
                 "grafana_cpu_cores", "node_cpu_busy_cores"):
        print(f"  peak {name}: {peak(name):.2f}")
    changes, last = [], None
    for t, v in s.get("replicas_desired", []):
        if v != last:
            changes.append(f"+{t - t0:.0f}s->{v:.0f}")
            last = v
    print("  desired replicas over time: " + " ".join(changes))


if __name__ == "__main__":
    main()
