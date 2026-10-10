# V8.3: remember negotiating moves and their observed replies

Policy: `astra-v83-action-response-memory`.
Implementation baseline: `e2a13e52b6126e1c934ce1fef35378b8acc9868e` (v8.2).

## Problem and evidence

An independent Astra review found that the final decision board exposed historical
supplier quotes as selectable packages, but not the preceding buyer proposals
already stored with those quotes. The final director can only choose validated
package IDs. This made it easier to repeat an old concession than the move that
preceded that concession.

In the recorded P18 session, sent event 854 offered EUR 5.25 fixed price with
14-day payment and 24/36-month alternatives. Received event 855 included EUR 5.60
with a 5% index deadband and a 24-month term; that package was later closed for
0.339633. In the more recent session, event 1120 opened at EUR 5.60 with deadband
or EUR 5.50 without. Reply 1121 offered EUR 5.70 with deadband, and the closed
score was 0.273018. These are historical observations, not proof that repeating
the earlier opening will reproduce its response. The options differ in more than
price, and a response to several alternatives cannot be attributed to one alone.

P02 is a separate case: the latest opening was already aggressive and the latest
estimated savings differed from actual savings by about EUR 152. There is no
evidence that this memory change will resolve P02's remaining benchmark gap.

## Change

- Historical episodes retain their preceding buyer message number, supplier
  status, standing terms and stage: opening, negotiating, after a final warning,
  or unknown when the necessary records are missing.
- Identical supplier replies no longer collapse distinct preceding buyer moves
  or contexts. Duplicate received/exchange representations still collapse.
  Request matching ignores the runner's added `from` transport field, so duplicate
  representations preserve the same stage instead of consuming separate slots.
- Up to three of the ten memory slots retain distinct opening packages, selected
  by recency and terms, not score. Additional protected slots retain useful quoted
  alternatives/evidence routes, with at least half available for newest exchanges.
  Retrieval remains bounded to the latest 160 raw reply records; older moves are
  not guaranteed to remain available indefinitely.
- Historical buyer packages pass the existing current-case validation and cost
  calculation, just like new proposals. Complete valid packages become fresh
  selectable IDs; missing fields are not invented. Historical supplier responses
  remain separately selectable proposals requiring renegotiation.
- Each `historical_moves` entry links buyer package IDs, response package IDs and
  prior context to the source episode. The message text remains in `past_exchanges`.
  The final board also reports how many buyer messages have been sent now.
- Both Astra roles are instructed to compare the preceding action with its reply
  and current stage. Python does not force that action or claim a causal effect.
  Old offer IDs never become executable acceptances.

No database migration is required: context is reconstructed from existing audit
records. New memory fields contain message evidence, not scores or hidden
benchmark terms. The existing ten-episode limit remains.

## Deliberately isolated from other audit findings

This patch changes action-response memory, not the total-cost formula, response
probabilities, stopping rules, forecast retrieval, model choice or time budgets.
The audit also found that proposer timeouts can leave the final director without
fresh proposals, and that the numerical continuation estimate does not value
future counteroffers. Those remain limitations; this patch does not claim to fix
them. Keeping them constant makes the memory intervention separately assessable.

## Validation and outcome status

Source parsing, targeted static lint and diff checks are the validation boundary
for this update. No local unit tests, simulations, model replays or new Arena
sessions were run. An independent read-only code review checks the implementation.
There is **no measured score improvement** for v8.3, and v8.2's retrieval change
also remains unevaluated in Arena.

Any subsequent strategy evaluation must use only P02 and P18. Compare this patch
with its v8.2 baseline using the same saved memory and public inputs; do not mix in
timeout, scoring or other prompt changes. Record whether the historical buyer
package was available, what Astra selected, the first supplier response, and the
final outcome. If the earlier move is available but not chosen, the menu restriction
was not the active cause of that run. If chosen without improved responses or
outcomes across a bounded comparison, the hypothesis loses support. One historical
best or one new run is not an estimate of expected performance.
