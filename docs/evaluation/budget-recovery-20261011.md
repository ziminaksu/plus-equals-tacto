# GPT-6 recovery under a USD 1 cap

The user authorized at most USD 1 additional spend for the whole improvement round.
After an initial credit rejection, the user supplied a funded key. The subsequent
GPT-6 Astra P18 run completed at **0.466961**, below the earlier Azure result of
**0.508944**. Conservative accounted spend for the entire round is **USD 0.499877**.
Reliability and spending controls were exercised, but **score recovery has not
been demonstrated**. No further paid requests were made after this run.

## Changes

- Budget mode uses one final model decision per turn, combining source reading,
  strategy and reply writing. It skips the separate proposer. One bounded
  correction of invalid output remains possible and is also metered.
- The smaller request retains every selectable package, exact terms, verified
  evidence, current sources, constraints and total-cost estimates. It drops
  unselectable package cards and repeated historical diagnostics. Ksu's existing
  offer generation and negotiation rules remain in place. The full board stays
  in the private audit log.
- Approved counteroffers are all transmitted, in order. The old renderer dropped
  offers more than 1% above the cheapest *direct* cost, even after the model had
  approved a trade using total cost. Invalid package selections now require
  correction instead of silent removal.
- An atomic SQLite ledger reserves a conservative maximum before dispatch.
  Concurrent processes and restarts share the same allowance. Usage reconciles
  reservations; unknown timeout outcomes retain the whole reservation. There is
  no automatic retry or switch to another paid provider.
- Exhausted budget closes a currently received valid offer instead of continuing
  unpaid template bargaining. This is explicitly logged as `budget_close`, not
  a model decision.
- Following the failed live attempt, a tiny metered billing check now runs before
  opening Arena. Definitive credit rejection blocks further calls and releases
  its unused reservation. An ambiguous error still retains the reservation.

The guard supports standard-tier direct OpenAI Responses calls to `gpt-6-astra`
and explicitly selected `gpt-6-sol`. The default here is **Astra**. Its rates come
from the [official Astra model page](https://developers.openai.com/api/docs/models/gpt-6-astra);
Sol rates come from [its model page](https://developers.openai.com/api/docs/models/gpt-6-sol).
The guard includes the 1.25x input cache-write rate and ignores caching discounts.
These are conservative usage estimates, not an invoice or an account balance.
It excludes priority tiers, tools and third-party endpoints; unsupported routes
fail before dispatch. Pricing constants need review if provider rates change.

## Attempts and validation

The first session start was explicitly rejected because the team had ten open
sessions. We did not interrupt another active run. After capacity opened, one
P18 session started with the same initial memory snapshot used in the earlier
Azure batch. Its only model request was rejected with
`429 / credit_balance_exhausted`. A fallback counter and budget closure produced
**0.252113**. This was not a successful GPT-6 strategy test. The definitive billing
rejection incurred no accounted generation spend. Billing preflight and immediate
budget closure were then added and checked before the funded attempt.

The user supplied a new key. We resumed the **same ledger and original USD 1 cap**,
retaining the rejection record. A tiny metered preflight passed before Arena opened.
The funded run used the same initial memory snapshot; its source stayed frozen.

| Metric | Funded P18 |
| --- | ---: |
| Arena score | 0.466961 |
| Earlier Azure P18 score | 0.508944 |
| Decisions / successful decision calls | 3 / 4 |
| Paid validation corrections | 1 |
| Model timeouts / fallback decisions | 0 / 0 |
| Decision input / output tokens | 31,431 / 2,121 |
| Decision call times (seconds) | 10.885, 14.810, 12.781, 8.656 |
| Conservative whole-round spend, including preflight | USD 0.499877 |
| Remaining authorized allowance | USD 0.500123 |
| Unknown-outcome reservations | USD 0 |

This is one stochastic session with multiple code/model changes, not a controlled
quality comparison. It does not establish that Astra is better or worse generally.
The remaining allowance was left unspent; it is not the user's account balance.

## What still limits the score

1. The first counter sought a fixed price with a longer commitment. The supplier
   instead offered two indexed alternatives. Their complete costs mattered more
   than the lower headline unit price.
2. Astra next chose an index-rebase question. It repeated that ask's own question
   ID in the optional question field. The validator rejected this harmless
   duplication, triggering another paid call. The correction changed the move to
   confirmation of the supplier's deadband alternative. This repair cost about
   USD 0.132 conservatively and changed the intended strategy.
3. After confirmation, Astra accepted with **eight moves still available**. Counter
   and question actions were still present: Python did not force that closure.
   The model's preceding plan said to close once the package was confirmed; the
   next decision followed that stopping condition. Whether another inquiry would
   improve the deal remains unmeasured.

After the run, validation was narrowed to accept an ask's identical repeated
question ID without changing its action, reply, or terms. A different question ID
still fails. A regression verifies one call and exact execution of the intended
question. This post-run fix has **not** had another paid Arena evaluation.

The next strategy experiment should examine the decision *before confirmation*:
compare one useful information request or priced trade against closing, using the
supplier's actual index/commitment constraints. Reopening after promising to
finalise is not a substitute for making that comparison early. Another model swap
alone does not address this stopping-policy issue.

In total, **23 focused regression checks passed**, covering concurrent spending,
restart safety, timeouts, credit rejection before Arena, exact offer rendering,
context preservation, redundant-question handling, one-call decision auditing and
prior recovery behavior. Targeted lint, shell syntax and diff checks passed. No
local negotiation simulator ran.

See [screened run metadata](budget-recovery-20261011.json) for the sessions,
evaluated source hashes, authorities and results. Hidden benchmark values and
credentials are excluded.

## Subsequent upstream integration

Ksu pushed `a8705b9` during this evaluation: the sender prioritizes selected volume
arguments on the opening, limits the selected arguments per message, and adds a
management-approval request on the second counter when no question was chosen.
This change was merged unchanged, preserving the existing punctual-payment and
approval-route attachments. The offer-rendering repair remains in place.

All 23 focused checks were rerun on the merged source. The funded P18 run predates
this upstream change and the redundant-question fix; it must not be described as
an evaluation of the final merged version. No additional credits were spent on
integration. The combined implementation and integration commit carries an Entire checkpoint
imported from the authentic, credential-redacted Codex session.

## Operation

`tools/run_gpt6.sh` now defaults to a shared USD 1 ledger at
`hollerau/logs/gpt6-spend.sqlite`. Its failures are visible and preserved. The
script accepts `OPENAI_API_KEY` or legacy `LLM_API_KEY` from ignored `.env`.

For a separately authorized round, select an explicit ledger and cap:

```sh
uv run tacto-bayes --cases case:P18 --max-sessions 1 --run-id funded-check \
  --primary astra --reviewer astra --openai-model gpt-6-astra \
  --max-spend-usd 1 --spend-ledger hollerau/logs/authorized-round.sqlite
```

Reuse that ledger across every case in the round; changing the run ID must not
reset the spending allowance. A billing-blocked ledger stays blocked until the
funding problem is resolved and the remaining allowance is deliberately resumed.
The current round's USD 1 authorization is not itself an API deposit.
