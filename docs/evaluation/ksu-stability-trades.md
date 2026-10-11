# Stability and conditional-trade experiment

Base: Ksu branch `ziminaksu`, commit `7da18da`.

## Stability fixes

- Preserve the server result when refresh discovers an ended session, and return it without another model call.
- Recovery cannot reset the move budget unless a new supplier event arrived; waiting respects the wave cap.
- Exhausted-board fallback must still fit the original decision deadline.
- Provider slots cannot exceed the remaining overall request budget.
- Reset the stale-accept retry count after a successful exchange.
- Preserve Azure launcher failures and expose diagnostic output.

## Optional strategy change

`ASTRA_TRADE_MENU=1` retains up to two validated, one-field non-price exchanges beside
Ksu's scheduled price step. These keep our previous price, either shorten payment
or extend commitment, and have expected total buyer cost no greater than the
scheduled price concession. The model still decides; direction alone does not
prove supplier willingness. Compaction preserves these options.

Default is off. This is a hypothesis, not a measured score improvement.

## Validation and pending Arena comparison

Eleven focused tests pass: cancellation, response validation, provider budget,
ended-session recovery, stale-state retry prevention, thread refresh, and trade
selection. Targeted lint, shell syntax and diff checks pass. No local negotiation
simulation was run.

Arena comparison is blocked pending the user-authorized Ksu Azure credentials.
No model calls or Arena sessions have started. Do not substitute Gemini: the user
explicitly requested Ksu's Azure configuration.

Proposed bounded comparison: two P18 practice starts, one with the flag off and one
on, same Azure deployment and initial SQLite snapshot. Log actual providers,
fallbacks, failures, cost components and total score for both. If credentials or
service quota fail, stop rather than consume sessions blindly. A two-run result is
exploratory, not proof of a general improvement; keep the flag off if inconclusive.
