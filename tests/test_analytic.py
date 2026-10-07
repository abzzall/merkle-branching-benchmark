"""Analytical model cross-checked against actually constructed trees."""

import pytest

from merklebench import analytic
from merklebench.hashing import CRYPTO_ALGORITHMS
from merklebench.tree import build_tree, measured_counts
from merklebench.workload import generate

KS = (2, 3, 4, 8, 16)
TX = 64


def boundary_sizes(k):
    return sorted({1, 2, 3, k - 1, k, k + 1, k * k - 1, k * k, k * k + 1})


@pytest.mark.parametrize("k", KS)
def test_structural_predictions_match_construction(k):
    for n in boundary_sizes(k):
        w = generate(n, TX, seed=1)
        tree = build_tree(w, k, "sha256")
        measured = measured_counts(tree)
        predicted = analytic.summary(n, k, TX)
        assert measured["tree_height"] == predicted["tree_height"], (n, k)
        assert measured["internal_node_count"] == predicted["internal_node_count"]
        assert (
            measured["construction_hash_calls_total"]
            == predicted["construction_hash_calls_total"]
        )
        assert (
            measured["construction_bytes_internal"]
            == predicted["construction_bytes_internal"]
        )


@pytest.mark.parametrize("k", KS)
def test_single_leaf_tree_has_no_internal_levels(k):
    w = generate(1, TX, seed=1)
    tree = build_tree(w, k, "sha256")
    assert tree.height == 0
    assert tree.internal_node_count == 0
    assert analytic.proof_shape(1, k, 0) == []


@pytest.mark.parametrize("k", KS)
def test_height_matches_closed_form(k):
    import math

    for n in (1, 2, 5, 17, 100, 1000):
        expected = 0 if n == 1 else math.ceil(math.log(n, k) - 1e-12)
        assert analytic.height(n, k) == expected, (n, k)


def test_proof_size_increases_monotonically_with_k():
    """Analytical result, not a hypothesis: (k-1)/ln k is strictly increasing."""
    n = 4096
    sizes = [analytic.proof_serialized_bytes(n, k, 0) for k in KS]
    assert sizes == sorted(sizes)
    assert len(set(sizes)) == len(sizes)


@pytest.mark.parametrize("k", KS)
def test_proof_size_distribution_covers_all_leaves(k):
    n = k * k + 1
    dist = analytic.proof_size_distribution(n, k)
    assert dist["serialized_min"] <= dist["serialized_median"]
    assert dist["serialized_median"] <= dist["serialized_max"]
    assert dist["siblings_min"] >= 1


@pytest.mark.parametrize("hash_name", CRYPTO_ALGORITHMS)
def test_leaf_hashing_is_independent_of_branching_factor(hash_name):
    from merklebench.tree import build_leaves

    w = generate(32, TX, seed=1)
    reference = build_leaves(w, hash_name)
    for k in KS:
        tree = build_tree(w, k, hash_name)
        assert tree.levels[0] == reference
