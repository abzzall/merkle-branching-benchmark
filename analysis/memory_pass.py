#!/usr/bin/env python3
"""Secondary memory pass: peak RSS per configuration, in a fresh subprocess.

Memory is a secondary metric (research plan, Section 14). The paper reports
the exact analytical digest footprint; this pass exists only as a sanity
check that the analytical account is not badly wrong, and its output stays in
the repository rather than the manuscript.

Each configuration runs in its own interpreter because a reused process
retains allocations, and this pass is kept separate from the latency
benchmark because the instrumentation perturbs timing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys

import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

CHILD = r"""
import json, os, resource, sys
sys.path.insert(0, {src!r})
import psutil
from merklebench.workload import generate
from merklebench.tree import build_tree

proc = psutil.Process()
baseline = proc.memory_info().rss
w = generate({n}, {tx}, {seed})
after_workload = proc.memory_info().rss
tree = build_tree(w, {k}, {hash_name!r})
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
print(json.dumps({{
    "baseline_rss_bytes": baseline,
    "workload_rss_bytes": after_workload,
    "peak_rss_bytes": peak,
    "peak_minus_baseline_bytes": peak - baseline,
    "internal_node_count": tree.internal_node_count,
}}))
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="experiments/config.yaml")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--out", default="results/raw/memory/memory_results.csv")
    args = parser.parse_args()

    path = args.config if os.path.isabs(args.config) else os.path.join(ROOT, args.config)
    with open(path) as fh:
        cfg = yaml.safe_load(fh)

    src = os.path.abspath(os.path.join(ROOT, "src"))
    out = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    fields = [
        "transaction_count", "branching_factor", "hash_algorithm", "repetition",
        "baseline_rss_bytes", "workload_rss_bytes", "peak_rss_bytes",
        "peak_minus_baseline_bytes", "internal_node_count",
        "analytical_digest_bytes",
    ]
    rows = 0
    with open(out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for n in cfg["transaction_counts"]:
            for k in cfg["branching_factors"]:
                for hash_name in cfg["hash_algorithms"]:
                    for rep in range(args.repetitions):
                        code = CHILD.format(
                            src=src, n=n, tx=cfg["transaction_size_bytes"],
                            seed=cfg["seed"], k=k, hash_name=hash_name,
                        )
                        result = subprocess.run(
                            [sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=600,
                        )
                        if result.returncode != 0:
                            print(f"FAILED N={n} k={k} {hash_name}: {result.stderr[-300:]}")
                            continue
                        payload = json.loads(result.stdout)
                        payload.update({
                            "transaction_count": n, "branching_factor": k,
                            "hash_algorithm": hash_name, "repetition": rep,
                            "analytical_digest_bytes":
                                (n + payload["internal_node_count"]) * 32,
                        })
                        writer.writerow(payload)
                        fh.flush()
                        rows += 1
                    print(f"  N={n:>8} k={k:>2} {hash_name}", flush=True)

    print(f"{rows} rows -> {out}")
    print("Note: RSS includes interpreter and allocator overhead. The paper "
          "reports the analytical digest footprint instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
