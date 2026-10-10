# V6 P02 Arena result — 10 October 2026

One hosted P02 session was requested and completed. No replacement session or P18 session was started. Code remained frozen at `024aa256ec2e4e3d8bb0a821e252e8a5b0d50bc8`, published with Entire checkpoint `01M4KAWSMM3E8PFTZS3TCP2Y94` before the run.

**P02 scored 0.096648, below the previous 0.156989.** Astra had final authority on all six actions. Removing the Python override did not improve this run's score.

## Actual outcome

| Component | Previous P02 | V6 P02 | Change in buyer cost |
|---|---:|---:|---:|
| Unit price | €368.45 | €346.95 | |
| Payment | 14 days | 30 days | |
| Price over the horizon | €2,251,229.50 | €2,119,864.50 | −€131,365.00 |
| Payment cost | €23,012.57 | €14,132.43 | −€8,880.14 |
| Quality | €1,191.45 | €1,191.45 | €0.00 |
| Index risk | €0.00 | €16,958.92 | +€16,958.92 |
| Relationship cost | €0.00 | €126,143.57 | +€126,143.57 |
| **Total** | **€2,275,433.52** | **€2,278,290.87** | **+€2,857.35** |
| **Arena score** | **0.156989** | **0.096648** | **−0.060341** |

The deal uses CU-NOTATION, material share 0.2, a 5% deadband and base month 2026-08. Arena reported zero index adjustment under this case's path, but still charged index risk. All must-haves passed. The case's opening and best benchmark costs were unchanged from the previous run. The benchmark was obtained only in the terminal result and was not used by the live policy.

## What happened

1. Astra asked which previous pricing structures remained available.
2. It proposed an indexed rebased package and two fixed-price alternatives. The supplier returned €346.95 with 14-day payment and the index clause.
3. Astra asked for priced payment alternatives; the supplier retained its offer and mentioned standard 30-day payment.
4. Astra offered conditional packages and requested management approval. The supplier agreed to €346.95 with 30-day payment and indexation.
5. Astra tried a further set of lower-priced packages. The supplier retained the standing offer.
6. Astra accepted that current standing offer. Python sent the exact selected acceptance.

All six final Astra calls succeeded. One of six proposal calls timed out; the final decision still used the available board. There were two questions, three counters and one acceptance, with no failed final authorization. Successful calls reported 201,783 input tokens and 3,796 output tokens; usage for the timed-out proposal is unknown.

## Why the lower price did not help

The final board estimated total cost at **€2,206,402.29**, including **€54,255.00** in relationship costs. Arena reported **€2,278,290.87**, including **€126,143.57** in relationship costs. The approximately **€71,889** forecasting error was in the relationship component; the other displayed components matched Arena to cents.

In the published formula, relationship cost prices a shortfall in the supplier's sustainable margin. A polite message or the supplier accepting a package does not eliminate that cost. Index protection is security rather than cash in the supplier-value formula. A rebased price can therefore look attractive while making the sustainability penalty worse.

The board explicitly labelled its supplier-cost estimates uncertain and showed a total-cost p10–p90 range of **€2,152,147.30–€2,370,656.83**. The actual result was inside that broad range. Astra's acceptance rationale relied on the favourable expected value and the expensive fallback; it did not adequately account for the downside relative to the previous deal.

The inherited belief state mixes public should-cost estimates with a quote-implied lower-cost scenario when those sources conflict. The final board flagged this conflict, with estimated supplier full cost averaging €337.9835 and a p10–p90 range of €302.0453–€377.6396. Those assumptions were not calibrated well enough for a relationship-sensitive decision. This run does not identify the supplier's true cost or prove that one particular estimator caused the entire error.

## Next strategy priorities

- Keep willingness to accept separate from evidence that the price supports a sustainable supplier margin. An accepted loss-making quote is possible in this exercise.
- Present the public should-cost and quote-implied scenarios separately, with their effects on margin and relationship cost. An unexplained average conceals the important disagreement.
- Give Astra comparisons against previous complete packages and explicit downside costs before acceptance. Astra retains final authority; Python supplies the calculations and constraints.
- Evaluate balanced price/payment/index packages, including a higher price if its relationship benefit outweighs the increase. Further price reduction is not automatically improvement.
- Use actual Arena outcomes to assess the strategy. Do not turn post-result hidden benchmarks into live supplier knowledge.

These are findings and proposed changes, not additional implementation or claimed improvements. There was only one stochastic live run and existing learning state was retained.

## Evaluation instruction going forward

The user stopped local testing during this run. No local tests have been run since that instruction. Future strategy updates are to be evaluated in hosted Arena on **P02 and P18 only**. The previous local validation remains a historical implementation check, not evidence of Arena performance. An increased Arena allowance does not itself authorise unlimited repetitions; record each update, session count and actual score.

The live session ID was `a2abf8f6e60c1d21`, run ID `ehl-v6-p02-20261010`. [Structured result and decision audit](v6-p02-arena.json) contain the actual response, model statuses and final cost estimate. Raw exchanges and the pre-run learning snapshot remain in ignored local logs.
