#!/usr/bin/env python3
"""Reviewer-requested re-analysis of the immutable final benchmark data.

This script does not run the benchmark or alter raw results. It produces:

* within-block paired-ratio bootstrap intervals for the key H1 and H3
  contrasts requested by Reviewer C; and
* an exact structural sensitivity summary for the boundary-enriched k=3
  proof sample versus the uniform population of leaves.

The proof timing CSV stores one aggregate timing per configuration and block,
not per-leaf timings. Consequently, the structural sensitivity output must not
be described as a boundary-versus-uniform latency estimate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
CODE_ROOT = HERE.parent
sys.path.insert(0, str(CODE_ROOT / "src"))
sys.path.insert(0, str(HERE))

from merklebench import analytic  # noqa: E402
from merklebench.workload import proof_indices  # noqa: E402
from process import BOOTSTRAP_SAMPLES, BOOTSTRAP_SEED, bootstrap_median_ci  # noqa: E402

REAL_HASHES = ("blake2s", "sha256", "sha3_256")
TRANSACTION_SIZE_BYTES = 256


def paired_contrast(
    frame: pd.DataFrame,
    metric: str,
    numerator_k: int,
    denominator_k: int,
    hypothesis: str,
) -> pd.DataFrame:
    """Return block-paired numerator/denominator ratios with bootstrap CIs."""
    rows = []
    subset = frame[frame["hash_algorithm"].isin(REAL_HASHES)]
    for (n, hash_name), group in subset.groupby(
        ["transaction_count", "hash_algorithm"]
    ):
        pivot = group.pivot_table(
            index="block", columns="branching_factor", values=metric, aggfunc="median"
        )
        if numerator_k not in pivot or denominator_k not in pivot:
            continue
        ratios = (pivot[numerator_k] / pivot[denominator_k]).dropna().to_numpy()
        median, lo, hi = bootstrap_median_ci(ratios)
        rows.append(
            {
                "hypothesis": hypothesis,
                "transaction_count": int(n),
                "hash_algorithm": hash_name,
                "metric": metric,
                "numerator_k": numerator_k,
                "denominator_k": denominator_k,
                "blocks": len(ratios),
                "ratio_median": median,
                "ratio_ci_lo": lo,
                "ratio_ci_hi": hi,
                "percent_change": 100.0 * (median - 1.0),
                "ci_excludes_1": not (lo <= 1.0 <= hi),
                "bootstrap_samples": BOOTSTRAP_SAMPLES,
                "bootstrap_seed": BOOTSTRAP_SEED,
            }
        )
    return pd.DataFrame(rows)


def key_contrasts(build: pd.DataFrame, proof: pd.DataFrame) -> pd.DataFrame:
    tables = []
    for k in (3, 4, 8, 16):
        tables.append(paired_contrast(build, "build_total_ns", k, 2, "H1"))
    # k=8 must beat both adjacent tested choices to support an interior minimum;
    # k=2 is retained because it is the manuscript's standard baseline.
    for denominator in (2, 4, 16):
        tables.append(
            paired_contrast(proof, "proof_verification_ns", 8, denominator, "H3")
        )
    return (
        pd.concat(tables, ignore_index=True)
        .sort_values(
            [
                "hypothesis",
                "transaction_count",
                "hash_algorithm",
                "denominator_k",
                "numerator_k",
            ]
        )
        .reset_index(drop=True)
    )


def _structural_means(n: int, k: int, indices) -> tuple[float, float, float]:
    indices = list(indices)
    proof_bytes = [analytic.proof_serialized_bytes(n, k, i) for i in indices]
    calls = [analytic.verification_hash_calls(n, k, i) for i in indices]
    hashed_bytes = [
        analytic.verification_bytes_hashed(n, k, i, TRANSACTION_SIZE_BYTES)
        for i in indices
    ]
    count = float(len(indices))
    return (
        sum(proof_bytes) / count,
        sum(calls) / count,
        sum(hashed_bytes) / count,
    )


def k3_structural_sensitivity(
    transaction_counts: list[int], sample_count: int, proof_seed: int
) -> pd.DataFrame:
    rows = []
    k = 3
    for n in transaction_counts:
        sampled = proof_indices(n, sample_count, proof_seed)
        boundary = list(dict.fromkeys((0, 1, n // 2, n - 2, n - 1)))
        populations = {
            "boundary_enriched_sample": sampled,
            "mandatory_boundary_leaves": boundary,
            "uniform_leaf_population": range(n),
        }
        uniform = _structural_means(n, k, range(n))
        for design, indices in populations.items():
            values = _structural_means(n, k, indices)
            row = {
                "transaction_count": n,
                "branching_factor": k,
                "index_design": design,
                "leaf_count": len(indices),
                "mean_serialized_bytes": values[0],
                "mean_verification_hash_calls": values[1],
                "mean_verification_hashed_bytes": values[2],
            }
            for label, value, baseline in zip(
                ("serialized_bytes", "verification_hash_calls", "verification_hashed_bytes"),
                values,
                uniform,
            ):
                row[f"{label}_percent_vs_uniform"] = 100.0 * (value / baseline - 1.0)
            rows.append(row)
    return pd.DataFrame(rows)


def write_largest_workload_markdown(contrasts: pd.DataFrame, path: Path) -> None:
    largest = contrasts["transaction_count"].max()
    table = contrasts[contrasts["transaction_count"] == largest].copy()
    table["contrast"] = (
        "k=" + table["numerator_k"].astype(str) + " / k=" + table["denominator_k"].astype(str)
    )
    table["ratio [95% CI]"] = table.apply(
        lambda r: f"{r.ratio_median:.4f} [{r.ratio_ci_lo:.4f}, {r.ratio_ci_hi:.4f}]",
        axis=1,
    )
    columns = (
        "hypothesis",
        "hash_algorithm",
        "metric",
        "contrast",
        "ratio [95% CI]",
        "percent change",
    )
    body = []
    for _, row in table.iterrows():
        body.append(
            "| "
            + " | ".join(
                (
                    str(row["hypothesis"]),
                    str(row["hash_algorithm"]),
                    str(row["metric"]),
                    str(row["contrast"]),
                    str(row["ratio [95% CI]"]),
                    f"{row['percent_change']:.1f}%",
                )
            )
            + " |"
        )
    lines = [
        "# Reviewer CI table — largest workload",
        "",
        f"N = {largest}. Ratios are medians of within-block paired ratios; intervals are",
        f"95% percentile bootstrap intervals using {BOOTSTRAP_SAMPLES:,} resamples and seed {BOOTSTRAP_SEED}.",
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
        *body,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=CODE_ROOT / "results/raw/final")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=CODE_ROOT / "results/processed/reviewer_revision",
    )
    parser.add_argument("--proof-sample-count", type=int, default=16)
    parser.add_argument("--proof-seed", type=int, default=20260923)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    build = pd.read_csv(args.raw_dir / "build_results.csv")
    proof = pd.read_csv(args.raw_dir / "proof_results.csv")

    contrasts = key_contrasts(build, proof)
    contrasts.to_csv(args.output_dir / "key_paired_ratio_intervals.csv", index=False)
    write_largest_workload_markdown(
        contrasts, args.output_dir / "key_paired_ratio_intervals_largest_workload.md"
    )

    counts = sorted(int(n) for n in proof["transaction_count"].unique())
    sensitivity = k3_structural_sensitivity(
        counts, args.proof_sample_count, args.proof_seed
    )
    sensitivity.to_csv(args.output_dir / "k3_structural_sample_sensitivity.csv", index=False)

    print(f"Wrote {len(contrasts)} paired contrasts to {args.output_dir}")
    print(f"Wrote {len(sensitivity)} structural sensitivity rows to {args.output_dir}")


if __name__ == "__main__":
    main()
