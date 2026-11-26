"""Tables for the README and DESIGN from one benchmark workflow run, each cell the range over its runs.

Reads <dir>/<scenario>-r<n>.{k6,prom}.json (the workflow's artifact) and prints Markdown.
Usage: python3 scripts/bench_report.py results/bench/<run-id> > results/bench-<run-id>.md
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from stage_table import seconds  # noqa: E402


def load(d: str, scenario: str) -> list[tuple[dict, dict]]:
    runs = []
    for k6_path in sorted(glob.glob(os.path.join(d, f"{scenario}-r*.k6.json"))):
        prom_path = k6_path.replace(".k6.json", ".prom.json")
        runs.append((json.load(open(k6_path)), json.load(open(prom_path))))
    return runs


def plateaus(k6: dict, prom: dict) -> list[tuple[int, dict]]:
    """(VUs, {series: mean over the last 20 s of the hold}) for each hold, as stage_table.py."""
    s, t0 = prom["series"], prom["start"]
    total = sum(seconds(st["duration"]) for st in k6["stages"])
    offset = max(0, prom["end"] - t0 - total)
    out, t, prev = [], 0, None
    for st in k6["stages"]:
        t += seconds(st["duration"])
        tgt = st["target"]
        if tgt == prev and tgt > 0:
            end = t0 + offset + t
            row = {}
            for name, series in s.items():
                vals = [v for ts, v in series if end - 20 <= ts <= end and v == v]
                row[name] = sum(vals) / len(vals) if vals else float("nan")
            out.append((tgt, row))
        prev = tgt
    return out


def rng(vals: list[float], fmt: str) -> str:
    lo, hi = fmt.format(min(vals)), fmt.format(max(vals))
    return lo if lo == hi else f"{lo}–{hi}"


def first_change(prom: dict, to_at_least: int) -> float:
    """Seconds from the window start until desired replicas first reach `to_at_least`."""
    for ts, v in prom["series"]["replicas_desired"]:
        if v >= to_at_least:
            return ts - prom["start"]
    return float("nan")


def capacity(d: str) -> None:
    runs = load(d, "capacity")
    if not runs:
        return
    rows = [plateaus(k, p) for k, p in runs]
    print(f"## Capacity: one api pod ({len(runs)} runs)\n")
    fails = [k["metrics"]["http_req_failed"]["values"].get("passes", 0) for k, _ in runs]
    reqs = [k["metrics"]["http_reqs"]["values"]["count"] for k, _ in runs]
    print("Failed requests per run: " + ", ".join(f"{f:.0f} of {r:.0f}" for f, r in zip(fails, reqs))
          + ".\n")
    print("Each cell is the range over the runs, from the last 20 s of each plateau.\n")
    print("| VUs | req/s | p95 (Prometheus) | in flight | pod CPU (cores) |")
    print("|---|---|---|---|---|")
    for i, (vus, _) in enumerate(rows[0]):
        cells = [r[i][1] for r in rows]
        print(f"| {vus} | {rng([c['rps'] for c in cells], '{:.2f}')} "
              f"| {rng([c['p95_s'] for c in cells], '{:.2f}')} s "
              f"| {rng([c['in_flight_per_pod_avg'] for c in cells], '{:.1f}')} "
              f"| {rng([c['api_cpu_cores_per_pod_avg'] for c in cells], '{:.2f}')} |")
    print()


def scaling(d: str) -> None:
    print("## Autoscaling: a 40-VU burst between two 2-VU periods\n")
    print("k6 latency is over the whole run; pods and req/s are from the end of the burst.\n")
    print("| scenario | runs | failed | p95 | p99 | max | pods in burst | req/s in burst "
          "| s to 2 pods | in flight per pod |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for scenario in ("hpa", "keda"):
        runs = load(d, scenario)
        if not runs:
            continue
        lat = [k["metrics"]["http_req_duration"]["values"] for k, _ in runs]
        failed = [k["metrics"]["http_req_failed"]["values"].get("passes", 0) for k, _ in runs]
        burst = [max(plateaus(k, p), key=lambda r: r[0])[1] for k, p in runs]
        # The burst's ramp starts 120 s into the stages; the window starts at k6 pod creation.
        to2 = [first_change(p, 2) - (p["end"] - p["start"]
                                     - sum(seconds(s["duration"]) for s in k["stages"])) - 120
               for k, p in runs]
        print(f"| {scenario} | {len(runs)} | {rng(failed, '{:.0f}')} "
              f"| {rng([x['p(95)'] / 1000 for x in lat], '{:.2f}')} s "
              f"| {rng([x['p(99)'] / 1000 for x in lat], '{:.2f}')} s "
              f"| {rng([x['max'] / 1000 for x in lat], '{:.1f}')} s "
              f"| {rng([b['replicas_ready'] for b in burst], '{:.0f}')} "
              f"| {rng([b['rps'] for b in burst], '{:.1f}')} "
              f"| {rng(to2, '{:.0f}')} "
              f"| {rng([b['in_flight_per_pod_avg'] for b in burst], '{:.1f}')} |")
    print()


def main() -> None:
    d = sys.argv[1]
    m = json.load(open(os.path.join(d, "machine.json")))
    print(f"# Benchmark {os.path.basename(os.path.normpath(d))}\n")
    print(f"Machine: {m.get('github_runner') or 'local'}, {m['cpu']} ({m['arch']}), "
          f"{m['cpu_cores']} cores, {m['ram_gib']} GiB; kind {m['kind'].split()[1]}, "
          f"{m['node_image']}. Recorded {m['date_utc']}. Generated by scripts/bench_report.py.\n")
    capacity(d)
    scaling(d)


if __name__ == "__main__":
    main()
