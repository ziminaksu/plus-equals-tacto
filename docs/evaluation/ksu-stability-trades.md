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

Azure connection verified with the user-authorized key and `gpt-5-mini` deployment.
Credentials remain in ignored `.env`. The comparison used Azure only, no other provider fallback.

| P18 arm | Score | Buyer cost | Model calls | Fallback decisions |
|---|---:|---:|---:|---:|
| Stability fixes, trade option off | 0.587026 | EUR 252,600.92 | 9/9 successful | 0 |
| Same code, trade option on | 0.631787 | EUR 249,354.81 | 9/9 successful | 0 |

The experimental agent selected a same-price move to 60-day payment. Both runs closed
valid deals. Score difference: +0.044760; scored buyer-cost reduction: EUR 3,246.11.
The input databases were identical snapshots and source code stayed frozen.

These are only two sessions. Initial offer terms matched, but the supplier’s first replies
already differed before the trade menu was applied. This comparison does not establish
causality or general improvement, and the feature stays opt-in. The current result is
below the 0.654 historical P18 best cited in Ksu’s earlier report.

Full screened results, model usage, selected trades and fingerprints:
`azure-p18-trade-comparison-20261011.json`. No replacement sessions were started.
