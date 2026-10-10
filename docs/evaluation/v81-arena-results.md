# V8.1 Arena results and remaining evidence-access weakness

Two sessions ran against code `21ffdfbb1292d95a432fc2b47da341792e1f67c2`, attached to Entire checkpoint `01M4KDJHF3W4Y2KPEF8M64AGHG`. Both analytical and runner hashes remained unchanged during the pair. No local tests or private model replays ran. [Full result and decision audit](v81-arena-results.json).

| Case | Previous best before this work | V8 first pair | V8.1 second pair |
|---|---:|---:|---:|
| P02 | 0.254765 | 0.000000 | 0.254765 |
| P18 | 0.339633 | 0.273018 | 0.273018 |

Four completed sessions total, on P02/P18 only, across two distinct published revisions. No failed or ambiguous session was replaced. These results do not demonstrate an improvement over the previous bests.

P02 made two counters, explicitly answered the volume question and accepted the same EUR 364.12 indexed package as v7. The score-objective correction prevented immediate opening-price acceptance. Exact returned terms now produce a genuine acceptance label. P18 countered, confirmed the EUR 5.70/5%-deadband alternative and accepted; it followed the stopping condition recorded on its previous turn and did not reopen bargaining. Every action in this pair was Astra-authorised.

## Why P02 remains difficult

The public case has only three negotiable fields: price, payment and indexation. Annual volume and contract duration are fixed. It has a scored relationship penalty (`relationship_eur_per_point=31920`, sustainable margin 0.5%) whose nonlinear formula can make an excessive price cut worse for the buyer. Its copper index rose 47.7% across the latest available twelve-month observations and copper has a category-team estimated 20% weight. That is evidence supporting cost pressure, not proof of the supplier's exact production cost. The supplier's requested increase is 6.5%; historical and forecast periods must not be mixed into an audited cost claim.

The static dossier supplied just one selectable argument in P02: an on-time-delivery complaint. Forecasts were omitted, and index evidence was filtered to movements favourable to the buyer. When the supplier requested forecast data, Astra stated that it had no separate detailed forecast. Inspection of the public package found `fc:350011@2026-09`, marked shareable, with 6,110 units and twelve monthly rows totalling the same quantity. The planning period is October 2026 through September 2027; this is not identical to the case contract period. It supports the volume discussion but does not guarantee a further concession.

## V8.2 evidence-path repair (not yet Arena-evaluated)

The latest code retrieves the current forecast and all available part-specific cost drivers, not only favourable claims. A supplier request for forecasts/volume also retrieves the monthly rows. Both Astra roles see a retrieval inventory that distinguishes missing records from lookup failures. A shareable, fact-checked forecast can be sent as an evidence-backed reply without making a fresh counteroffer. Prices and binding volume remain governed by permitted case terms.

V8.2 received static syntax/lint/diff checks only. It has no new Arena score; the table above belongs to v8 and v8.1, not this retrieval change. The recorded 11.9% forecast `change_pct` is not presented as year-on-year growth because its comparison basis was not established; the actual dated forecast and quantities are used instead.
