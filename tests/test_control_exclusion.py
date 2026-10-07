"""The null-hash control must never pass for a real commitment."""

import pytest

from merklebench.hashing import (
    CONTROL_ALGORITHMS,
    CRYPTO_ALGORITHMS,
    NullHashError,
    is_control,
    new_hasher,
    require_cryptographic,
)
from merklebench.proof import generate_proof, serialize, verify_proof
from merklebench.tree import build_tree
from merklebench.workload import generate


def test_control_is_not_in_the_cryptographic_set():
    assert set(CONTROL_ALGORITHMS).isdisjoint(CRYPTO_ALGORITHMS)
    assert is_control("nullhash")
    assert not any(is_control(name) for name in CRYPTO_ALGORITHMS)


def test_generate_proof_refuses_the_control():
    w = generate(16, 64, seed=7)
    tree = build_tree(w, 4, "nullhash")
    with pytest.raises(NullHashError):
        generate_proof(tree, 0)


def test_verify_refuses_the_control():
    w = generate(16, 64, seed=7)
    real = build_tree(w, 4, "sha256")
    blob = serialize(generate_proof(real, 0))
    with pytest.raises(NullHashError):
        verify_proof(w[0], blob, real.root, "nullhash", 4)


def test_require_cryptographic_guard():
    with pytest.raises(NullHashError):
        require_cryptographic("nullhash")
    for name in CRYPTO_ALGORITHMS:
        require_cryptographic(name)


def test_control_output_is_constant_and_content_independent():
    a, b = new_hasher("nullhash"), new_hasher("nullhash")
    a.update(b"one")
    b.update(b"completely different")
    assert a.digest() == b.digest()
    assert len(a.digest()) == 32


def test_control_tree_root_carries_no_information():
    """Two different workloads produce the same control root, by design."""
    t1 = build_tree(generate(16, 64, seed=1), 4, "nullhash")
    t2 = build_tree(generate(16, 64, seed=2), 4, "nullhash")
    assert t1.root == t2.root
