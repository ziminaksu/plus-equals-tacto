# Five additional practice sessions — v2 / v2.1

Exactly five new sessions were started under one persistent allowance. The same five case IDs were used as in the initial experiment. No replacement or sixth session was started.

| Case | Initial score | New score | Change | New replay |
|---|---:|---:|---:|---|
| case:P01 | 0.619 | 0.619 | +0.000 | [Replay](https://arena.tacto.ai/replay/8ce21019f5d5a281) |
| case:P04 | 0.815 | 0.815 | +0.000 | [Replay](https://arena.tacto.ai/replay/a9cb4c7d3feac983) |
| case:P05 | 0.433 | 0.433 | +0.000 | [Replay](https://arena.tacto.ai/replay/25533c1796f6c26b) |
| case:P10 | 0.000 | 0.578 | +0.578 | [Replay](https://arena.tacto.ai/replay/c02cc68ac9aaf974) |
| case:P11 | 0.375 | 0.133 | -0.242 | [Replay](https://arena.tacto.ai/replay/99b8b56c13e78d5b) |

Mean score: **0.448 → 0.516** (+0.067 absolute). Deals: **4/5 → 5/5**.

## Recovery and policy versions
P01, P04, P05 and P10 used bayes-v2. P10 negotiated the required 23,400 units on a 36-month commitment, but its attempted acceptance of a secondary alternative sheet received HTTP 422: that ID was not registered as standing. A read of the same session confirmed it was still open. After checking must-haves and estimated cost, the agent tooling accepted the server-confirmed primary offer in that existing session. This recovery is logged and is **not an uninterrupted autonomous completion**.

The integration was corrected before P11: bayes-v2.1 distinguishes indicative alternatives from executable standing offers and confirms the offer ID before acceptance. P11 used that version. These are five distinct starts, not six; the P10 recovery did not open a session. The experiment therefore contains an integration intervention and is not a perfectly frozen-policy benchmark.

## What improved
- Quoted supplier preferences are applied before package ranking, with bounded updates and deduplication.
- Price search includes intermediate prices and premiums; candidate pruning preserves economically useful middle options.
- Counteroffers must improve estimated supplier package value rather than repeat or worsen rejected demands.
- Persistent supplier/category priors and regularised response updates preserve uncertainty.
- Interpretation and short prose use one small-model call; escalation requires material unresolved interpretation.

## Remaining regression
P11 declined from 0.375 to 0.133. The new policy proposed EUR 48.41 with a 1,500-ppm commitment, which the supplier immediately accepted. The initial run closed at EUR 47.50 with a 300-ppm commitment. The revised policy was too conservative about the cost/acceptability of tighter quality requirements and conceded too much in its first package. This meets the hard quality limit but is economically weaker. It was not hidden or replaced by another run.

The new version should not be described as uniformly better or production-ready. The next controlled experiment should isolate quality-preference priors and the opening-offer acceptance trade-off. No post-hoc case-ID rule or untested policy patch was added to disguise this regression.

## Operational measurements
| Measure | Initial | New |
|---|---:|---:|
| Model calls | 36 | 11 |
| Model timeouts | 12 | 0 |
| Mean offer-generation time (seconds) | 22.64 | 7.40 |
| Returned usage cost (USD) | 0.04758 | 0.01193 |

Usage costs exclude setup checks and may omit charges from timed-out requests. Offer-generation timing excludes acceptance-only decisions and supplier response time. Different numbers of turns and responses prevent a clean latency or calibration experiment.

## Local validation
- Evaluated v2.1 suite: **54 passed, 1 optional hosted test skipped**. After integrating concurrent teammate changes, v2.2 passed **57 tests, 1 skipped**. No hosted test was enabled.
- Nine matched local simulator games, three cases × three fixed seeds, with LLMs disabled: mean 0.582 for the previous v1.1 code and 0.690 for v2. All moves passed validation. One case type regressed, so the aggregate is not universal improvement.
- The first v2 pruning attempt regressed in these local games; it was corrected before hosted runs. Local simulations guided implementation and are not an independent held-out evaluation.
- A saved-opening Qwen check verified evidence-before-selection without starting an Arena session.

Five paired case IDs with stochastic supplier replies provide limited evidence. Multiple changes shipped together; no individual feature is proven to have caused the score gain. Response probabilities remain approximate, and the P10 recovery must be considered when assessing autonomy.

[Full machine-readable comparison](improved-five-practice-results.json) · [Local comparison](local-v2-comparison.json) · [Current design](../ANALYTICAL.md)

## Final repository integration

A teammate pushed supplier-informed priors, economic supplier prioritisation, coverage-preserving search and optional OpenAI routing to the same branch during the experiment. These changes are preserved in the merged **bayes-v2.2** implementation, along with the new pipeline and closing guard. The combined version passed the local suite but was **not tested in another hosted run**. The scores above apply to v2/v2.1, not to an unmeasured v2.2 run.
