# Five-session practice report

Exactly five remote starts were used. These results measure **bayes-v1**, before the fixes below.

| Case | Score | Deal | Opening cost | Deal cost | Replay |
|---|---:|---|---:|---:|---|
| case:P01 | 0.619 | True | €1,153,779.74 | €1,118,542.70 | [Replay](https://arena.tacto.ai/replay/56e82b2f69eadf31) |
| case:P04 | 0.815 | True | €198,846.33 | €196,957.20 | [Replay](https://arena.tacto.ai/replay/0f8a7b4989da7516) |
| case:P05 | 0.433 | True | €305,544.96 | €270,021.92 | [Replay](https://arena.tacto.ai/replay/fe58b5d345143447) |
| case:P10 | 0.000 | False | €1,932,492.18 | — | [Replay](https://arena.tacto.ai/replay/3c92250b0dab3d0a) |
| case:P11 | 0.375 | True | €817,578.00 | €781,882.50 | [Replay](https://arena.tacto.ai/replay/2123ec722c123b23) |

Mean: **0.448**; deals: **4/5**.
The practice leaderboard averages best scores over all ten hosted cases; unplayed cases count zero.

## Findings and changes
- P10 failed mandatory volume coverage. The agent correctly refused the inadequate final offer, but reached it with poor modelling and a worsened second price demand.
- Candidate sampling missed full-volume, longer-contract combinations. The final implementation retains all combinations within the starter kit cap before ranking.
- Final code prevents a follow-up package with lower estimated supplier value and models uncertainty when requesting volume above the supplier’s offered allocation.
- The large Qwen model timed out at default thinking depth. A separate non-Arena API check passed with low reasoning effort. The five-case experiment retained the original settings in its running process.
- No new live score is claimed for these fixes. Regression tests and replay checks verify mechanics, not counterfactual negotiation success.

## Scope of evidence
This is a smoke experiment, not proof of superiority or calibrated supplier probabilities. Production cost estimates and response coefficients remain uncertain. Model failures used deterministic fallback. Audit data is held locally in ignored SQLite; only this aggregate report is published.

See [machine-readable results](five-practice-results.json) for timing and returned usage.
