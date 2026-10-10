# V10 P02: execution recovered; score did not improve

Two separately authorized P02 sessions were started. The additional session
completed with **0.235133**, below the previous best **0.254765** by **0.019631**.
The initial failed session is included below. No P18 or third session was started.
No local runtime tests, simulations or LLM replays were run.

| Attempt | Runtime commit | Outcome | Official score |
|---|---|---|---:|
| Initial authorized P02 | `9f98e44` | Final action validation failed before any message; remote session later ended by timeout. | 0.000000 |
| Separately authorized additional P02 | `0c2f92f` | Deal at €367.84/unit, 14-day payment, no index clause. | 0.235133 |

Full run IDs, session IDs, source/data/memory fingerprints, decisions and linked
outcomes are in [the machine-readable report](v10-p02-results.json).

## Execution evidence from the additional run

| Turn | Proposer seconds | Final seconds | Whole decision seconds | Final action |
|---|---:|---:|---:|---|
| 1 | 8.277 | 16.872 | 25.948 | Offer €363.90, early payment, fixed price |
| 2 | 13.964 | 16.031 | 30.911 | Moderate to €367.00, early payment, fixed price |
| 3 | 10.376 | 14.491 | 25.754 | Accept €367.84 |

All six model requests completed; all three final actions passed validation on
their first attempt. No output-correction call was needed, so that recovery path
remains unexercised in Arena. One proposer interpretation was rejected on turn 2;
three valid proposals remained, and final Astra was explicitly told its input was
partially validated. API completion and full semantic validity are distinct.

All three actions have a linked decision, dispatch and observed outcome. Both
supplier counters matched the predicted response class and fell within the
subjective price intervals. This verifies trace linkage, not calibrated prediction
accuracy: there were only two counteroffers and the intervals were broad.

Frozen runtime source matched the evaluated commit before the run and remained
unchanged afterward. Actual decisions retained at least 24 seconds of the internal
budget before dispatch. Proposer timing is materially different from the old
approximately 7.2-second read cutoff; one successful case cannot establish a
future timeout rate across suppliers.

## Why the score remains low

The observed sequence was €370.96 opening → €368.68 supplier counter → €367.84
supplier counter → acceptance. The final supplier status was still `open`, with
no final-offer warning. Remaining moves were eight; this does not prove the
supplier would tolerate another request.

Astra explicitly chose to stop. Its earlier plan reserved an indexed exchange
for an unchanged reply and called for closing after meaningful fixed-price
progress. The supplier made progress, and final Astra followed that stopping rule.
No Python override forced acceptance. The final prompt does tell Astra to honour
its prior stopping rule unless new evidence supports revising it; that consistency
requirement can preserve an overly conservative early plan.

The indexed alternative remained available to select. At closure the board gave
it only €1,240.64 more mean improvement than the standing offer, with worse
downside. Its estimated relationship cost was €4,148.36 versus €225.65 for the
standing deal. Astra cited those comparisons and the prior stop condition when
rejecting it. These are estimated economics, not observed costs for an unmade deal.

The accepted deal's realized total cost was **€2,271,733.11**, an improvement of
**€11,134.38** from opening. Its observed relationship cost was €64.79 versus the
€225.65 estimate. That difference is about €161; it does not by itself explain
the score or establish that the indexed alternative was undervalued. The final
cost prediction for the chosen deal was close, while continuation value and
alternative-deal uncertainty remain unresolved.

This run therefore narrows the diagnosis: the remaining problem is the choice of
negotiation sequence and stopping decision, rather than a missing proposer caused
by timeout. A useful next investigation is whether the prior plan receives too
much authority, and whether alternative packages are rejected for uncertainty
without enough direct evidence. No new strategy patch or experiment is claimed
by this report, and a higher score from another move is not established.

## Initial failure and correction

The first attempt's proposer and final API calls completed in 9.450 and 18.721
seconds. Application validation then failed. The old diagnostic retained only
`ValueError`, so the exact rejected selection and reason are unknown. The runner
stopped before dispatch; the remote session subsequently ended with score zero.

The published correction records returned decisions and exact validation reasons,
adds source-ID/string constraints to the output schema, and allows one bounded
correction on validation failure when at least ten seconds remain. No network
retry or Python-selected substitute is used. The original session was not resumed;
the user explicitly approved the second session after it ended.

## Limits

- Historical best is context, not a matched baseline. Several changes and different
  histories prevent causal attribution of the score difference.
- Timing and validation succeeded in one completed session; the first failed
  session remains part of the evidence.
- The correction path, forecast-mismatch branch and graceful batch stop were not
  exercised by this run. Static review does not replace runtime verification.
- No claim that P02 strategy, other suppliers or all failure modes are solved.
