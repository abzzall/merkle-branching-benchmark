"""Hash implementations under test, plus the non-cryptographic control.

Every registered implementation exposes the same incremental interface so the
traversal code path is byte-for-byte identical across factor levels:

    h = new_hasher(name)
    h.update(b"...")      # called once per preimage component
    digest = h.digest()   # exactly DIGEST_SIZE bytes

Preimages are assembled by chaining ``update`` calls rather than joining bytes
and hashing once, so that ``bytes`` allocation is not timed as hashing work
(research plan, Section 6).
"""

from __future__ import annotations

import hashlib

DIGEST_SIZE = 32

#: Cryptographic implementations actually under study.
CRYPTO_ALGORITHMS = ("sha256", "sha3_256", "blake2s")

#: Instrumentation control. Not a hash function; see NullHash.
CONTROL_ALGORITHMS = ("nullhash",)

ALL_ALGORITHMS = CRYPTO_ALGORITHMS + CONTROL_ALGORITHMS


class NullHashError(RuntimeError):
    """Raised when the control is used where a real commitment is required."""


class NullHash:
    """Fixed-output stand-in that performs no hashing work.

    This exists solely to isolate interpreter and traversal overhead from
    cryptographic cost. At k=16 an internal node hashes 515 bytes, which costs
    roughly the same as the surrounding Python loop; without this control,
    "construction latency vs k" would substantially measure Python iteration
    count, which is just the analytically known internal-node count.

    ``update`` is a real method call that does no work, so the control pays the
    same per-child dispatch cost as a genuine hasher and differs only in the
    cryptographic component.

    It produces no valid commitment and must never appear in correctness,
    tamper, or cross-hash tests.
    """

    __slots__ = ()

    is_control = True
    digest_size = DIGEST_SIZE

    _CONSTANT = bytes(range(32))

    def update(self, data) -> None:  # noqa: D102 - deliberately does nothing
        pass

    def digest(self) -> bytes:  # noqa: D102
        return self._CONSTANT


def new_hasher(name: str):
    """Return a fresh incremental hasher for ``name``."""
    if name == "nullhash":
        return NullHash()
    if name == "sha256":
        return hashlib.sha256()
    if name == "sha3_256":
        return hashlib.sha3_256()
    if name == "blake2s":
        return hashlib.blake2s(digest_size=DIGEST_SIZE)
    raise ValueError(f"unknown hash implementation: {name!r}")


def is_control(name: str) -> bool:
    return name in CONTROL_ALGORITHMS


def require_cryptographic(name: str) -> None:
    """Guard used by every code path that asserts a real commitment."""
    if is_control(name):
        raise NullHashError(
            f"{name!r} is an instrumentation control and cannot produce or "
            "verify a valid commitment"
        )


def backend_info() -> dict:
    """Record the backend so results are scoped to the tested build."""
    return {
        "openssl_version": getattr(hashlib, "openssl_md5", None)
        and __import__("ssl").OPENSSL_VERSION,
        "algorithms_available": sorted(hashlib.algorithms_available),
        "digest_size": DIGEST_SIZE,
    }
