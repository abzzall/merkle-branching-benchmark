"""Membership proofs: generation, deterministic serialization, verification.

Wire format (version 1), chosen so that measured proof size reflects
cryptographic overhead rather than text-encoding overhead:

    byte  0      : format version
    bytes 1-2    : number of levels, uint16 big endian
    per level    : 1 byte position
                   1 byte child count r
                   32 * (r - 1) bytes of sibling digests, left to right

Supplied out of band, not carried in the proof: the transaction, the expected
root, the hash identifier, and the branching factor. The verifier must already
know which configuration it is checking against; carrying these in the proof
would let an attacker choose them.

Verification is strict. It rejects unsupported versions, invalid child counts
or positions, sibling counts inconsistent with the child count, wrong digest
lengths, truncated input, and trailing bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import analytic
from .hashing import DIGEST_SIZE, new_hasher, require_cryptographic
from .tree import MAX_BRANCHING_FACTOR, Tree

PROOF_VERSION = 1
MAX_LEVELS = 0xFFFF


class ProofError(ValueError):
    """Raised for any malformed, inconsistent, or unsupported proof."""


@dataclass(frozen=True)
class ProofLevel:
    position: int
    child_count: int
    siblings: tuple[bytes, ...]


@dataclass(frozen=True)
class Proof:
    levels: tuple[ProofLevel, ...]

    @property
    def sibling_count(self) -> int:
        return sum(len(level.siblings) for level in self.levels)

    @property
    def raw_hash_bytes(self) -> int:
        return DIGEST_SIZE * self.sibling_count


def generate_proof(tree: Tree, leaf_index: int) -> Proof:
    """Authentication path for ``leaf_index``."""
    require_cryptographic(tree.hash_name)
    n = tree.leaf_count
    if not 0 <= leaf_index < n:
        raise ProofError("leaf_index out of range")

    k = tree.branching_factor
    levels = []
    idx = leaf_index
    for level in tree.levels[:-1]:
        group_start = (idx // k) * k
        group = level[group_start : group_start + k]
        position = idx - group_start
        siblings = tuple(d for i, d in enumerate(group) if i != position)
        levels.append(ProofLevel(position, len(group), siblings))
        idx //= k
    return Proof(tuple(levels))


def serialize(proof: Proof) -> bytes:
    """Deterministic binary encoding."""
    if len(proof.levels) > MAX_LEVELS:
        raise ProofError("too many levels to encode")
    out = bytearray()
    out.append(PROOF_VERSION)
    out += len(proof.levels).to_bytes(2, "big")
    for level in proof.levels:
        if not 1 <= level.child_count <= MAX_BRANCHING_FACTOR:
            raise ProofError("child count out of encodable range")
        if not 0 <= level.position < level.child_count:
            raise ProofError("position inconsistent with child count")
        if len(level.siblings) != level.child_count - 1:
            raise ProofError("sibling count inconsistent with child count")
        out.append(level.position)
        out.append(level.child_count)
        for sibling in level.siblings:
            if len(sibling) != DIGEST_SIZE:
                raise ProofError("sibling digest has wrong length")
            out += sibling
    return bytes(out)


def deserialize(blob: bytes, branching_factor: int) -> Proof:
    """Parse and structurally validate a serialized proof."""
    if len(blob) < 3:
        raise ProofError("truncated proof header")
    if blob[0] != PROOF_VERSION:
        raise ProofError(f"unsupported proof version {blob[0]}")
    level_count = int.from_bytes(blob[1:3], "big")

    levels = []
    offset = 3
    for _ in range(level_count):
        if offset + 2 > len(blob):
            raise ProofError("truncated level header")
        position = blob[offset]
        child_count = blob[offset + 1]
        offset += 2
        if not 1 <= child_count <= branching_factor:
            raise ProofError("child count outside the configured branching factor")
        if not 0 <= position < child_count:
            raise ProofError("position inconsistent with child count")
        need = DIGEST_SIZE * (child_count - 1)
        if offset + need > len(blob):
            raise ProofError("truncated sibling digests")
        siblings = tuple(
            bytes(blob[offset + i * DIGEST_SIZE : offset + (i + 1) * DIGEST_SIZE])
            for i in range(child_count - 1)
        )
        offset += need
        levels.append(ProofLevel(position, child_count, siblings))

    if offset != len(blob):
        raise ProofError("trailing bytes after proof")
    return Proof(tuple(levels))


def _recompute_root(
    transaction, proof: Proof, hash_name: str, branching_factor: int
) -> bytes:
    h = new_hasher(hash_name)
    h.update(analytic.LEAF_PREFIX)
    h.update(transaction)
    digest = h.digest()

    arity_byte = bytes((branching_factor,))
    for level in proof.levels:
        h = new_hasher(hash_name)
        h.update(analytic.INTERNAL_PREFIX)
        h.update(arity_byte)
        h.update(bytes((level.child_count,)))
        siblings = level.siblings
        position = level.position
        for i in range(level.child_count):
            if i == position:
                h.update(digest)
            else:
                h.update(siblings[i if i < position else i - 1])
        digest = h.digest()
    return digest


def verify_proof(
    transaction,
    proof_blob: bytes,
    expected_root: bytes,
    hash_name: str,
    branching_factor: int,
    expected_levels: int | None = None,
) -> bool:
    """Strictly verify a serialized proof. Returns False on mismatch.

    Structural defects raise ``ProofError``; a well-formed proof that simply
    does not reconstruct ``expected_root`` returns ``False``.
    """
    require_cryptographic(hash_name)
    if len(expected_root) != DIGEST_SIZE:
        raise ProofError("expected root has wrong length")
    proof = deserialize(proof_blob, branching_factor)
    if expected_levels is not None and len(proof.levels) != expected_levels:
        raise ProofError("unexpected proof depth")
    return _recompute_root(transaction, proof, hash_name, branching_factor) == expected_root


def verify_parsed(
    transaction, proof: Proof, expected_root: bytes, hash_name: str, branching_factor: int
) -> bool:
    """Verify an already-parsed proof, for the timed inner loop."""
    return (
        _recompute_root(transaction, proof, hash_name, branching_factor) == expected_root
    )
