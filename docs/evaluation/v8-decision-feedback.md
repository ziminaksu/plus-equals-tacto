# V8: repair negotiation decisions and feedback

The v7 audit found four false positive acceptances in P02, an unobserved terminal walkout in P18, template replies that failed to answer fixed-volume questions, and no per-action gain/loss evidence before Astra chose a counter.

## Implemented changes

1. `feedback.py` compares complete returned and proposed packages, including price and index details. Agreement to an unchanged standing offer is labelled `unchanged_offer`, never acceptance of a different proposal. Only exact newly agreed packages get the acceptance label. Pure questions have separate response counts rather than fictitious offer rejections.
2. The shared runner delivers explicit terminal supplier replies to the agent before returning the result. Missing terminal status is logged as unavailable; a zero score alone is not inferred to mean walkout. Result/benchmark data never enter behavioural learning.
3. Legacy learned-model rows remain untouched for audit and are ignored. The next session reconstructs estimates from completed hosted raw exchanges for the same supplier/case/context, including terminal records, with duplicate suppression. No local simulations or model calls are used for this reconstruction.
4. Astra writes the actual reply and can answer or ask a bespoke question. Fixed facts have exact placeholders. Python appends complete packages including fixed annual volume and full index-clause details. Numeric claims/reference IDs and protocol constraints are checked; the validator cannot establish the truth of every numeric-free sentence.
5. Before selection, each package exposes the gain if agreed, loss if the current offer disappears, an optimistic break-even walkout probability, and uncalibrated response estimates. Other executable supplier offers can contribute to the outside option. Counts of prior offer/question outcomes after final warnings are explicit. Astra provides a subjective walkout range, explanation, information goal and stop condition; these are audited, not used for an automatic strategic veto.
6. Both Astra roles receive the case's objective scope. Supplier profitability is a scored objective only where the published relationship penalty applies; other cases omit irrelevant supplier-margin cost cards.

## Assumptions and limitations

- The behavioural probability model is still approximate and does not itself model the final-warning hazard. That limitation is explicit; Astra sees the warning and context-specific observed outcomes before choosing.
- The optimistic break-even threshold assumes every surviving negotiation gets the desired improvement. The expected-gain estimate assumes counteroffers preserve the current package. Both assumptions can overstate continuation value; the board says so.
- Counts and Wilson intervals describe sparse, dependent historical observations, not calibrated future probabilities. They are not guaranteed outcomes or a claimed Arena score.
- Reply prose uses exact fixed-fact placeholders for numeric answers. Binding commitments remain the permitted term sheets plus fixed case terms. No hidden supplier parameters or benchmark are used.
- Historical reconstruction learns only from observed hosted messages and original public case context. It ignores contaminated aggregate estimates rather than editing original logs.

## Validation and publication

Static syntax/lint and diff checks only; local tests and private replays remain stopped at the user's request. The authorised strategy evaluation is exactly one new hosted P02 session and one P18 session, without replacement sessions. This implementation document does not claim score improvement before those runs finish. Code is published with an authentic scoped Entire session attachment before evaluation; results receive their own subsequent attachment.
