# V7 P02/P18 Arena results — 10 October 2026

Two authorised sessions ran against the same published source revision, `b0f52719a4ddee44c882434bf8fa714961b9ee98`, attached to Entire checkpoint `01M4KBQ5R6VPN2D23CVQGX85BH`. The analytical source hash remained unchanged throughout. No local tests, private model replays, simulator games or replacement Arena sessions were run.

| Case | Previous latest | Previous best | V7 result | Outcome |
|---|---:|---:|---:|---|
| P02 | 0.096648 | 0.156989 | **0.254765** | Deal: €364.12, 14 days, CU-NOTATION 20%, 5% deadband |
| P18 | 0.339633 | 0.339633 | **0.000000** | Supplier walked away after a counter to its final offer |

This is a mixed result, not a successful improvement across both cases. [Machine-readable results and decision audit](v7-arena-results.json) contain the actual Arena responses, model statuses, source freeze and selections. There was one stochastic run per case, with existing practice feedback retained; this is not an isolated causal comparison or evidence of generalisation to unseen suppliers.

## P02: better forecast, better deal, still a modest score

The original €374.95 should-cost and ±5% uncertainty reached both Astra roles. The effective-cost interval inferred from prior completed practice feedback was €365.8652–€369.3347. Its midpoint was €367.60. This inference did not use the hidden best-cost benchmark, and quotes did not change the cost distribution during the run.

Astra asked for a cost walkthrough, then proposed priced payment/index exchanges and requested committee approval. It secured an indexed €364.12/14-day offer and later tried higher fixed prices conditional on removing indexation. Those fixed-price alternatives were not confirmed. A €365.19/30-day indexed quote appeared, but after another counter the supplier returned to its €364.12/14-day standing package. Astra accepted on the last move.

| Cost component | V6 actual | V7 actual |
|---|---:|---:|
| Price | €2,119,864.50 | €2,224,773.20 |
| Payment | €14,132.43 | €22,742.13 |
| Quality | €1,191.45 | €1,191.45 |
| Index risk | €16,958.92 | €17,798.19 |
| Relationship | €126,143.57 | €4,298.55 |
| **Total** | **€2,278,290.87** | **€2,270,803.51** |

The final relationship forecast was **€4,148.36**, an underestimate of **€150.19**, versus the v6 underestimate of €71,888.57. Other forecast cost components matched Arena to cents. This is strong evidence that the cost repair worked on this observed package, not proof that every future supplier-cost inference is accurate. The completed result and its component errors were stored for the next eligible practice session.

P02 improved by €7,487.36 in total cost versus v6 and by €4,630.01 versus the earlier best deal. It still has €35,289.46 of cost gap to Arena's terminal benchmark. That benchmark was used only for this post-run report, never by the live agent. The remaining gap is primarily a negotiation problem: balanced lower-cost packages were proposed but not secured, and index/early-payment costs remain.

All ten final decisions were authorised by Astra. Seven proposal calls succeeded, two timed out, and the final closing move did not need a proposal call. All ten final-decision calls succeeded. No timeout caused the negotiated result.

## P18: poor closing judgement caused a walkout

The supplier's standing package reached €5.60, 14-day payment, 24 months and an AS-14404 index with **zero deadband**. Its calculated buyer cost was €276,514.75. The supplier also floated €5.70 with a 5% deadband; the previous €5.60/5%-deadband best package was not freshly confirmed in this run.

After several exchanges and payment questions, the supplier explicitly marked its quote `final_offer` and asked for a decision. Astra countered with €5.60/5%-deadband and €5.50/zero-deadband packages at 36 months, requesting committee approval. The supplier then returned `walked_away`. Arena reported no deal and score zero. Python did not replace Astra's choice, and the API/model did not fail at this point.

The closing comparison was poor. The desired historical package represented about **€5,972** of further savings, while losing the current offer exposed roughly **€24,573** of additional fallback cost. Even under the optimistic assumption that every non-walkout achieved the desired improvement, a walkout probability around 19.6% would erase the expected benefit. This is a retrospective break-even calculation, not a measured supplier probability.

P18 is a `leverage` case, with no scored relationship penalty. Nevertheless, Astra's reasoning repeatedly mentioned the uncertain supplier margin. That concern should not displace the case's actual objective. The next repair should make active cost dimensions explicit and present the final-offer loss/gain trade-off to Astra before another counter, while retaining Astra's final authority. This report records that remaining weakness; it does not claim the closing policy was repaired or tested after these two sessions.

There were five Astra-authorised actions. Four proposal calls succeeded and one timed out; all five final-decision calls succeeded. No extra session was started after the walkout.

## Publication and evaluation limits

The code was pushed before the runs through Entire's authentic scoped-session import. This report is a subsequent documentation update with its own scoped Entire attachment. Public practice feedback is used only within the same supplier/case/context; it is not transplanted to unseen final suppliers. No local testing was resumed. P02/P18 remain the only cases authorised by the standing evaluation instruction.
