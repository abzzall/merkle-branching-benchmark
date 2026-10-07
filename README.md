# Merkle branching-factor benchmark

Reproducibility package for the experimental study of branching-factor
trade-offs in conventional hash-based Merkle trees on commodity hardware.

The benchmark varies tree branching factor, workload size and hash
implementation independently. It measures construction, proof generation and
verification latency; computes structural quantities exactly; evaluates a
null-hash traversal control; and validates a two-parameter latency model on
cells fixed before the final run.

## Included material

```text
src/merklebench/    tree, proof, hashing, workload and analytical model
experiments/        runner and smoke, pilot and final configurations
tests/              correctness, boundary, tamper and isolation tests
analysis/           validation, statistics, plots and reviewer re-analysis
results/raw/        immutable smoke, pilot and final CSV results
results/processed/  generated summaries and statistical outputs
results/figures/    generated benchmark figures
logs/               final execution log
```

No manuscript or journal-template files are included.

## Experimental design

- Branching factors: `2, 3, 4, 8, 16`
- Transaction counts: `4096, 16384, 65536, 262144, 1048576`
- Transaction size: 256 bytes
- Hash implementations: SHA-256, SHA3-256 and BLAKE2s-256 via `hashlib`
- Construction-only control: `nullhash`
- Timing blocks: 15, with independently randomized configuration order
- Proof samples per configuration: 16, rotated within calibrated batches
- Workload seed: `20260922`
- Proof-index seed: `20260923`
- Bootstrap seed: `20260924`

The four model holdout cells were fixed in `experiments/config.yaml` before
the final run and were excluded from model fitting for every real hash
implementation.

## Setup

Python 3.12 is required. Create an isolated environment and install the pinned
dependencies:

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

The benchmark is CPU-only.

## Verify the archived results

```bash
make test
make validate RUN=final
make process RUN=final
make figures RUN=final
make reviewer-analysis
```

`make process` and `make figures` regenerate processed outputs from the
archived raw CSVs. They do not modify raw data.

## Run a small end-to-end check

```bash
make smoke
```

This executes a small benchmark, validates its output, and regenerates its
processed results and figures.

## Run configurations

```bash
make pilot
make estimate
make final
```

The archived final run took 27.72 minutes on the recorded machine. Running the
final configuration again creates new measurements; it does not reproduce the
exact timing values because latency is platform-dependent.

## Construction and proof rules

Leaves and internal nodes use domain-separated preimages:

```text
leaf     = H(0x00 || transaction)
internal = H(0x01 || enc(k) || enc(r) || c_0 || ... || c_(r-1))
```

Here `r` is the actual child count. Every consecutive group of one through `k`
children produces a parent; nodes are never promoted unhashed, duplicated or
padded. Binding both `k` and `r` separates roots across configurations.

The proof wire format records a version, level count, and each level's child
position, child count and sibling digests. The current one-byte fields impose
`k <= 255`.

## Statistical analysis

The primary comparison is the within-block paired ratio against `k=2`. The
reported effect is the median of 15 block ratios, with a 95% percentile
interval from 10,000 bootstrap resamples. Structural quantities are exact and
are not subjected to significance tests.

The latency model is

```text
T = a * hash_calls + b * bytes_hashed
```

and is fitted per operation and hash implementation by non-negative least
squares. Four `(k,N)` cells are withheld from fitting and used only for
prediction evaluation.

The null-hash control repeats the construction traversal without cryptographic
hashing. It estimates the Python traversal and dispatch floor; it is not a
valid commitment and is excluded from proof and correctness paths.

## Archived run environment

The final run used:

- Intel Core i5-13420H, 12 logical CPUs, 15.3 GiB RAM
- Linux x86-64, glibc 2.39
- CPython 3.12.3
- OpenSSL 3.0.13
- source revision `223fef811f00956cca7825db60c806e0dbba9889`

Complete package versions and configuration are recorded in
`results/raw/final/environment.json`. Launch metadata are recorded in
`results/raw/final/RUN_MANIFEST.txt`, and the console record is preserved in
`logs/final-20260922T090744Z.log`.

Results apply to the recorded implementations and platform. They should not
be generalized to other language runtimes, hash backends or hardware without
local calibration.

## Raw-data integrity

Files under `results/raw/final/` are the frozen output of the reported run.
Do not edit them. Derived tables, summaries and figures belong under
`results/processed/` and `results/figures/`.

## License

The software is licensed under the Apache License 2.0. Redistributions must
preserve the license and attribution notices; see [LICENSE](LICENSE) and
[NOTICE](NOTICE).

## Citation

If this software or its archived results contribute to a publication, cite the
repository using [CITATION.cff](CITATION.cff). GitHub can render this metadata
through its “Cite this repository” function. Add the public repository URL and
Zenodo DOI to the citation metadata after publication and archival.
