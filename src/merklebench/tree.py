"""Generic k-ary Merkle tree.

One implementation serves every branching factor; there are no specialised
k=2/4/8/16 code paths, so measured differences reflect the branching factor
rather than differing implementation quality (research plan, Task 3).

Construction rule (Section 9):

    leaf     = H(0x00 || transaction)
    internal = H(0x01 || encode(k) || encode(r) || c_0 || ... || c_{r-1})

``r`` is the actual child count of the node, ``k`` the configured branching
factor. Binding both separates digests across configurations: without the
arity byte, a 3-child node in a k=8 tree and a 3-child node in a k=4 tree
would share a preimage.

Preimages are fed through chained ``update`` calls so that ``bytes``
concatenation is never timed as hashing work.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import analytic
from .hashing import DIGEST_SIZE, new_hasher

MAX_BRANCHING_FACTOR = 255  # arity and child count are one byte each


@dataclass(frozen=True)
class Workload:
    """A deterministic transaction set held as one contiguous buffer.

    Storing a single ``bytes`` blob rather than a list of per-transaction
    objects keeps the largest workloads affordable: at N = 2^20 and 256-byte
    payloads a list of separate objects costs roughly 300 MB in object
    overhead alone.
    """

    blob: bytes
    transaction_size: int

    @property
    def count(self) -> int:
        return len(self.blob) // self.transaction_size

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> memoryview:
        if not 0 <= index < self.count:
            raise IndexError(index)
        start = index * self.transaction_size
        return memoryview(self.blob)[start : start + self.transaction_size]

    def prefix(self, n: int) -> "Workload":
        if n > self.count:
            raise ValueError("prefix longer than workload")
        return Workload(self.blob[: n * self.transaction_size], self.transaction_size)


@dataclass
class Tree:
    root: bytes
    levels: list[list[bytes]]
    branching_factor: int
    hash_name: str
    transaction_size: int

    @property
    def leaf_count(self) -> int:
        return len(self.levels[0])

    @property
    def height(self) -> int:
        return len(self.levels) - 1

    @property
    def internal_node_count(self) -> int:
        return sum(len(level) for level in self.levels[1:])


def _check_branching_factor(k: int) -> None:
    if not 2 <= k <= MAX_BRANCHING_FACTOR:
        raise ValueError(f"branching factor must be in [2, {MAX_BRANCHING_FACTOR}]")


def build_leaves(workload: Workload, hash_name: str) -> list[bytes]:
    """Domain-separated leaf digests. Independent of branching factor."""
    leaves = []
    append = leaves.append
    size = workload.transaction_size
    blob = workload.blob
    for start in range(0, len(blob), size):
        h = new_hasher(hash_name)
        h.update(analytic.LEAF_PREFIX)
        h.update(blob[start : start + size])
        append(h.digest())
    return leaves


def build_internal(leaves: list[bytes], branching_factor: int, hash_name: str):
    """Build internal levels from precomputed leaf digests.

    Returns ``(root, levels)`` where ``levels[0]`` is ``leaves``.
    """
    _check_branching_factor(branching_factor)
    if not leaves:
        raise ValueError("at least one leaf is required")

    k = branching_factor
    arity_byte = bytes((k,))
    prefix = analytic.INTERNAL_PREFIX
    levels = [leaves]
    current = leaves

    while len(current) > 1:
        parents = []
        append = parents.append
        for start in range(0, len(current), k):
            group = current[start : start + k]
            h = new_hasher(hash_name)
            h.update(prefix)
            h.update(arity_byte)
            h.update(bytes((len(group),)))
            for child in group:
                h.update(child)
            append(h.digest())
        levels.append(parents)
        current = parents

    return current[0], levels


def build_tree(
    workload: Workload,
    branching_factor: int,
    hash_name: str,
    leaves: list[bytes] | None = None,
) -> Tree:
    """Full construction. Pass ``leaves`` to skip leaf hashing (Mode B)."""
    if leaves is None:
        leaves = build_leaves(workload, hash_name)
    root, levels = build_internal(leaves, branching_factor, hash_name)
    return Tree(
        root=root,
        levels=levels,
        branching_factor=branching_factor,
        hash_name=hash_name,
        transaction_size=workload.transaction_size,
    )


def measured_counts(tree: Tree) -> dict:
    """Counts read back off the constructed tree, for analytical cross-check."""
    n = tree.leaf_count
    k = tree.branching_factor
    internal_bytes = 0
    for children, parents in zip(tree.levels, tree.levels[1:]):
        internal_bytes += len(parents) * analytic.INTERNAL_HEADER_BYTES
        internal_bytes += len(children) * DIGEST_SIZE
    return {
        "tree_height": tree.height,
        "internal_node_count": tree.internal_node_count,
        "construction_hash_calls_total": n + tree.internal_node_count,
        "construction_bytes_internal": internal_bytes,
    }
