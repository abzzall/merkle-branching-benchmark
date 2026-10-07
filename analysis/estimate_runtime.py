#!/usr/bin/env python3
"""Project final-run wall time from pilot measurements.

The gate is two-sided (research plan, Section 13). A projection above the
45-minute limit means reduce blocks or batch targets; a projection far below
it means the workload grid is too small to resolve the effects being studied
and should be scaled up before launching.

Wall time per configuration is modelled per hash implementation as
    wall = a * hash_calls + b * bytes_hashed + c
fitted on the pilot cells, then evaluated over the full final grid.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from merklebench import analytic  # noqa: E402

LOWER_GATE_MINUTES = 10.0
UPPER_GATE_MINUTES = 45.0
HARD_LIMIT_MINUTES = 60.0


def fit_wall_model(pilot: pd.DataFrame, tx_size: int) -> dict:
    models = {}
    for hash_name, group in pilot.groupby("hash_algorithm"):
        rows = []
        for _, row in group.iterrows():
            n, k = int(row["transaction_count"]), int(row["branching_factor"])
            calls = analytic.construction_hash_calls(n, k)["total"]
            byts = analytic.construction_bytes_hashed(n, k, tx_size)["total"]
            rows.append((calls, byts, row["config_wall_ns"]))
        arr = np.asarray(rows, dtype=float)
        design = np.column_stack([arr[:, 0], arr[:, 1], np.ones(len(arr))])
        coef, *_ = np.linalg.lstsq(design, arr[:, 2], rcond=None)
        models[hash_name] = coef
    return models


def project(models: dict, cfg: dict) -> tuple[float, pd.DataFrame]:
    tx_size = cfg["transaction_size_bytes"]
    algorithms = list(cfg["hash_algorithms"]) + list(cfg.get("control_algorithms", []))
    blocks = cfg["timing_blocks"]

    rows = []
    for n in cfg["transaction_counts"]:
        for k in cfg["branching_factors"]:
            calls = analytic.construction_hash_calls(n, k)["total"]
            byts = analytic.construction_bytes_hashed(n, k, tx_size)["total"]
            for hash_name in algorithms:
                coef = models.get(hash_name)
                if coef is None:
                    coef = np.mean([c for c in models.values()], axis=0)
                wall_ns = max(coef[0] * calls + coef[1] * byts + coef[2], 0.0)
                rows.append({
                    "transaction_count": n, "branching_factor": k,
                    "hash_algorithm": hash_name,
                    "projected_seconds_per_block": wall_ns / 1e9,
                    "projected_seconds_total": wall_ns * blocks / 1e9,
                })
    frame = pd.DataFrame(rows)
    return float(frame["projected_seconds_total"].sum()), frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot_raw_dir")
    parser.add_argument("--final-config", default="experiments/config.yaml")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    pilot = pd.read_csv(os.path.join(args.pilot_raw_dir, "build_results.csv"))
    with open(os.path.join(args.pilot_raw_dir, "environment.json")) as fh:
        pilot_env = json.load(fh)
    tx_size = pilot_env["configuration"]["transaction_size_bytes"]

    path = args.final_config
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    with open(path) as fh:
        final_cfg = yaml.safe_load(fh)

    models = fit_wall_model(pilot, tx_size)
    total_seconds, frame = project(models, final_cfg)
    minutes = total_seconds / 60.0

    pilot_minutes = pilot["config_wall_ns"].sum() / 1e9 / 60.0

    print(f"pilot wall time (timed work only) : {pilot_minutes:.2f} min")
    print(f"projected final run              : {minutes:.1f} min")
    print(f"headroom to {UPPER_GATE_MINUTES:.0f}-minute gate      : {UPPER_GATE_MINUTES - minutes:.1f} min")
    print()
    print("largest contributors:")
    top = frame.sort_values("projected_seconds_total", ascending=False).head(8)
    for _, row in top.iterrows():
        print(f"  N={int(row['transaction_count']):>8} k={int(row['branching_factor']):>2} "
              f"{row['hash_algorithm']:<9} {row['projected_seconds_total'] / 60:6.2f} min")

    if minutes > HARD_LIMIT_MINUTES:
        verdict, code = "BLOCKED: exceeds the hard 60-minute limit", 2
    elif minutes > UPPER_GATE_MINUTES:
        verdict, code = "BLOCKED: exceeds the 45-minute launch gate", 1
    elif minutes < LOWER_GATE_MINUTES:
        verdict, code = (
            f"UNDER-USED: below {LOWER_GATE_MINUTES:.0f} min; scale the workload grid up "
            "before launching", 3
        )
    else:
        verdict, code = "CLEARED: within the launch gate", 0

    print()
    print(verdict)

    out = args.out or os.path.join(root, "results", "processed", "runtime_estimate.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump({
            "pilot_raw_dir": os.path.abspath(args.pilot_raw_dir),
            "final_config": os.path.abspath(path),
            "projected_minutes": minutes,
            "upper_gate_minutes": UPPER_GATE_MINUTES,
            "lower_gate_minutes": LOWER_GATE_MINUTES,
            "verdict": verdict,
            "per_configuration": frame.to_dict(orient="records"),
        }, fh, indent=2)
    print(f"written to {out}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
