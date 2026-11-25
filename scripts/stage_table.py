"""One row per load plateau of a run: throughput, latency, CPU and in-flight at the plateau's end.

Plateaus are stages whose target equals the previous stage's (a hold). The 1-minute rate windows
lag, so each row uses the samples in the last 20 s of the plateau.
Usage: python3 scripts/stage_table.py results/raw/<run>.k6.json results/raw/<run>.prom.json
"""

import json
import re
import sys


def seconds(d: str) -> int:
    return sum(int(n) * {"s": 1, "m": 60, "h": 3600}[u] for n, u in re.findall(r"(\d+)([smh])", d))


def main() -> None:
    k6, prom = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
    s, t0 = prom["series"], prom["start"]
    # The pod start and image pull happen before k6 runs; find when traffic begins.
    rps = s["rps"]
    first = next((t for t, v in rps if v > 0), t0)
    offset = first - t0 - 15  # rate[1m] turns non-zero within about one step
    cols = ["rps", "p95_s", "in_flight_per_pod_avg", "api_cpu_cores_per_pod_avg", "replicas_ready"]
    print("| VUs | " + " | ".join(cols) + " |")
    print("|" + "---|" * (len(cols) + 1))
    t, prev = 0, None
    for st in k6["stages"]:
        dur, tgt = seconds(st["duration"]), st["target"]
        t += dur
        if tgt == prev and tgt > 0:
            end = t0 + offset + t
            row = []
            for c in cols:
                vals = [v for ts, v in s[c] if end - 20 <= ts <= end and v == v]
                row.append(f"{sum(vals) / len(vals):.2f}" if vals else "n/a")
            print(f"| {tgt} | " + " | ".join(row) + " |")
        prev = tgt


if __name__ == "__main__":
    main()
