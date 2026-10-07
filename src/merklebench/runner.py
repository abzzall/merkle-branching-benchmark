"""Benchmark execution: randomized timing blocks over the full factorial.

Design points enforced here (research plan, Sections 8, 12, 15):

* Transactions are generated once, outside every timed region.
* Each block runs every configuration exactly once, in a freshly randomized
  order, so block-level drift (frequency scaling, scheduling) is shared across
  configurations and cancels in within-block paired contrasts.
* Two construction modes are timed: full (leaf hashing plus internal levels)
  and internal-only (leaf digests precomputed outside the timed region).
* Verification batches rotate through all sampled proofs rather than
  re-verifying one proof, which would keep it resident in L1.
* The garbage collector is disabled inside timed regions and re-enabled after.
"""

from __future__ import annotations

import gc
import random
import time
from dataclasses import dataclass, field

from . import analytic, workload as workload_mod
from .hashing import CRYPTO_ALGORITHMS, is_control
from .proof import generate_proof, serialize, verify_parsed
from .tree import Workload, build_internal, build_leaves, build_tree

perf = time.perf_counter_ns


@dataclass(frozen=True)
class Config:
    transaction_count: int
    branching_factor: int
    hash_name: str

    def key(self) -> tuple:
        return (self.transaction_count, self.branching_factor, self.hash_name)


@dataclass
class Plan:
    configs: list[Config]
    transaction_size: int
    seed: int
    proof_seed: int
    timing_blocks: int
    proof_samples: int
    verification_batch_target_ms: float
    warmup_repetitions: int
    workloads: dict = field(default_factory=dict)

    def workload(self, n: int) -> Workload:
        if n not in self.workloads:
            self.workloads[n] = workload_mod.generate(n, self.transaction_size, self.seed)
        return self.workloads[n]


def build_plan(cfg: dict) -> Plan:
    algorithms = list(cfg["hash_algorithms"]) + list(cfg.get("control_algorithms", []))
    configs = [
        Config(n, k, h)
        for n in cfg["transaction_counts"]
        for k in cfg["branching_factors"]
        for h in algorithms
    ]
    return Plan(
        configs=configs,
        transaction_size=cfg["transaction_size_bytes"],
        seed=cfg["seed"],
        proof_seed=cfg["proof_seed"],
        timing_blocks=cfg["timing_blocks"],
        proof_samples=cfg["proof_samples_per_configuration"],
        verification_batch_target_ms=cfg["verification_batch_target_ms"],
        warmup_repetitions=cfg.get("warmup_repetitions", 3),
    )


def warm_up(plan: Plan, config: Config) -> None:
    """Touch the code path for this configuration before measuring it."""
    small = plan.workload(min(config.transaction_count, 256))
    for _ in range(plan.warmup_repetitions):
        build_tree(small, config.branching_factor, config.hash_name)


def measure_construction(plan: Plan, config: Config) -> dict:
    """One timed observation of both construction modes."""
    w = plan.workload(config.transaction_count)
    k, h = config.branching_factor, config.hash_name

    # Mode B preparation: leaf digests computed outside the timed region so
    # that leaf hashing, which is independent of branching factor, cannot
    # obscure the structural effect.
    leaves = build_leaves(w, h)

    gc.collect()
    gc.disable()
    try:
        t0 = perf()
        build_internal(leaves, k, h)
        t1 = perf()
        build_internal_ns = t1 - t0

        t0 = perf()
        tree = build_tree(w, k, h)
        t1 = perf()
        build_total_ns = t1 - t0
    finally:
        gc.enable()

    root = tree.root
    del tree, leaves
    return {
        "build_internal_ns": build_internal_ns,
        "build_total_ns": build_total_ns,
        "build_throughput_tx_per_sec": config.transaction_count / (build_total_ns / 1e9),
        "root_digest": root.hex(),
    }


def _calibrate(operation, target_ms: float, minimum: int = 1, maximum: int = 1_000_000) -> int:
    """Choose a repetition count so the batch lasts roughly ``target_ms``."""
    t0 = perf()
    operation()
    single_ns = max(perf() - t0, 1)
    reps = int((target_ms * 1e6) / single_ns)
    return max(minimum, min(maximum, reps))


def measure_proofs(plan: Plan, config: Config) -> dict | None:
    """Timed proof generation and verification for one configuration.

    Returns ``None`` for the non-cryptographic control, which cannot produce
    proofs.
    """
    if is_control(config.hash_name):
        return None

    n, k, h = config.transaction_count, config.branching_factor, config.hash_name
    w = plan.workload(n)
    tree = build_tree(w, k, h)
    indices = workload_mod.proof_indices(n, plan.proof_samples, plan.proof_seed)

    proofs = [generate_proof(tree, i) for i in indices]
    blobs = [serialize(p) for p in proofs]
    transactions = [bytes(w[i]) for i in indices]
    root = tree.root

    # --- proof generation: rotate over sampled indices ---
    sample_count = len(indices)

    def gen_once():
        for i in indices:
            generate_proof(tree, i)

    gen_reps = _calibrate(gen_once, plan.verification_batch_target_ms)
    gc.collect()
    gc.disable()
    try:
        t0 = perf()
        for _ in range(gen_reps):
            for i in indices:
                generate_proof(tree, i)
        gen_total = perf() - t0
    finally:
        gc.enable()

    # --- verification: rotate over sampled proofs so no single proof stays
    # resident in L1 across the batch ---
    def verify_once():
        for tx, proof in zip(transactions, proofs):
            verify_parsed(tx, proof, root, h, k)

    ver_reps = _calibrate(verify_once, plan.verification_batch_target_ms)
    gc.collect()
    gc.disable()
    try:
        t0 = perf()
        for _ in range(ver_reps):
            for tx, proof in zip(transactions, proofs):
                verify_parsed(tx, proof, root, h, k)
        ver_total = perf() - t0
    finally:
        gc.enable()

    all_valid = all(
        verify_parsed(tx, proof, root, h, k) for tx, proof in zip(transactions, proofs)
    )

    result = {
        "proof_sample_count": sample_count,
        "generation_batch_reps": gen_reps,
        "verification_batch_reps": ver_reps,
        "proof_generation_ns": gen_total / (gen_reps * sample_count),
        "proof_verification_ns": ver_total / (ver_reps * sample_count),
        "mean_serialized_bytes": sum(len(b) for b in blobs) / sample_count,
        "verification_success": bool(all_valid),
    }
    del tree, proofs, blobs, transactions
    return result


def block_order(configs: list[Config], rng: random.Random) -> list[Config]:
    order = list(configs)
    rng.shuffle(order)
    return order


def analytical_rows(plan: Plan) -> list[dict]:
    """Deterministic quantities, computed once per (N, k) configuration."""
    rows = []
    seen = set()
    for config in plan.configs:
        key = (config.transaction_count, config.branching_factor)
        if key in seen:
            continue
        seen.add(key)
        n, k = key
        row = analytic.summary(n, k, plan.transaction_size)
        indices = workload_mod.proof_indices(n, plan.proof_samples, plan.proof_seed)
        row["sampled_mean_serialized_bytes"] = sum(
            analytic.proof_serialized_bytes(n, k, i) for i in indices
        ) / len(indices)
        row["sampled_mean_verification_hash_calls"] = sum(
            analytic.verification_hash_calls(n, k, i) for i in indices
        ) / len(indices)
        row["sampled_mean_verification_bytes"] = sum(
            analytic.verification_bytes_hashed(n, k, i, plan.transaction_size)
            for i in indices
        ) / len(indices)
        if n <= 262144:
            row.update(analytic.proof_size_distribution(n, k))
        rows.append(row)
    return rows
