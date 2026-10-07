# Methodology handoff for reviewer revision

Generated from the immutable final raw results. No benchmark was re-run and no
raw result was changed.

## Decision on new experiments

No new experiment is methodologically necessary for the requested revision.

- Reviewer C.9 explicitly says the compiled control is strongly recommended
  but not required. The appropriate minimal response is to state the
  single-language/single-platform limitation in the Abstract.
- Reviewer C.10 says a boundary-sensitivity latency estimate “would help.” The
  frozen proof CSV contains aggregate timing over 16 rotated proofs, not
  per-leaf timings, so the requested latency contrast cannot be recovered.
  Running it now would be a new post-review experiment. The exact structural
  sensitivity below quantifies the sampling difference without pretending it
  is a latency estimate.

This decision follows the user instruction not to add improvements beyond the
reviewers' requirements.

## Reviewer C.4: confidence-interval evidence

Artifacts:

- `key_paired_ratio_intervals.csv`: all workloads, implementations and key H1
  and H3 contrasts (105 rows).
- `key_paired_ratio_intervals_largest_workload.md`: compact table suitable for
  manuscript/appendix adaptation at N=1,048,576.

Method: within each randomized block, divide the numerator-k timing by the
denominator-k timing; take the median of the 15 ratios; obtain the 95%
percentile interval from 10,000 bootstrap resamples of the block ratios using
the prespecified seed 20260924.

Checks:

- All 60 H1 construction ratios (k=3,4,8,16 versus k=2 across five workloads
  and three real hashes) have 95% intervals excluding 1.
- At N=1,048,576, k=8 verification versus k=2 is 0.6256
  [0.6248, 0.6287] for BLAKE2s, 0.5409 [0.5360, 0.5423] for SHA-256, and
  0.5471 [0.5445, 0.5482] for SHA3-256.
- k=8 has the lowest median verification timing in every measured cell. Do not
  claim that it is separated from both adjacent tested factors in every cell:
  at N=65,536 the k=8/k=4 BLAKE2s interval is 0.9820–1.0090 and the k=8/k=16
  SHA-256 interval is 0.9892–1.0032.

## Reviewer C.10: exact structural sensitivity at k=3

Artifact: `k3_structural_sample_sensitivity.csv`.

At N=1,048,576, the original 16-leaf boundary-enriched sample has:

- mean serialized proof size 785.0 bytes versus the exact uniform-population
  mean 828.6296 bytes (5.27% lower);
- the same mean verification hash-call count, 14.0;
- mean verification hashed bytes 1468.0 versus 1511.6296 (2.89% lower).

The five mandatory boundary leaves alone average 688.2 serialized bytes
(16.95% below uniform) and 1371.2 verification hashed bytes (9.29% below
uniform). The additional pseudorandom leaves reduce that imbalance in the
actual 16-leaf sample.

Interpretation boundary: these are exact structural comparisons. They suggest
that the boundary-enriched sample processes somewhat fewer bytes at k=3, but
they do not identify a latency difference. The revised limitation should say
that per-leaf latency was not retained and that the aggregate proof timing is
not a uniform-leaf population estimate.

## Other exact methodology corrections

- The 1500 construction observations are 5 workloads × 5 branching factors ×
  4 hash/control implementations × 15 blocks. Each observation row contains
  both `build_total_ns` and `build_internal_ns`; these are two response fields
  from the same randomized configuration execution, not 3000 independent
  observations.
- Pilot-to-final error should be stated as 1.8–6.7% for construction and
  1.6–6.8% for verification, or “at most 6.8% overall,” not below 7.2%.
- Textual percentage changes use medians of within-block paired ratios. Table 2
  reports marginal medians, whose ratios can differ slightly. Its note should
  state this explicitly.
- For Eq. (6), differentiating the continuous approximation gives the
  first-order condition `k(ln k - 1) = (a/b + 3)/d`.
- The current wire format uses one byte for branching factor, child count and
  position, imposing `k <= 255`.

## Validation

Focused analytical and regression tests: 26 passed.

Analysis environment: Python 3.12 with the repository's pinned packages. The
`.venv/bin/python3` symlink currently resolves to system Python 3.14, so this
re-analysis was executed with `/usr/bin/python3.12` and the existing pinned
Python 3.12 site-packages. No package was installed or upgraded.
