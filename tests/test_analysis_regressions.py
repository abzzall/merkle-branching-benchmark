"""Regression tests for publication-analysis bugs found during audit."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from plots import _pareto_front  # noqa: E402
from process import population_proof_sizes  # noqa: E402
from merklebench.analytic import proof_size_distribution  # noqa: E402


def test_population_proof_sizes_are_not_boundary_sample_sizes():
    cells = pd.DataFrame([{"transaction_count": 4096, "branching_factor": 3}])
    row = population_proof_sizes(cells).iloc[0]
    exact = proof_size_distribution(4096, 3)
    assert row["serialized_mean"] == exact["serialized_mean"]
    assert row["serialized_min"] == 307
    assert row["serialized_max"] == 499


def test_pareto_rejects_slower_point_with_equal_proof_size():
    points = np.array([[683.0, 16.0], [683.0, 14.2], [829.0, 10.2]])
    assert _pareto_front(points).tolist() == [1, 2]
