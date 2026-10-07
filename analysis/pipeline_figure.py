#!/usr/bin/env python3
"""Methods figure: the experiment pipeline and what is timed.

Shows the data path from workload generation to verification, which regions
are inside timed measurement, where the analytically exact counts are taken,
and where the null-hash control substitutes for a real hash implementation.
"""

from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

INK = "#1b2a3a"
TIMED = "#1b4965"
CTRL = "#c1436d"
ANALYTIC = "#2a9d8f"
MUTED = "#6b7785"

plt.rcParams.update({"font.family": "Times New Roman", "font.size": 10})


def box(ax, x, y, w, h, label, sub=None, color=INK, fill="#ffffff", lw=1.4, ls="-"):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.02",
        linewidth=lw, edgecolor=color, facecolor=fill, linestyle=ls, zorder=2))
    ax.text(x + w / 2, y + h / 2 + (0.035 if sub else 0), label, ha="center",
            va="center", fontsize=10.5, color=INK, zorder=3)
    if sub:
        ax.text(x + w / 2, y + h / 2 - 0.05, sub, ha="center", va="center",
                fontsize=8.2, color=MUTED, style="italic", zorder=3)


def arrow(ax, x1, y1, x2, y2, color=INK, ls="-", lw=1.0):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=9,
        linewidth=lw, color=color, linestyle=ls, zorder=1,
        shrinkA=0, shrinkB=0))


def build(out_dir: str) -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.0))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Main experimental path: four large stages readable at journal size.
    w, h, y = 0.19, 0.22, 0.61
    xs = [0.02, 0.275, 0.53, 0.785]
    box(ax, xs[0], y, w, h, "Seeded records")
    box(ax, xs[1], y, w, h, "$k$-ary tree build", color=TIMED)
    box(ax, xs[2], y, w, h, "Generate proof", color=TIMED)
    box(ax, xs[3], y, w, h, "Verify proof", color=TIMED)
    for i in range(3):
        arrow(ax, xs[i] + w, y + h / 2, xs[i + 1], y + h / 2, lw=1.3)

    # Three supporting measurements; each connects to one clear stage.
    by, bh = 0.12, 0.22
    box(ax, 0.03, by, 0.25, bh, "Exact counts",
        color=ANALYTIC, fill="#f0faf8")
    box(ax, 0.375, by, 0.25, bh, "Null-hash control",
        color=CTRL, fill="#fdf2f6", ls="--")
    box(ax, 0.72, by, 0.25, bh, "Held-out prediction",
        color=ANALYTIC, fill="#f0faf8")

    arrow(ax, xs[1] + w / 2, y, 0.155, by + bh,
          color=ANALYTIC, ls=":", lw=1.2)
    arrow(ax, xs[1] + w / 2, y, 0.50, by + bh,
          color=CTRL, ls="--", lw=1.2)
    arrow(ax, xs[3] + w / 2, y, 0.845, by + bh,
          color=ANALYTIC, ls=":", lw=1.2)

    os.makedirs(out_dir, exist_ok=True)
    for ext in ("pdf", "png", "jpg"):
        fig.savefig(os.path.join(out_dir, f"fig0_pipeline.{ext}"),
                    bbox_inches="tight", dpi=600 if ext in {"png", "jpg"} else None)
    plt.close(fig)
    print(f"  wrote fig0_pipeline.pdf / .png / .jpg -> {out_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    build(args.out or os.path.join(root, "results", "figures", "final"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
