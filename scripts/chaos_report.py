"""One table row per failure-test run: requests, failures and their kind, latency, recovery time.

Reads <dir>/chaos-<scenario>-r<n>.{k6.json,k6.log,chaos.json} from scripts/chaos.sh.
Usage: python3 scripts/chaos_report.py results/raw > results/chaos-<run-id>.md
"""

import collections
import glob
import json
import os
import re
import sys

MSG = re.compile(r'msg="((?:[^"\\]|\\.)*)"')


def failures(log_path: str) -> collections.Counter:
    """Kinds of failed request from the ASK_FAIL lines k6 printed: HTTP status or k6 error code."""
    kinds = collections.Counter()
    if not os.path.exists(log_path):
        return kinds
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
        kinds[f"HTTP {f['status']}" if f["status"] else f"k6 {f['error_code']}"] += 1
    return kinds


def main() -> None:
    d = sys.argv[1]
    print("| scenario | run | requests | failed | kinds | p95 | p99 | max | ready again after |")
    print("|---|---|---|---|---|---|---|---|---|")
    for path in sorted(glob.glob(os.path.join(d, "chaos-*-r*.chaos.json"))):
        base = path[: -len(".chaos.json")]
        c = json.load(open(path))
        m = json.load(open(base + ".k6.json"))["metrics"]
        lat = m["http_req_duration"]["values"]
        kinds = failures(base + ".k6.log")
        run = base.rsplit("-r", 1)[1]
        print(f"| {c['scenario']} | {run} | {m['http_reqs']['values']['count']:.0f} "
              f"| {m['http_req_failed']['values'].get('passes', 0):.0f} "
              f"| {', '.join(f'{k} x{n}' for k, n in kinds.items()) or '-'} "
              f"| {lat['p(95)'] / 1000:.2f} s | {lat['p(99)'] / 1000:.2f} s | {lat['max'] / 1000:.1f} s "
              f"| {c['recovered_s']} s |")


if __name__ == "__main__":
    main()
