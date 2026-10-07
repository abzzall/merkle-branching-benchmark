"""Exact structural cost model for k-ary Merkle trees.

Every quantity here is deterministic: it is computed once per configuration
rather than measured repeatedly (research plan, Section 19). These functions
are the predictors used by the RQ3 cost model and are cross-checked against
the constructed trees by the test suite.

Construction rule (Section 9):

    leaf     = H(0x00 || transaction)
    internal = H(0x01 || encode(k) || encode(r) || c_0 || ... || c_{r-1})

where ``r`` is the actual number of children (1 <= r <= k). Every consecutive
group of one to k children produces a parent; nodes are never promoted
unhashed. For N = 1 the root is the domain-separated leaf digest and the tree
has zero internal levels.
"""

from __future__ import annotations

from .hashing import DIGEST_SIZE

LEAF_PREFIX = b"\x00"
INTERNAL_PREFIX = b"\x01"

#: internal preimage overhead: prefix byte + arity byte + child-count byte
INTERNAL_HEADER_BYTES = 3


def level_sizes(n: int, k: int) -> list[int]:
    """Node counts per level, leaves first, root last."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if k < 2:
        raise ValueError("k must be >= 2")
    sizes = [n]
    while sizes[-1] > 1:
        m = sizes[-1]
        sizes.append((m + k - 1) // k)
    return sizes


def height(n: int, k: int) -> int:
    """Number of internal levels; 0 when N == 1."""
    return len(level_sizes(n, k)) - 1


def internal_node_count(n: int, k: int) -> int:
    return sum(level_sizes(n, k)[1:])


def construction_hash_calls(n: int, k: int) -> dict:
    internal = internal_node_count(n, k)
    return {"leaf": n, "internal": internal, "total": n + internal}


def construction_bytes_hashed(n: int, k: int, tx_size: int) -> dict:
    """Bytes fed to the hash functions during construction."""
    leaf_bytes = n * (len(LEAF_PREFIX) + tx_size)
    sizes = level_sizes(n, k)
    internal_bytes = 0
    for children, parents in zip(sizes, sizes[1:]):
        # each parent contributes a 3-byte header; every child digest is
        # consumed exactly once at this transition
        internal_bytes += parents * INTERNAL_HEADER_BYTES
        internal_bytes += children * DIGEST_SIZE
    return {
        "leaf": leaf_bytes,
        "internal": internal_bytes,
        "total": leaf_bytes + internal_bytes,
    }


def analytical_memory_bytes(n: int, k: int) -> dict:
    """Exact digest storage, the primary memory metric (Section 14)."""
    internal = internal_node_count(n, k)
    return {
        "leaf_digest_bytes": n * DIGEST_SIZE,
        "internal_digest_bytes": internal * DIGEST_SIZE,
        "total_digest_bytes": (n + internal) * DIGEST_SIZE,
    }


def proof_shape(n: int, k: int, leaf_index: int) -> list[tuple[int, int]]:
    """Per-level ``(position, child_count)`` for the proof of ``leaf_index``.

    Proof shape varies by leaf position because the final group of a level may
    be incomplete.
    """
    if not 0 <= leaf_index < n:
        raise ValueError("leaf_index out of range")
    shape = []
    idx = leaf_index
    for m in level_sizes(n, k)[:-1]:
        group = idx // k
        child_count = min(k, m - group * k)
        shape.append((idx % k, child_count))
        idx = group
    return shape


def proof_sibling_count(n: int, k: int, leaf_index: int) -> int:
    return sum(r - 1 for _, r in proof_shape(n, k, leaf_index))


def proof_raw_hash_bytes(n: int, k: int, leaf_index: int) -> int:
    return DIGEST_SIZE * proof_sibling_count(n, k, leaf_index)


def proof_serialized_bytes(n: int, k: int, leaf_index: int) -> int:
    """Byte length of the wire format defined in ``proof.py``."""
    shape = proof_shape(n, k, leaf_index)
    total = 1 + 2  # version byte + level count (uint16 big endian)
    for _, child_count in shape:
        total += 2 + DIGEST_SIZE * (child_count - 1)
    return total


def verification_hash_calls(n: int, k: int, leaf_index: int) -> int:
    """One leaf hash plus one internal hash per proof level."""
    return 1 + len(proof_shape(n, k, leaf_index))


def verification_bytes_hashed(n: int, k: int, leaf_index: int, tx_size: int) -> int:
    total = len(LEAF_PREFIX) + tx_size
    for _, child_count in proof_shape(n, k, leaf_index):
        total += INTERNAL_HEADER_BYTES + child_count * DIGEST_SIZE
    return total


def proof_size_distribution(n: int, k: int) -> dict:
    """Exact distribution of proof size over every leaf position.

    Cheap because it depends only on position arithmetic, not on hashing.
    """
    sizes = [proof_serialized_bytes(n, k, i) for i in range(n)]
    siblings = [proof_sibling_count(n, k, i) for i in range(n)]
    sizes.sort()
    siblings.sort()

    def median(xs):
        m = len(xs) // 2
        return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2

    return {
        "serialized_min": sizes[0],
        "serialized_median": median(sizes),
        "serialized_mean": sum(sizes) / len(sizes),
        "serialized_max": sizes[-1],
        "siblings_min": siblings[0],
        "siblings_median": median(siblings),
        "siblings_mean": sum(siblings) / len(siblings),
        "siblings_max": siblings[-1],
    }


def summary(n: int, k: int, tx_size: int) -> dict:
    """All deterministic quantities for one (N, k) configuration."""
    calls = construction_hash_calls(n, k)
    byts = construction_bytes_hashed(n, k, tx_size)
    mem = analytical_memory_bytes(n, k)
    return {
        "transaction_count": n,
        "branching_factor": k,
        "transaction_size_bytes": tx_size,
        "tree_height": height(n, k),
        "internal_node_count": internal_node_count(n, k),
        "construction_hash_calls_leaf": calls["leaf"],
        "construction_hash_calls_internal": calls["internal"],
        "construction_hash_calls_total": calls["total"],
        "construction_bytes_leaf": byts["leaf"],
        "construction_bytes_internal": byts["internal"],
        "construction_bytes_total": byts["total"],
        "analytical_digest_bytes": mem["total_digest_bytes"],
    }
