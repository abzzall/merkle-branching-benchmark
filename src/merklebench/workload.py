"""Deterministic synthetic transaction generation.

The study benchmarks authenticated-tree mechanics, not transaction semantics,
so payloads are fixed-length pseudorandom records.

Prefix consistency: transactions are drawn from a single stream seeded once,
so the first N transactions are identical for every workload size and every
configuration. Smaller workloads are therefore genuine prefixes of larger ones
without materialising the largest dataset (research plan, Section 6): at
N = 2^20 and 256-byte payloads that would be 256 MB held resident while the
small configurations run.

Generation always happens outside timed regions.
"""

from __future__ import annotations

import numpy as np

from .tree import Workload

CHUNK_TRANSACTIONS = 65536


def generate(n: int, transaction_size: int, seed: int) -> Workload:
    """Return the first ``n`` transactions of the stream defined by ``seed``."""
    if n < 1:
        raise ValueError("n must be >= 1")
    rng = np.random.default_rng(seed)
    total = n * transaction_size
    parts = []
    remaining = total
    chunk = CHUNK_TRANSACTIONS * transaction_size
    while remaining > 0:
        take = min(chunk, remaining)
        parts.append(rng.bytes(take))
        remaining -= take
    return Workload(b"".join(parts), transaction_size)


def proof_indices(n: int, sample_count: int, proof_seed: int) -> list[int]:
    """Deterministic leaf indices covering boundaries and interior positions.

    Always includes 0, 1, N//2, N-2 and N-1 where valid, so incomplete final
    groups are exercised, then fills the remainder pseudorandomly rather than
    sampling boundaries only.
    """
    required = [0, 1, n // 2, n - 2, n - 1]
    chosen = []
    for idx in required:
        if 0 <= idx < n and idx not in chosen:
            chosen.append(idx)
        if len(chosen) == sample_count:
            return sorted(chosen)

    rng = np.random.default_rng(proof_seed)
    pool = set(chosen)
    guard = 0
    while len(chosen) < sample_count and len(pool) < n and guard < 100 * sample_count:
        candidate = int(rng.integers(0, n))
        guard += 1
        if candidate not in pool:
            pool.add(candidate)
            chosen.append(candidate)
    return sorted(chosen)
