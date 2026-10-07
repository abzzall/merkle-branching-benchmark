#!/usr/bin/env python3
"""Statistical processing: summaries, block-paired contrasts, cost model.

Primary estimator (research plan, Section 19): every configuration appears
exactly once per timing block, so comparisons against the k=2 baseline are
computed as within-block ratios, and the median ratio is bootstrapped across
blocks. This cancels block-level drift and assumes no distribution.

Regression is used only where it is the object of study: the RQ3 cost model
T = a*hash_calls + b*bytes_hashed, calibrated on prespecified training cells
and evaluated by prediction on prespecified held-out cells.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import nnls

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from merklebench.hashing import CONTROL_ALGORITHMS, CRYPTO_ALGORITHMS  # noqa: E402

BOOTSTRAP_SAMPLES = 10000
BOOTSTRAP_SEED = 20260924
GROUP = ["transaction_count", "branching_factor", "hash_algorithm"]


def bootstrap_median_ci(values, samples=BOOTSTRAP_SAMPLES, seed=BOOTSTRAP_SEED):
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return (np.nan, np.nan, np.nan)
    if len(values) == 1:
        return (float(values[0]), float(values[0]), float(values[0]))
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(samples, len(values)), replace=True)
    medians = np.median(draws, axis=1)
    return (
        float(np.median(values)),
        float(np.percentile(medians, 2.5)),
        float(np.percentile(medians, 97.5)),
    )


def summarise(df: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    rows = []
    for keys, group in df.groupby(GROUP):
        row = dict(zip(GROUP, keys))
        row["observations"] = len(group)
        for metric in metrics:
            values = group[metric].to_numpy(dtype=float)
            median, lo, hi = bootstrap_median_ci(values)
            row[f"{metric}_median"] = median
            row[f"{metric}_ci_lo"] = lo
            row[f"{metric}_ci_hi"] = hi
            row[f"{metric}_iqr"] = float(
                np.percentile(values, 75) - np.percentile(values, 25)
            )
            row[f"{metric}_mean"] = float(values.mean())
            row[f"{metric}_sd"] = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        rows.append(row)
    return pd.DataFrame(rows).sort_values(GROUP).reset_index(drop=True)


def paired_ratios(df: pd.DataFrame, metric: str, baseline_k: int = 2) -> pd.DataFrame:
    """Within-block ratio of each k against the baseline, then bootstrap.

    A ratio below 1 means the configuration is faster than binary.
    """
    rows = []
    for (n, hash_name), group in df.groupby(["transaction_count", "hash_algorithm"]):
        pivot = group.pivot_table(
            index="block", columns="branching_factor", values=metric, aggfunc="median"
        )
        if baseline_k not in pivot.columns:
            continue
        base = pivot[baseline_k]
        for k in sorted(pivot.columns):
            ratios = (pivot[k] / base).dropna().to_numpy()
            if len(ratios) == 0:
                continue
            median, lo, hi = bootstrap_median_ci(ratios)
            rows.append(
                {
                    "transaction_count": n,
                    "hash_algorithm": hash_name,
                    "branching_factor": k,
                    "baseline_branching_factor": baseline_k,
                    "metric": metric,
                    "blocks": len(ratios),
                    "ratio_median": median,
                    "ratio_ci_lo": lo,
                    "ratio_ci_hi": hi,
                    "percent_change": (median - 1.0) * 100.0,
                    "significant": not (lo <= 1.0 <= hi),
                }
            )
    return pd.DataFrame(rows)


def control_decomposition(summary: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Split measured latency into interpreter overhead and hashing work.

    The null-hash control runs the identical traversal without hashing, so its
    latency is the interpreter and traversal floor. The remainder is the
    cryptographic component.
    """
    col = f"{metric}_median"
    control = summary[summary["hash_algorithm"].isin(CONTROL_ALGORITHMS)]
    if control.empty:
        return pd.DataFrame()
    control = control.set_index(["transaction_count", "branching_factor"])[col]

    rows = []
    for _, row in summary[summary["hash_algorithm"].isin(CRYPTO_ALGORITHMS)].iterrows():
        key = (row["transaction_count"], row["branching_factor"])
        if key not in control.index:
            continue
        floor = float(control.loc[key])
        total = float(row[col])
        rows.append(
            {
                "transaction_count": row["transaction_count"],
                "branching_factor": row["branching_factor"],
                "hash_algorithm": row["hash_algorithm"],
                "metric": metric,
                "total_ns": total,
                "interpreter_ns": floor,
                "cryptographic_ns": total - floor,
                "interpreter_fraction": floor / total if total else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _fit_nnls(calls, byts, times):
    """Non-negative least squares for T = a*calls + b*bytes.

    Both coefficients are physically non-negative, and the predictors are
    strongly collinear, so an unconstrained fit can return a negative
    per-call cost that is not interpretable.
    """
    design = np.column_stack([np.asarray(calls, float), np.asarray(byts, float)])
    coef, _ = nnls(design, np.asarray(times, float))
    return float(coef[0]), float(coef[1])


def _mape(actual, predicted):
    actual = np.asarray(actual, float)
    predicted = np.asarray(predicted, float)
    return float(np.mean(np.abs((predicted - actual) / actual)) * 100.0)


def fit_cost_model(
    summary: pd.DataFrame,
    analytic_df: pd.DataFrame,
    holdout_cells: list[dict],
    metric: str,
    calls_col: str,
    bytes_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calibrate on training cells, predict prespecified held-out cells."""
    merged = summary.merge(analytic_df, on=["transaction_count", "branching_factor"])
    merged = merged[merged["hash_algorithm"].isin(CRYPTO_ALGORITHMS)].copy()

    held = {(int(c["k"]), int(c["n"])) for c in holdout_cells}
    merged["split"] = [
        "holdout" if (int(r.branching_factor), int(r.transaction_count)) in held else "train"
        for r in merged.itertuples()
    ]

    coef_rows, pred_rows = [], []
    target = f"{metric}_median"

    for hash_name, group in merged.groupby("hash_algorithm"):
        train = group[group["split"] == "train"]
        test = group[group["split"] == "holdout"]
        if len(train) < 2:
            continue

        a, b = _fit_nnls(train[calls_col], train[bytes_col], train[target])

        # bootstrap the coefficients over training cells
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        boot = []
        idx = np.arange(len(train))
        for _ in range(1000):
            pick = rng.choice(idx, size=len(idx), replace=True)
            sub = train.iloc[pick]
            boot.append(_fit_nnls(sub[calls_col], sub[bytes_col], sub[target]))
        boot = np.asarray(boot)

        def predict(frame):
            return a * frame[calls_col].to_numpy(float) + b * frame[bytes_col].to_numpy(float)

        train_pred = predict(train)
        row = {
            "hash_algorithm": hash_name,
            "metric": metric,
            "a_ns_per_hash_call": a,
            "a_ci_lo": float(np.percentile(boot[:, 0], 2.5)),
            "a_ci_hi": float(np.percentile(boot[:, 0], 97.5)),
            "b_ns_per_byte": b,
            "b_ci_lo": float(np.percentile(boot[:, 1], 2.5)),
            "b_ci_hi": float(np.percentile(boot[:, 1], 97.5)),
            "a_over_b": a / b if b else np.nan,
            "training_cells": len(train),
            "train_mape_percent": _mape(train[target], train_pred),
        }
        if len(test):
            test_pred = predict(test)
            row["holdout_cells"] = len(test)
            row["holdout_mape_percent"] = _mape(test[target], test_pred)
        else:
            row["holdout_cells"] = 0
            row["holdout_mape_percent"] = np.nan
        coef_rows.append(row)

        for frame, pred in ((train, train_pred), (test, predict(test) if len(test) else [])):
            for (_, r), p in zip(frame.iterrows(), pred):
                pred_rows.append(
                    {
                        "hash_algorithm": hash_name,
                        "metric": metric,
                        "transaction_count": r["transaction_count"],
                        "branching_factor": r["branching_factor"],
                        "split": r["split"],
                        "measured_ns": r[target],
                        "predicted_ns": p,
                        "relative_error_percent": (p - r[target]) / r[target] * 100.0,
                    }
                )

    return pd.DataFrame(coef_rows), pd.DataFrame(pred_rows)


def population_proof_sizes(analytic_df: pd.DataFrame) -> pd.DataFrame:
    """Exact proof-size distributions over all leaves, not the timing sample.

    Boundary leaves are deliberately over-represented in the latency sample.
    That is useful for coverage but biases population proof size for k=3.
    """
    rows = []
    cells = analytic_df[["transaction_count", "branching_factor"]].drop_duplicates()
    for cell in cells.itertuples(index=False):
        row = {
            "transaction_count": int(cell.transaction_count),
            "branching_factor": int(cell.branching_factor),
        }
        n, k = row["transaction_count"], row["branching_factor"]
        # Vectorised exact enumeration. The core reference implementation is
        # intentionally simple and loops over leaves; doing that for every
        # million-leaf publication cell is needlessly slow.
        indices = np.arange(n, dtype=np.int64)
        sibling_counts = np.zeros(n, dtype=np.int32)
        m = n
        levels = 0
        while m > 1:
            groups = indices // k
            child_counts = np.minimum(k, m - groups * k)
            sibling_counts += child_counts.astype(np.int32) - 1
            indices = groups
            m = (m + k - 1) // k
            levels += 1
        sizes = 3 + 2 * levels + 32 * sibling_counts
        row.update({
            "serialized_min": int(sizes.min()),
            "serialized_median": float(np.median(sizes)),
            "serialized_mean": float(sizes.mean()),
            "serialized_max": int(sizes.max()),
            "siblings_min": int(sibling_counts.min()),
            "siblings_median": float(np.median(sibling_counts)),
            "siblings_mean": float(sibling_counts.mean()),
            "siblings_max": int(sibling_counts.max()),
        })
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["transaction_count", "branching_factor"]
    ).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    raw = args.raw_dir
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "results", "processed",
        os.path.basename(os.path.normpath(raw)),
    )
    os.makedirs(out, exist_ok=True)

    build = pd.read_csv(os.path.join(raw, "build_results.csv"))
    proof = pd.read_csv(os.path.join(raw, "proof_results.csv"))
    analytic_df = pd.read_csv(os.path.join(raw, "analytic_results.csv"))
    with open(os.path.join(raw, "environment.json")) as fh:
        env = json.load(fh)
    cfg = env.get("configuration", {})
    holdout = cfg.get("cost_model", {}).get("holdout_cells", [])
    target_mape = cfg.get("cost_model", {}).get("target_mape_percent")

    build_summary = summarise(build, ["build_total_ns", "build_internal_ns",
                                      "build_throughput_tx_per_sec"])
    proof_summary = summarise(proof, ["proof_generation_ns", "proof_verification_ns"])
    build_summary.to_csv(os.path.join(out, "build_summary.csv"), index=False)
    proof_summary.to_csv(os.path.join(out, "proof_summary.csv"), index=False)

    proof_population = population_proof_sizes(analytic_df)
    proof_population.to_csv(os.path.join(out, "proof_population.csv"), index=False)

    ratios = pd.concat(
        [paired_ratios(build, "build_total_ns"),
         paired_ratios(build, "build_internal_ns"),
         paired_ratios(proof, "proof_verification_ns")],
        ignore_index=True,
    )
    ratios.to_csv(os.path.join(out, "paired_ratios.csv"), index=False)

    decomposition = pd.concat(
        [control_decomposition(build_summary, "build_total_ns"),
         control_decomposition(build_summary, "build_internal_ns")],
        ignore_index=True,
    )
    decomposition.to_csv(os.path.join(out, "control_decomposition.csv"), index=False)

    coef_build, pred_build = fit_cost_model(
        build_summary, analytic_df, holdout, "build_total_ns",
        "construction_hash_calls_total", "construction_bytes_total",
    )
    coef_verify, pred_verify = fit_cost_model(
        proof_summary, analytic_df, holdout, "proof_verification_ns",
        "sampled_mean_verification_hash_calls", "sampled_mean_verification_bytes",
    )
    coefficients = pd.concat([coef_build, coef_verify], ignore_index=True)
    predictions = pd.concat([pred_build, pred_verify], ignore_index=True)
    coefficients.to_csv(os.path.join(out, "cost_model_coefficients.csv"), index=False)
    predictions.to_csv(os.path.join(out, "cost_model_predictions.csv"), index=False)

    # Residuals broken down by branching factor. The parity plot spans two
    # orders of magnitude in N, so a tight overall fit can hide systematic
    # failure to capture the k-effect, which is the subtle part. If relative
    # error is structured in k, the model is tracking workload scaling rather
    # than branching behaviour and must be reported as such.
    if not predictions.empty:
        residuals = (
            predictions.groupby(["metric", "hash_algorithm", "branching_factor"])
            ["relative_error_percent"]
            .agg(["mean", "std", "count"])
            .reset_index()
            .rename(columns={"mean": "mean_error_percent",
                             "std": "sd_error_percent", "count": "cells"})
        )
        residuals.to_csv(os.path.join(out, "cost_model_residuals_by_k.csv"), index=False)

    report = {
        "raw_dir": os.path.abspath(raw),
        "run_id": env.get("run_id"),
        "target_mape_percent": target_mape,
        "holdout_cells": holdout,
        "cost_model": coefficients.to_dict(orient="records"),
    }
    with open(os.path.join(out, "processing_report.json"), "w") as fh:
        json.dump(report, fh, indent=2, default=str)

    print(f"processed -> {out}")
    for _, row in coefficients.iterrows():
        print(
            f"  {row['metric']:<22} {row['hash_algorithm']:<9} "
            f"a={row['a_ns_per_hash_call']:.1f} ns/call  "
            f"b={row['b_ns_per_byte']:.4f} ns/byte  "
            f"train MAPE={row['train_mape_percent']:.1f}%  "
            f"holdout MAPE={row['holdout_mape_percent']:.1f}%"
        )
    if not predictions.empty:
        print()
        print("mean relative error by branching factor (structure here means the")
        print("model tracks workload scaling rather than the k-effect):")
        table = predictions.pivot_table(
            index=["metric", "branching_factor"], columns="hash_algorithm",
            values="relative_error_percent", aggfunc="mean",
        )
        print(table.round(2).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
