# Azure full practice batch and structural diagnosis

One attempt for each of the ten hosted practice cases, with Ksu's Azure
`gpt-5-mini`, low reasoning effort, compact board, and `ASTRA_TRADE_MENU=1`.
No replacement sessions or other provider fallback. Two cases ran concurrently.
Every case received its own copy of the same initial SQLite memory. Source remained
frozen at `80c3f6d0b20b7821ffbf8f6bca16fbc1fb31a6a0` throughout. No strategy edits were made mid-batch.

## Results

Mean score, including the no-deal result: **0.624269**.
Valid deals: **9/10**. All ten processes completed, which does
not imply ten successful negotiations. There were **5
failed model calls out of 86**, and
**1 Python fallback decision(s)**.

| Case | Score | Deal | Failed/all model calls | Fallback decisions |
|---|---:|---|---:|---:|
| P01 | 0.748094 | Yes | 1/9 | 0 |
| P02 | 0.630135 | Yes | 1/12 | 0 |
| P03 | 0.950303 | Yes | 0/10 | 0 |
| P04 | 0.809807 | Yes | 0/5 | 0 |
| P05 | 0.000000 | No | 1/7 | 1 |
| P07 | 0.659149 | Yes | 1/10 | 0 |
| P08 | 0.648288 | Yes | 1/7 | 0 |
| P10 | 0.578073 | Yes | 0/5 | 0 |
| P11 | 0.709896 | Yes | 0/12 | 0 |
| P18 | 0.508944 | Yes | 0/9 | 0 |

The published score is `(opening cost - deal cost) / (opening cost - benchmark best
cost)`, clipped to 0–1. It measures the share of possible total-cost improvement,
not deal success probability. The agent does not receive the hidden benchmark.
Historical records are best-of-many results and cannot serve as matched controls.
This one-pass batch does not establish that the trade menu improves scores. It stays
off by default.

## Confirmed problems

### 1. The final selected action and the sent offer can differ

`director.execute` removes packages above 101% of the cheapest selected package's
**direct** cost after the model has chosen them and written its email. Across this
batch, this happened in **14 decisions**.
This is separate from normalization and compaction, which can also restrict choices.

- P02 decision 4 selected three packages but sent one, while its email still said
  three alternatives were attached.
- P07 decision 2 selected EUR 5.11 / 90 days and EUR 4.94 / 60 days. Only the latter
  was sent. Decision 3 similarly selected three packages but sent only EUR 4.94 /
  45 days. The new optional trade menu therefore interacts with the old execution
  filter; a selected price-concession route can disappear.
- P01 selected a plain reply while its rationale described proposing two better
  packages. The sent message contained no term sheet. The next reply was final.
  This chronology does not prove that a real counter would have won a better deal.

Fix: finalize package filtering before model approval; expose only selectable IDs;
render package counts and terms from that approved action. Require the plan and
message to agree with the action. Reject or explicitly repair contradictions instead
of silently discarding economic choices. Supplier-facing text should use the final
validated package object as its single source of truth.

### 2. Multi-supplier timing and stale alternatives can lose the whole deal

P05 had a roughly 46-second gap while refreshing other supplier threads before a
decision. Only about 3.4 seconds remained for the final model call, which timed out
and triggered a fallback. Later, an executable EUR 30 offer was left while we
continued with a rival. When we attempted to accept it, the offer had expired.

At the last decision, only one supplier remained. The model chose `walk_away`
while claiming it could pursue a better rival. That rival was no longer live.
The action ended the whole case, producing **zero**. This was a semantic decision
failure, not a successful recovery merely because the process did not crash.

Fix: bounded refresh requests, per-supplier deadlines, explicit expiring-offer
priority, and a current-only list of executable alternatives. The closing contract
must state that walk-away ends the entire case, and cannot justify walking away
using a closed or expired rival. Avoid granting fresh time for unchanged state.

### 3. Negotiation heuristics can override total-cost reasoning

The director constrains ordinary opening offers near 86% of the ask, uses separate
relationship-case price bands, schedules later concessions by fractions of the
price gap, and removes counters after two consecutive agreements. Multi-supplier
rules treat a 5% supplier price cut as a limit. These are heuristics inferred from
individual runs, not measured universal supplier rules.

In P01, a generated EUR 130 / 14-day package had a lower estimated total cost, but
was outside the permitted counter set. That is evidence of restricted choice, not
proof the supplier would have accepted EUR 130. The model must be able to compare
well-supported alternatives while hard validation enforces genuine case constraints.

### 4. A lower unit price need not be a better relationship-case outcome

P02 closed at EUR 356.12, 45-day payment and a copper index clause, scoring
0.630135. Its actual breakdown included EUR 51,283.66 in relationship/sustainability
cost and EUR 17,407.15 in index risk. Those costs matter in this benchmark.

The supplier had earlier accepted EUR 356.12 / 90 days. Shortening payment to 45 days
raised direct buyer cost by EUR 21,758.93, but the model estimated a larger reduction
in sustainability cost (about EUR 30,499). Therefore the shorter payment term is
**not by itself evidence of a worse total agreement**. The final total-cost estimate
was EUR 2,254,908.08 versus actual EUR 2,253,028.44: the final economics estimate was
fairly close. The remaining issue includes finding obtainable joint trade-offs,
not simply replacing the cost arithmetic or optimizing unit price alone.

Fix: compare complete packages using the same total-cost definition at generation,
selection, and execution. Seek quote-backed alternatives that jointly vary price,
payment and indexing. Keep supplier willingness separate from estimated economic
sustainability, with uncertainty visible. Do not infer that a willing supplier is
necessarily profitable.

### 5. P18 was a strategy shortfall despite successful model calls

P18 scored 0.508944 with all nine calls successful and no Python fallback. Supplier
prices moved 6.10 -> 5.80 -> 5.50 -> 5.40, then remained at 5.40 in its final offer.
The final package had 60-day payment, 36-month commitment and a 5% deadband index
clause. Its scored buyer cost was EUR 258,263.64, including EUR 2,303.64 of index
movement/risk. The final response arrived with six nominal moves remaining; spare
moves alone do not mean a supplier will keep bargaining.

The package menu and repeated approval-route requests did not produce another
concession. One selected package was filtered out before sending. These observations
do not prove that a different message or model would improve the outcome. The score
is below both earlier P18 runs (0.587026 control, 0.631787 trade option), which also
had supplier response variation and used the pre-merge source. No general improvement
claim is supported.

## Recommended order

1. Repair current-offer state and closing semantics; preserve viable deals.
2. Make approved and sent actions identical, with consistent prose.
3. Replace hard strategy exclusions with explicit, reviewable preferences where
   they are not real buyer constraints or protocol restrictions.
4. Evaluate one strategy change at a time against a frozen control; report every
   attempt, mean score, deal rate, expired offers, timeouts, and action mismatches.

These findings do not establish that a larger model would solve the problems, or
that any single proposed fix will reach 0.9. The all-case tests are diagnostic;
the implementation remains the frozen version already in this PR.

Machine-readable results and usage: `azure-all-cases-20261011.json`. Credentials,
raw transcripts, and private databases remain ignored. Reported token usage does
not include unreported usage from failed calls and is not a billing estimate.
