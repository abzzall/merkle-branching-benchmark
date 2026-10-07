# Reviewer CI table — largest workload

N = 1048576. Ratios are medians of within-block paired ratios; intervals are
95% percentile bootstrap intervals using 10,000 resamples and seed 20260924.

| hypothesis | hash_algorithm | metric | contrast | ratio [95% CI] | percent change |
| --- | --- | --- | --- | --- | --- |
| H1 | blake2s | build_total_ns | k=3 / k=2 | 0.7813 [0.7783, 0.7835] | -21.9% |
| H1 | blake2s | build_total_ns | k=4 / k=2 | 0.7303 [0.7261, 0.7345] | -27.0% |
| H1 | blake2s | build_total_ns | k=8 / k=2 | 0.6567 [0.6514, 0.6591] | -34.3% |
| H1 | blake2s | build_total_ns | k=16 / k=2 | 0.6252 [0.6242, 0.6266] | -37.5% |
| H1 | sha256 | build_total_ns | k=3 / k=2 | 0.7351 [0.7229, 0.7440] | -26.5% |
| H1 | sha256 | build_total_ns | k=4 / k=2 | 0.6572 [0.6511, 0.6616] | -34.3% |
| H1 | sha256 | build_total_ns | k=8 / k=2 | 0.5634 [0.5556, 0.5650] | -43.7% |
| H1 | sha256 | build_total_ns | k=16 / k=2 | 0.5227 [0.5145, 0.5284] | -47.7% |
| H1 | sha3_256 | build_total_ns | k=3 / k=2 | 0.7635 [0.7625, 0.7661] | -23.6% |
| H1 | sha3_256 | build_total_ns | k=4 / k=2 | 0.6818 [0.6811, 0.6844] | -31.8% |
| H1 | sha3_256 | build_total_ns | k=8 / k=2 | 0.6111 [0.6087, 0.6151] | -38.9% |
| H1 | sha3_256 | build_total_ns | k=16 / k=2 | 0.5822 [0.5799, 0.5835] | -41.8% |
| H3 | blake2s | proof_verification_ns | k=8 / k=2 | 0.6256 [0.6248, 0.6287] | -37.4% |
| H3 | blake2s | proof_verification_ns | k=8 / k=4 | 0.9520 [0.9469, 0.9551] | -4.8% |
| H3 | blake2s | proof_verification_ns | k=8 / k=16 | 0.8755 [0.8718, 0.8771] | -12.4% |
| H3 | sha256 | proof_verification_ns | k=8 / k=2 | 0.5409 [0.5360, 0.5423] | -45.9% |
| H3 | sha256 | proof_verification_ns | k=8 / k=4 | 0.8816 [0.8766, 0.8828] | -11.8% |
| H3 | sha256 | proof_verification_ns | k=8 / k=16 | 0.9722 [0.9690, 0.9741] | -2.8% |
| H3 | sha3_256 | proof_verification_ns | k=8 / k=2 | 0.5471 [0.5445, 0.5482] | -45.3% |
| H3 | sha3_256 | proof_verification_ns | k=8 / k=4 | 0.9447 [0.9428, 0.9476] | -5.5% |
| H3 | sha3_256 | proof_verification_ns | k=8 / k=16 | 0.8727 [0.8675, 0.8741] | -12.7% |
