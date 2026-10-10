# Eight previously low-scoring Arena practice cases

Evaluated code: `1b73db108efa6abda0ed2f9f80ed53d2d80e3afc` (`bayes-v4-integrated`).

The allowlist was frozen before any new session: each case’s latest completed practice score had to be strictly below 0.60. One new session per eligible case; P01 and P04 were excluded. The CLI ran sequential groups of five and three, preserving learned SQLite memory. No policy changed during the runs.

| Case | Previous latest | New score | Change | Deal |
|---|---:|---:|---:|---|
| [case:P02](https://arena.tacto.ai/replay/e5afa6ac10625d51) | 0.000 | 0.157 | +0.157 | yes |
| [case:P03](https://arena.tacto.ai/replay/e4f7a33f302e9129) | 0.561 | 0.851 | +0.290 | yes |
| [case:P05](https://arena.tacto.ai/replay/71813595bf534217) | 0.433 | 0.383 | -0.049 | yes |
| [case:P07](https://arena.tacto.ai/replay/e68df559ba8e9ca4) | 0.568 | 0.648 | +0.079 | yes |
| [case:P08](https://arena.tacto.ai/replay/82a821f172254c66) | 0.305 | 0.383 | +0.078 | yes |
| [case:P10](https://arena.tacto.ai/replay/820e1b85c83734f4) | 0.578 | 0.686 | +0.108 | yes |
| [case:P11](https://arena.tacto.ai/replay/cd3e7320baca25a9) | 0.380 | 0.626 | +0.246 | yes |
| [case:P18](https://arena.tacto.ai/replay/7014f3de09900f25) | 0.189 | 0.340 | +0.150 | yes |

Mean: **0.377 → 0.509**. 7 improved, 0 tied, 1 regressed; 8/8 deals.

Practice usage: 20 → 28 of 200.

Model calls:

- `Qwen/Qwen3.8-27B:deepinfra`: 39 attempts; 38 ok, 1 ReadTimeout.
- `gpt-6-astra`: 2 attempts; 1 ok, 1 ReadTimeout.

Validation: 97 local tests passed, one optional hosted test skipped; lint passed. Both GitHub offline regression jobs passed on the evaluated commit. The original private implementation and the team integration each have an Entire checkpoint, and both remote checkpoint refs were verified before the first Arena session.

These are one-off stochastic comparisons, with multiple simultaneous changes and carried-over learning. They do not isolate the value of Astra or establish a 0.90 success rate. All results, including regressions and model timeouts, are retained in [the machine-readable report](v4-low-score-results.json).
