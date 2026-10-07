#!/usr/bin/env python3
"""Generate the four paper figures from processed results.

The figure budget is four (research plan, Section 21); the 10-page limit
cannot absorb more. Nothing here hardcodes a conclusion: every figure is
drawn from the processed CSVs.

Each figure is written as PDF, PNG, and a 600-dpi JPG submission source.
"""

from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

CONTROL = "nullhash"
HASH_LABEL = {
    "sha256": "SHA-256",
    "sha3_256": "SHA3-256",
    "blake2s": "BLAKE2s-256",
    CONTROL: "null-hash control",
}
K_COLORS = {2: "#1b4965", 3: "#2a9d8f", 4: "#e9c46a", 8: "#f4a261", 16: "#c1436d", 32: "#6a4c93"}

plt.rcParams.update({
    "font.family": "Times New Roman",
    "font.size": 8,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
    "figure.dpi": 150,
})


def save(fig, out_dir: str, name: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for ext in ("pdf", "png", "jpg"):
        fig.savefig(
            os.path.join(out_dir, f"{name}.{ext}"),
            bbox_inches="tight",
            dpi=600 if ext in {"png", "jpg"} else None,
        )
    plt.close(fig)
    print(f"  wrote {name}.pdf / .png / .jpg")


def fig_construction_latency(build: pd.DataFrame, out_dir: str) -> None:
    """Figure 1: construction latency vs N, with the interpreter floor shown."""
    hashes = [h for h in ("sha256", "sha3_256", "blake2s") if h in set(build["hash_algorithm"])]
    fig, axes = plt.subplots(1, len(hashes), figsize=(3.0 * len(hashes), 2.9),
                             sharey=True, squeeze=False)
    axes = axes[0]

    control = build[build["hash_algorithm"] == CONTROL]

    for ax, hash_name in zip(axes, hashes):
        sub = build[build["hash_algorithm"] == hash_name]
        for k in sorted(sub["branching_factor"].unique()):
            series = sub[sub["branching_factor"] == k].sort_values("transaction_count")
            ax.plot(series["transaction_count"], series["build_total_ns_median"] / 1e6,
                    marker="o", markersize=3, linewidth=1.2,
                    color=K_COLORS.get(k, "#666"), label=f"k={k}")
            ax.fill_between(series["transaction_count"],
                            series["build_total_ns_ci_lo"] / 1e6,
                            series["build_total_ns_ci_hi"] / 1e6,
                            color=K_COLORS.get(k, "#666"), alpha=0.15, linewidth=0)
        if not control.empty:
            floor = control.groupby("transaction_count")["build_total_ns_median"].median()
            ax.plot(floor.index, floor.to_numpy() / 1e6, linestyle=":", color="#444",
                    linewidth=1.2, label="control")
        ax.set_xscale("log", base=2)
        ax.set_yscale("log")
        ax.xaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"$2^{{{int(np.log2(v))}}}$")
        )
        ax.set_title(HASH_LABEL.get(hash_name, hash_name))
        ax.set_xlabel("transactions $N$")

    axes[0].set_ylabel("construction latency (ms)")
    axes[-1].legend(loc="upper left", fontsize=7, ncol=2)
    fig.tight_layout()
    save(fig, out_dir, "fig1_construction_latency")


def _pareto_front(points: np.ndarray) -> np.ndarray:
    """Indices of non-dominated points; both axes are minimised."""
    front = []
    for i, point in enumerate(points):
        no_worse = np.all(points <= point, axis=1)
        strictly_better = np.any(points < point, axis=1)
        if not np.any(no_worse & strictly_better):
            front.append(i)
    return np.asarray(front, dtype=int)


def fig_tradeoff(proof: pd.DataFrame, population: pd.DataFrame, out_dir: str) -> None:
    """Figure 2: proof size against verification latency, with Pareto frontier.

    Two axes only. A third, noisy axis would leave nearly every configuration
    non-dominated and the frontier uninformative.
    """
    n = int(proof["transaction_count"].max())
    merged = proof[proof["transaction_count"] == n].merge(
        population[population["transaction_count"] == n],
        on=["transaction_count", "branching_factor"],
    )
    merged = merged[merged["hash_algorithm"] != CONTROL]
    if merged.empty:
        return

    fig, ax = plt.subplots(figsize=(4.4, 3.4))
    markers = {"sha256": "o", "sha3_256": "s", "blake2s": "^"}
    for hash_name, group in merged.groupby("hash_algorithm"):
        ax.scatter(group["serialized_mean"],
                   group["proof_verification_ns_median"] / 1e3,
                   s=[10 + 3 * np.log2(k) ** 2 for k in group["branching_factor"]],
                   c=[K_COLORS.get(k, "#666") for k in group["branching_factor"]],
                   marker=markers.get(hash_name, "o"), alpha=0.85, linewidths=0.4,
                   edgecolors="white", label=HASH_LABEL.get(hash_name, hash_name))

    points = merged[["serialized_mean", "proof_verification_ns_median"]].to_numpy()
    front = _pareto_front(points)
    ordered = points[front][np.argsort(points[front][:, 0])]
    ax.plot(ordered[:, 0], ordered[:, 1] / 1e3, color="#222", linewidth=1.0,
            linestyle="--", alpha=0.7, label="Pareto frontier", zorder=0)

    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
        axis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xlabel("mean serialized proof size (bytes)")
    ax.set_ylabel("verification latency (µs)")

    handles, labels = ax.get_legend_handles_labels()
    k_handles = [plt.Line2D([], [], marker="o", linestyle="", color=K_COLORS.get(k, "#666"),
                            markersize=5, label=f"k={k}")
                 for k in sorted(merged["branching_factor"].unique())]
    ax.legend(handles=handles + k_handles, fontsize=7, ncol=2, loc="upper left")
    fig.tight_layout()
    save(fig, out_dir, "fig2_proofsize_vs_verification")


def fig_verification_vs_k(proof: pd.DataFrame, out_dir: str) -> None:
    """Figure 3: does the interior optimum in k predicted by H3 exist?"""
    sub = proof[proof["hash_algorithm"] != CONTROL]
    if sub.empty:
        return
    workloads = sorted(sub["transaction_count"].unique())
    chosen = workloads[-2:] if len(workloads) >= 2 else workloads

    fig, axes = plt.subplots(1, len(chosen), figsize=(3.2 * len(chosen), 2.9),
                             squeeze=False)
    axes = axes[0]
    colors = {"sha256": "#1b4965", "sha3_256": "#c1436d", "blake2s": "#2a9d8f"}

    for ax, n in zip(axes, chosen):
        frame = sub[sub["transaction_count"] == n]
        for hash_name, group in frame.groupby("hash_algorithm"):
            group = group.sort_values("branching_factor")
            ax.errorbar(
                group["branching_factor"], group["proof_verification_ns_median"] / 1e3,
                yerr=[
                    (group["proof_verification_ns_median"] - group["proof_verification_ns_ci_lo"]) / 1e3,
                    (group["proof_verification_ns_ci_hi"] - group["proof_verification_ns_median"]) / 1e3,
                ],
                marker="o", markersize=3.5, linewidth=1.2, capsize=2,
                color=colors.get(hash_name, "#666"),
                label=HASH_LABEL.get(hash_name, hash_name),
            )
        ax.set_xscale("log", base=2)
        ax.set_xticks(sorted(frame["branching_factor"].unique()))
        ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
        ax.set_title(f"$N = {n}$")
        ax.set_xlabel("branching factor $k$")
    axes[0].set_ylabel("verification latency (µs)")
    axes[-1].legend(fontsize=7)
    fig.tight_layout()
    save(fig, out_dir, "fig3_verification_vs_k")


def fig_parity(predictions: pd.DataFrame, out_dir: str) -> None:
    """Figure 4: cost-model predictions against measurements (RQ3, H2)."""
    if predictions.empty:
        return
    metrics = list(predictions["metric"].unique())
    fig, axes = plt.subplots(1, len(metrics), figsize=(3.2 * len(metrics), 3.0),
                             squeeze=False)
    axes = axes[0]
    colors = {"sha256": "#1b4965", "sha3_256": "#c1436d", "blake2s": "#2a9d8f"}
    titles = {"build_total_ns": "construction", "proof_verification_ns": "verification"}

    for ax, metric in zip(axes, metrics):
        frame = predictions[predictions["metric"] == metric]
        for hash_name, group in frame.groupby("hash_algorithm"):
            for split, marker, alpha in (("train", "o", 0.45), ("holdout", "D", 1.0)):
                part = group[group["split"] == split]
                if part.empty:
                    continue
                ax.scatter(part["measured_ns"], part["predicted_ns"],
                           marker=marker, s=26 if split == "holdout" else 14,
                           color=colors.get(hash_name, "#666"), alpha=alpha,
                           edgecolors="white", linewidths=0.4,
                           label=f"{HASH_LABEL.get(hash_name, hash_name)} ({split})")
        lims = [
            min(frame["measured_ns"].min(), frame["predicted_ns"].min()) * 0.8,
            max(frame["measured_ns"].max(), frame["predicted_ns"].max()) * 1.2,
        ]
        ax.plot(lims, lims, color="#222", linewidth=0.8, linestyle="--", zorder=0)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(lims)
        ax.set_ylim(lims)
        ax.set_aspect("equal")
        ax.set_title(titles.get(metric, metric))
        ax.set_xlabel("measured (ns)")
    axes[0].set_ylabel("predicted (ns)")
    axes[-1].legend(fontsize=6, loc="upper left")
    fig.tight_layout()
    save(fig, out_dir, "fig4_cost_model_parity")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("processed_dir")
    parser.add_argument("--raw-dir", default=None,
                        help="raw directory holding analytic_results.csv")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    proc = args.processed_dir
    raw = args.raw_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "results", "raw",
        os.path.basename(os.path.normpath(proc)),
    )
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "results", "figures",
        os.path.basename(os.path.normpath(proc)),
    )

    build = pd.read_csv(os.path.join(proc, "build_summary.csv"))
    proof = pd.read_csv(os.path.join(proc, "proof_summary.csv"))
    population = pd.read_csv(os.path.join(proc, "proof_population.csv"))
    predictions = pd.read_csv(os.path.join(proc, "cost_model_predictions.csv"))
    print(f"figures -> {out}")
    fig_construction_latency(build, out)
    fig_tradeoff(proof, population, out)
    fig_verification_vs_k(proof, out)
    fig_parity(predictions, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
