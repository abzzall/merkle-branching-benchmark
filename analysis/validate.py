#!/usr/bin/env python3
"""Validate a raw result directory before any analysis is run.

Checks completeness, schema, and internal consistency. Exits non-zero on any
failure so a broken run cannot silently reach the paper.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from merklebench import analytic  # noqa: E402
from merklebench.hashing import CONTROL_ALGORITHMS  # noqa: E402


def validate(raw_dir: str) -> list[str]:
    problems = []

    def need(path):
        full = os.path.join(raw_dir, path)
        if not os.path.exists(full):
            problems.append(f"missing file: {path}")
            return None
        return full

    build_path = need("build_results.csv")
    proof_path = need("proof_results.csv")
    analytic_path = need("analytic_results.csv")
    env_path = need("environment.json")
    if problems:
        return problems

    build = pd.read_csv(build_path)
    proof = pd.read_csv(proof_path)
    analytic_df = pd.read_csv(analytic_path)
    with open(env_path) as fh:
        env = json.load(fh)

    cfg = env.get("configuration", {})
    expected_ns = set(cfg.get("transaction_counts", []))
    expected_ks = set(cfg.get("branching_factors", []))
    expected_hashes = set(cfg.get("hash_algorithms", [])) | set(
        cfg.get("control_algorithms", [])
    )
    blocks = cfg.get("timing_blocks")

    # --- completeness ---
    if blocks is not None:
        expected_rows = len(expected_ns) * len(expected_ks) * len(expected_hashes) * blocks
        if len(build) != expected_rows:
            problems.append(
                f"build_results.csv has {len(build)} rows, expected {expected_rows}"
            )
        counts = build.groupby(
            ["transaction_count", "branching_factor", "hash_algorithm"]
        ).size()
        bad = counts[counts != blocks]
        if len(bad):
            problems.append(f"{len(bad)} configurations do not have exactly {blocks} observations")

    missing = (
        expected_ns - set(build["transaction_count"]),
        expected_ks - set(build["branching_factor"]),
        expected_hashes - set(build["hash_algorithm"]),
    )
    for name, gap in zip(("transaction_count", "branching_factor", "hash_algorithm"), missing):
        if gap:
            problems.append(f"missing {name} levels in build results: {sorted(gap)}")

    # --- no corrupted or partial rows ---
    if build.isna().any().any():
        problems.append("build_results.csv contains null values")
    if proof.isna().any().any():
        problems.append("proof_results.csv contains null values")
    for col in ("build_total_ns", "build_internal_ns"):
        if (build[col] <= 0).any():
            problems.append(f"non-positive values in {col}")
    if (build["build_internal_ns"] > build["build_total_ns"]).mean() > 0.10:
        problems.append(
            "internal-only construction exceeded full construction in more than "
            "10% of observations, which suggests timing corruption"
        )

    # --- proofs ---
    if not proof.empty:
        if not proof["verification_success"].astype(str).str.lower().isin(["true"]).all():
            problems.append("at least one sampled proof failed verification")
        control_rows = proof[proof["hash_algorithm"].isin(CONTROL_ALGORITHMS)]
        if len(control_rows):
            problems.append("control algorithm appears in proof results")
        if (proof["proof_verification_ns"] <= 0).any():
            problems.append("non-positive verification latency")

    # --- roots are stable across blocks ---
    roots = build.groupby(
        ["transaction_count", "branching_factor", "hash_algorithm"]
    )["root_digest"].nunique()
    unstable = roots[roots != 1]
    if len(unstable):
        problems.append(f"{len(unstable)} configurations produced inconsistent roots")

    # --- measured structure matches the analytical model ---
    tx_size = cfg.get("transaction_size_bytes")
    for _, row in analytic_df.iterrows():
        n, k = int(row["transaction_count"]), int(row["branching_factor"])
        expected = analytic.summary(n, k, tx_size)
        for field in ("tree_height", "internal_node_count", "construction_hash_calls_total"):
            if int(row[field]) != expected[field]:
                problems.append(f"analytic mismatch at N={n}, k={k}, field={field}")

    # --- observed proof bytes match the analytical prediction ---
    if not proof.empty:
        merged = proof.merge(
            analytic_df[
                ["transaction_count", "branching_factor", "sampled_mean_serialized_bytes"]
            ],
            on=["transaction_count", "branching_factor"],
            how="left",
        )
        delta = (
            merged["mean_serialized_bytes"] - merged["sampled_mean_serialized_bytes"]
        ).abs()
        if (delta > 1e-6).any():
            problems.append("measured proof sizes disagree with the analytical model")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir")
    args = parser.parse_args()

    problems = validate(args.raw_dir)
    if problems:
        print(f"VALIDATION FAILED ({len(problems)} problems)")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"VALIDATION PASSED: {args.raw_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
