#!/usr/bin/env python3
"""Post-hoc robustness check: fit the cost model on pilot, predict final.

This is temporal/workload validation on the same platform, not independent
platform validation.  Pilot and final proof samples differ (8 versus 16), so
each run's own analytical sampled-proof predictors are used.
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from process import _fit_nnls, _mape  # noqa: E402

HASHES = ("sha256", "sha3_256", "blake2s")


def merged(processed: str, raw: str, metric: str) -> pd.DataFrame:
    summary_name = "build_summary.csv" if metric == "build_total_ns" else "proof_summary.csv"
    summary = pd.read_csv(os.path.join(processed, summary_name))
    analytic = pd.read_csv(os.path.join(raw, "analytic_results.csv"))
    return summary.merge(analytic, on=["transaction_count", "branching_factor"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    root = args.results or os.path.join(os.path.dirname(__file__), "..", "results")
    root = os.path.abspath(root)
    out = args.out or os.path.join(root, "processed", "final", "pilot_final_robustness.csv")

    specs = (
        ("build_total_ns", "construction_hash_calls_total", "construction_bytes_total"),
        ("proof_verification_ns", "sampled_mean_verification_hash_calls",
         "sampled_mean_verification_bytes"),
    )
    rows = []
    for metric, calls_col, bytes_col in specs:
        pilot = merged(
            os.path.join(root, "processed", "pilot"),
            os.path.join(root, "raw", "pilot"), metric,
        )
        final = merged(
            os.path.join(root, "processed", "final"),
            os.path.join(root, "raw", "final"), metric,
        )
        target = f"{metric}_median"
        for hash_name in HASHES:
            train = pilot[pilot["hash_algorithm"] == hash_name]
            test = final[final["hash_algorithm"] == hash_name].copy()
            a, b = _fit_nnls(train[calls_col], train[bytes_col], train[target])
            test["predicted"] = a * test[calls_col] + b * test[bytes_col]
            largest = test[test["transaction_count"] == test["transaction_count"].max()]
            rows.append({
                "metric": metric,
                "hash_algorithm": hash_name,
                "pilot_cells": len(train),
                "final_cells": len(test),
                "a_ns_per_hash_call": a,
                "b_ns_per_byte": b,
                "final_mape_percent": _mape(test[target], test["predicted"]),
                "largest_workload_mape_percent": _mape(
                    largest[target], largest["predicted"]
                ),
            })

    frame = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    frame.to_csv(out, index=False)
    print(frame.to_string(index=False))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
