"""Correctness, tamper detection, malformed input, and isolation tests.

The non-cryptographic control is deliberately absent from every test in this
file except the explicit exclusion tests.
"""

import pytest

from merklebench import analytic
from merklebench.hashing import CRYPTO_ALGORITHMS, DIGEST_SIZE
from merklebench.proof import (
    ProofError,
    deserialize,
    generate_proof,
    serialize,
    verify_proof,
)
from merklebench.tree import build_tree
from merklebench.workload import generate

KS = (2, 3, 4, 8, 16)
TX = 64


def boundary_sizes(k):
    return sorted({1, 2, 3, k - 1, k, k + 1, k * k - 1, k * k, k * k + 1})


@pytest.mark.parametrize("hash_name", CRYPTO_ALGORITHMS)
@pytest.mark.parametrize("k", KS)
def test_every_leaf_of_small_trees_verifies(hash_name, k):
    for n in boundary_sizes(k):
        w = generate(n, TX, seed=7)
        tree = build_tree(w, k, hash_name)
        for i in range(n):
            blob = serialize(generate_proof(tree, i))
            assert verify_proof(w[i], blob, tree.root, hash_name, k), (n, k, i)


@pytest.mark.parametrize("k", KS)
def test_serialized_size_matches_analytical_prediction(k):
    for n in boundary_sizes(k):
        w = generate(n, TX, seed=7)
        tree = build_tree(w, k, "sha256")
        for i in range(n):
            blob = serialize(generate_proof(tree, i))
            assert len(blob) == analytic.proof_serialized_bytes(n, k, i)


@pytest.mark.parametrize("k", (2, 3, 4, 8))
def test_tampered_transaction_is_rejected(k):
    n = k * k + 1
    w = generate(n, TX, seed=7)
    tree = build_tree(w, k, "sha256")
    blob = serialize(generate_proof(tree, 2))
    forged = bytearray(w[2])
    forged[0] ^= 0x01
    assert not verify_proof(bytes(forged), blob, tree.root, "sha256", k)


@pytest.mark.parametrize("k", (3, 4, 8))
def test_tampered_sibling_is_rejected(k):
    n = k * k + 1
    w = generate(n, TX, seed=7)
    tree = build_tree(w, k, "sha256")
    blob = bytearray(serialize(generate_proof(tree, 2)))
    blob[5] ^= 0x01  # inside the first sibling digest
    assert not verify_proof(w[2], bytes(blob), tree.root, "sha256", k)


@pytest.mark.parametrize("k", KS)
def test_tampered_root_is_rejected(k):
    n = k * k + 1
    w = generate(n, TX, seed=7)
    tree = build_tree(w, k, "sha256")
    blob = serialize(generate_proof(tree, 2))
    forged = bytearray(tree.root)
    forged[0] ^= 0x01
    assert not verify_proof(w[2], blob, bytes(forged), "sha256", k)


@pytest.mark.parametrize("k", (3, 4, 8))
def test_proof_of_wrong_leaf_is_rejected(k):
    n = k * k + 1
    w = generate(n, TX, seed=7)
    tree = build_tree(w, k, "sha256")
    blob = serialize(generate_proof(tree, 2))
    assert not verify_proof(w[3], blob, tree.root, "sha256", k)


def test_cross_hash_isolation():
    n = 17
    w = generate(n, TX, seed=7)
    tree_a = build_tree(w, 4, "sha256")
    tree_b = build_tree(w, 4, "sha3_256")
    blob = serialize(generate_proof(tree_a, 5))
    assert not verify_proof(w[5], blob, tree_b.root, "sha3_256", 4)
    assert tree_a.root != tree_b.root


def test_arity_binding_separates_roots():
    """k is bound into the internal preimage, so identical child groups under
    different branching factors still commit to different roots."""
    n = 3  # a single internal node with 3 children under either k
    w = generate(n, TX, seed=7)
    tree_4 = build_tree(w, 4, "sha256")
    tree_8 = build_tree(w, 8, "sha256")
    assert tree_4.root != tree_8.root


@pytest.mark.parametrize("n", (3, 9, 17, 65))
def test_cross_arity_isolation(n):
    """A proof issued under one branching factor must not verify, under its
    own configuration, against a root built with a different one."""
    w = generate(n, TX, seed=7)
    tree_4 = build_tree(w, 4, "sha256")
    tree_8 = build_tree(w, 8, "sha256")
    blob = serialize(generate_proof(tree_4, 1))
    assert verify_proof(w[1], blob, tree_4.root, "sha256", 4)
    assert not verify_proof(w[1], blob, tree_8.root, "sha256", 4)


def test_differing_tree_shapes_reject_transplanted_proofs():
    """Where the two configurations also differ structurally, a transplanted
    proof fails even when the verifier uses the foreign branching factor."""
    n = 9  # k=4 -> levels [9,3,1]; k=8 -> levels [9,2,1]
    w = generate(n, TX, seed=7)
    tree_4 = build_tree(w, 4, "sha256")
    tree_8 = build_tree(w, 8, "sha256")
    blob = serialize(generate_proof(tree_4, 1))
    assert not verify_proof(w[1], blob, tree_8.root, "sha256", 8)


def test_rejects_unsupported_version():
    blob = bytearray(b"\x01\x00\x00")
    blob[0] = 9
    with pytest.raises(ProofError, match="unsupported proof version"):
        deserialize(bytes(blob), 4)


def test_rejects_truncated_header():
    with pytest.raises(ProofError, match="truncated proof header"):
        deserialize(b"\x01\x00", 4)


def test_rejects_truncated_siblings():
    w = generate(9, TX, seed=7)
    tree = build_tree(w, 3, "sha256")
    blob = serialize(generate_proof(tree, 0))
    with pytest.raises(ProofError, match="truncated"):
        deserialize(blob[:-1], 3)


def test_rejects_trailing_bytes():
    w = generate(9, TX, seed=7)
    tree = build_tree(w, 3, "sha256")
    blob = serialize(generate_proof(tree, 0))
    with pytest.raises(ProofError, match="trailing bytes"):
        deserialize(blob + b"\x00", 3)


def test_rejects_child_count_above_branching_factor():
    w = generate(9, TX, seed=7)
    tree = build_tree(w, 3, "sha256")
    blob = bytearray(serialize(generate_proof(tree, 0)))
    blob[4] = 9  # child_count of the first level
    with pytest.raises(ProofError, match="child count outside"):
        deserialize(bytes(blob), 3)


def test_rejects_position_beyond_child_count():
    w = generate(9, TX, seed=7)
    tree = build_tree(w, 3, "sha256")
    blob = bytearray(serialize(generate_proof(tree, 0)))
    blob[3] = 3  # position == child_count
    with pytest.raises(ProofError, match="position inconsistent"):
        deserialize(bytes(blob), 3)


def test_rejects_unexpected_depth():
    w = generate(9, TX, seed=7)
    tree = build_tree(w, 3, "sha256")
    blob = serialize(generate_proof(tree, 0))
    with pytest.raises(ProofError, match="unexpected proof depth"):
        verify_proof(w[0], blob, tree.root, "sha256", 3, expected_levels=5)


def test_rejects_wrong_root_length():
    w = generate(9, TX, seed=7)
    tree = build_tree(w, 3, "sha256")
    blob = serialize(generate_proof(tree, 0))
    with pytest.raises(ProofError, match="expected root has wrong length"):
        verify_proof(w[0], blob, tree.root[:-1], "sha256", 3)


def test_serialization_is_deterministic():
    w = generate(50, TX, seed=7)
    tree = build_tree(w, 4, "sha256")
    for i in (0, 7, 49):
        assert serialize(generate_proof(tree, i)) == serialize(generate_proof(tree, i))


@pytest.mark.parametrize("hash_name", CRYPTO_ALGORITHMS)
def test_root_is_deterministic(hash_name):
    w = generate(100, TX, seed=7)
    assert build_tree(w, 4, hash_name).root == build_tree(w, 4, hash_name).root


def test_out_of_range_leaf_index():
    w = generate(5, TX, seed=7)
    tree = build_tree(w, 4, "sha256")
    with pytest.raises(ProofError):
        generate_proof(tree, 5)


def test_digest_sizes_are_uniform():
    w = generate(20, TX, seed=7)
    for hash_name in CRYPTO_ALGORITHMS:
        tree = build_tree(w, 4, hash_name)
        assert len(tree.root) == DIGEST_SIZE
