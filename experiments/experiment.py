#!/usr/bin/env python3
"""Merkle branching-factor benchmark runner.

Usage:
    python experiments/experiment.py --pilot
    python experiments/experiment.py --config experiments/config.yaml
    python experiments/experiment.py --config experiments/config.yaml --smoke

Raw rows are appended to CSV as they are produced, so a partial run leaves
usable, inspectable output and progress is visible in the log.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import time

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from merklebench import environment  # noqa: E402
from merklebench.runner import (  # noqa: E402
    analytical_rows,
    block_order,
    build_plan,
    measure_construction,
    measure_proofs,
    warm_up,
)

BUILD_FIELDS = [
    "run_id", "block", "order_in_block", "seed", "transaction_count",
    "transaction_size_bytes", "branching_factor", "hash_algorithm",
    "build_total_ns", "build_internal_ns", "build_throughput_tx_per_sec",
    "config_wall_ns", "root_digest", "timestamp_utc",
]

PROOF_FIELDS = [
    "run_id", "block", "seed", "proof_seed", "transaction_count",
    "transaction_size_bytes", "branching_factor", "hash_algorithm",
    "proof_sample_count", "generation_batch_reps", "verification_batch_reps",
    "proof_generation_ns", "proof_verification_ns", "mean_serialized_bytes",
    "verification_success", "timestamp_utc",
]


class CsvSink:
    def __init__(self, path: str, fields: list[str]):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.fh = open(path, "w", newline="")
        self.writer = csv.DictWriter(self.fh, fieldnames=fields, extrasaction="ignore")
        self.writer.writeheader()
        self.fh.flush()
        self.rows = 0

    def write(self, row: dict) -> None:
        self.writer.writerow(row)
        self.rows += 1
        self.fh.flush()

    def close(self) -> None:
        self.fh.close()


def write_analytical(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    fields = ["transaction_count", "branching_factor"] + [
        f for f in fields if f not in ("transaction_count", "branching_factor")
    ]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_config(path: str) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def run(cfg: dict, out_dir: str, run_id: str, label: str) -> dict:
    plan = build_plan(cfg)
    rng = random.Random(cfg["seed"])

    os.makedirs(out_dir, exist_ok=True)
    build_sink = CsvSink(os.path.join(out_dir, "build_results.csv"), BUILD_FIELDS)
    proof_sink = CsvSink(os.path.join(out_dir, "proof_results.csv"), PROOF_FIELDS)

    write_analytical(os.path.join(out_dir, "analytic_results.csv"), analytical_rows(plan))

    environment.write(
        os.path.join(out_dir, "environment.json"),
        extra={"run_id": run_id, "label": label, "configuration": cfg},
    )

    print(f"[{label}] run_id={run_id}", flush=True)
    print(f"[{label}] {len(plan.configs)} configurations x {plan.timing_blocks} blocks",
          flush=True)

    # Materialise every workload before timing starts; generation must never
    # happen inside a timed region.
    for n in sorted({c.transaction_count for c in plan.configs}):
        t0 = time.time()
        plan.workload(n)
        print(f"[{label}] workload N={n} ready in {time.time() - t0:.1f}s", flush=True)

    warmed = set()
    started = time.time()

    for block in range(plan.timing_blocks):
        block_started = time.time()
        for position, config in enumerate(block_order(plan.configs, rng)):
            if config.key() not in warmed:
                warm_up(plan, config)
                warmed.add(config.key())

            stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            common = {
                "run_id": run_id,
                "block": block,
                "seed": plan.seed,
                "transaction_count": config.transaction_count,
                "transaction_size_bytes": plan.transaction_size,
                "branching_factor": config.branching_factor,
                "hash_algorithm": config.hash_name,
                "timestamp_utc": stamp,
            }

            config_started = time.perf_counter_ns()
            build = measure_construction(plan, config)
            proofs = measure_proofs(plan, config)
            config_wall_ns = time.perf_counter_ns() - config_started

            build_sink.write({
                **common, "order_in_block": position,
                "config_wall_ns": config_wall_ns, **build,
            })
            if proofs is not None:
                proof_sink.write({**common, "proof_seed": plan.proof_seed, **proofs})

        elapsed = time.time() - started
        per_block = elapsed / (block + 1)
        remaining = per_block * (plan.timing_blocks - block - 1)
        print(
            f"[{label}] block {block + 1}/{plan.timing_blocks} "
            f"took {time.time() - block_started:.1f}s; "
            f"elapsed {elapsed / 60:.1f} min; "
            f"projected remaining {remaining / 60:.1f} min",
            flush=True,
        )

    total = time.time() - started
    build_sink.close()
    proof_sink.close()

    summary = {
        "run_id": run_id,
        "label": label,
        "elapsed_seconds": total,
        "build_rows": build_sink.rows,
        "proof_rows": proof_sink.rows,
        "configurations": len(plan.configs),
        "timing_blocks": plan.timing_blocks,
    }
    print(f"[{label}] complete in {total / 60:.2f} min "
          f"({build_sink.rows} build rows, {proof_sink.rows} proof rows)", flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="experiments/config.yaml")
    parser.add_argument("--pilot", action="store_true",
                        help="run the short pilot configuration")
    parser.add_argument("--smoke", action="store_true",
                        help="run the tiny end-to-end smoke configuration")
    parser.add_argument("--out", default=None, help="output directory")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    if args.pilot:
        path = os.path.join(root, "experiments", "config_pilot.yaml")
        label, default_out = "pilot", "results/raw/pilot"
    elif args.smoke:
        path = os.path.join(root, "experiments", "config_smoke.yaml")
        label, default_out = "smoke", "results/raw/smoke"
    else:
        path = args.config if os.path.isabs(args.config) else os.path.join(root, args.config)
        label, default_out = "final", "results/raw/final"

    cfg = load_config(path)
    out_dir = args.out or os.path.join(root, default_out)
    run_id = args.run_id or f"{label}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"

    run(cfg, out_dir, run_id, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
