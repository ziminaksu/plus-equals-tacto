# V8 first pair: feedback repairs exposed an objective mismatch

Both authorised sessions completed on code `9a4d108bd3769f49ca93c19e36d9c6fd6f8c3467`, with Entire checkpoint `01M4KDBYEQS7K8GGKC9SC1R9D6`. The analytical and runner source hashes remained unchanged during both sessions. No local tests ran.

| Case | V7 | V8 | Outcome |
|---|---:|---:|---|
| P02 | 0.254765 | 0.000000 | Astra accepted the unchanged opening offer immediately |
| P18 | 0.000000 | 0.273018 | Two concrete counters, then a valid deal; no walkout |

[Raw results, decisions and reconstruction audit](v8-arena-results.json).

P02 reconstructed 26 previous replies into 13 counteroffers, 11 unchanged offers and two genuine acceptances. P18 reconstructed 17 replies, including the previously missed walkout after a final warning. The code no longer imports the contaminated aggregate learning rows.

The P02 decision exposed another design error: its risk review compared a modest possible improvement with approximately EUR 321,000 of cash fallback loss, then protected the opening offer. But the published Arena score gives zero both to no deal and to an unchanged opening deal. That cash-loss comparison belongs to a real procurement objective, not the competition reward. V8 therefore regressed P02 despite repairing the observation mechanics. It is not a successful overall evaluation.

P18 used authored messages, cited the fixed annual requirement, answered the supplier's request for a price basis without inventing internal cost data, and made conditional exchanges. It closed at EUR 5.70 with 14-day payment, a 36-month contract and 5% index deadband, costing EUR 275,373.46. Its 0.273 score remains below the earlier best 0.340.

## V8.1 correction before the next pair

The action cards now use positive total-cost savings from the opening offer as a transparent proxy for Arena reward. Walkout risks the improvement already secured. Cash fallback loss remains separately labelled business context. The unknown best-cost denominator and score saturation are not estimated or imported into the agent. This proxy preserves all non-price cost components and does not justify arbitrary unit-price cutting.

Astra sees its previous stopping condition on the next turn and must explain any evidence-based revision. The final choice remains Astra's; Python does not force a counter or acceptance.

This is a distinct source revision prompted by an observed failure, not a replacement of a failed/ambiguous API session. The follow-up evaluation remains limited to P02/P18, one session each. Both pairs will be reported, including regressions.
