"""One table row per failure-test run: requests, failures and their kind, latency, recovery time.

Reads <dir>/chaos-<scenario>-r<n>.{k6.json,k6.log,chaos.json} from scripts/chaos.sh.
Usage: python3 scripts/chaos_report.py results/raw > results/chaos-<run-id>.md
"""

import collections
import datetime
import glob
import json
import os
import re
import sys

# k6 error codes seen in these tests (k6 docs, "Error codes"); 1000 here is a closed connection.
K6_ERRORS = {1000: "EOF", 1212: "connection refused", 1220: "connection reset"}
MSG = re.compile(r'msg="((?:[^"\\]|\\.)*)"')


def failures(log_path: str) -> tuple[collections.Counter, list[float]]:
    """Kinds of failed request from the ASK_FAIL lines k6 printed (HTTP status or k6 error code),
    and when each failed (unix seconds)."""
    kinds, times = collections.Counter(), []
    if not os.path.exists(log_path):
        return kinds, times
    for line in open(log_path):
        # k6 prints console.warn as a logfmt line: msg="ASK_FAIL {...}" with the quotes escaped.
        msg = MSG.search(line)
        if not msg or not msg.group(1).startswith("ASK_FAIL "):
            continue
        raw = re.sub(r"\\(.)", r"\1", msg.group(1))[len("ASK_FAIL "):]
        try:
            f = json.loads(raw)
        except json.JSONDecodeError:
            kinds["unparsed"] += 1
            continue
        kinds[f"HTTP {f['status']}" if f["status"] else K6_ERRORS.get(f["error_code"], f"k6 {f['error_code']}")] += 1
        times.append(datetime.datetime.fromisoformat(f["t"].replace("Z", "+00:00")).timestamp())
    return kinds, times


def span(times: list[float]) -> str:
    """First to last failure: how long the fault was visible to clients."""
    return f"{max(times) - min(times):.1f} s" if times else "-"


def alerts(prom_path: str) -> str:
    """Alerts that fired at any point in the run's window (prom_range.py's alert_* series)."""
    if not os.path.exists(prom_path):
        return "not recorded"
    series = json.load(open(prom_path))["series"]
    if not any(k.startswith("alert_") for k in series):
        return "not recorded"
    return ", ".join(k[len("alert_"):] for k, v in series.items() if k.startswith("alert_") and v) or "none"


def ready(c: dict) -> str:
    """Seconds from the fault until 3 api pods (and Qdrant) are ready. Runs before fault_to_ready_s was recorded
    timed from after the fault command returned, which for a drain is after its evictions."""
    if "fault_to_ready_s" in c:
        return f"{c['fault_to_ready_s']} s"
    if c["scenario"] == "drain":
        return "not recorded"
    return f"{c['recovered_s'] + 3} s"


def main() -> None:
    d = sys.argv[1]
    print("| scenario | run | requests | failed | kinds | failures span | p95 | p99 | max "
          "| ready again, from the fault | alerts fired |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for path in sorted(glob.glob(os.path.join(d, "chaos-*-r*.chaos.json"))):
        base = path[: -len(".chaos.json")]
        c = json.load(open(path))
        m = json.load(open(base + ".k6.json"))["metrics"]
        lat = m["http_req_duration"]["values"]
        kinds, times = failures(base + ".k6.log")
        run = base.rsplit("-r", 1)[1]
        print(f"| {c['scenario']} | {run} | {m['http_reqs']['values']['count']:.0f} "
              f"| {m['http_req_failed']['values'].get('passes', 0):.0f} "
              f"| {', '.join(f'{k} x{n}' for k, n in kinds.items()) or '-'} | {span(times)} "
              f"| {lat['p(95)'] / 1000:.2f} s | {lat['p(99)'] / 1000:.2f} s | {lat['max'] / 1000:.1f} s "
              f"| {ready(c)} | {alerts(base + '.prom.json')} |")


if __name__ == "__main__":
    main()
