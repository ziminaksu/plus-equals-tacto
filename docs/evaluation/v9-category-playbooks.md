# V9: extend Ksu's negotiation strategy across weaker case categories

Policy: `astra-v9-category-playbooks`. Teammate baseline: `0479452`, including
Ksu's latest escalation/share-of-business change. Her branch records a P18
score of 0.563345; this update targets other cases.

## Scope and observed problems

Read-only Arena inspection selected P01, P02, P05, P07, P08, P10 and P11 because
their best completed practice scores were below 0.7. P18, P03 and P04 are excluded.
[The frozen baseline](v9-baseline.json) records both best and latest scores.
The evaluation allowance is exactly one session per selected case, seven total,
with no replacement for a failed start. No local tests, simulations or LLM replays.

Earlier recorded exchanges show distinct problems: P01 accepted an early offer
after giving away 14-day payment; P02 repeated an immediately accepted historical
package; P05 repeated tiny price moves while offering little new in exchange;
P07 gave away payment and duration early; P08 needs indexed/fixed price trades;
P10 closed with a costly 56-day lead time; P11 repeated price-only moves while the
supplier requested a payment concession the case does not permit.

## Implementation

`playbook.py` chooses a plan from public category goals and supplier count, not
case IDs or target scores:

| Category | Main negotiation route |
|---|---|
| Stabilise | Effective date, payment and fixed/indexed structures, including relationship-cost uncertainty. |
| Secure supply | Jointly feasible volume, duration and delivery packages; permit economically useful premiums. |
| Quality first | Trade permitted ppm targets and reimbursement against price; never promise changes to fixed payment terms. |
| Competitive RFQ | Compare current executable total-cost offers and consider untried suppliers before early closure. |
| Commercial | Preserve Ksu's ambitious opening, staged reciprocal concessions and supported approval/share-of-business route. |

Candidate generation now repairs negotiable hard constraints before varying an
invalid supplier opening. This lets capacity and quality options appear even
when the original offer fails a must-have. All candidates still pass the existing
full validity checks. The anchor menu remains capped at 24: non-price routes get
slots before the remaining price grid. Historical unit references are labelled
separately from exploratory discounts; component purchase prices are not used as
kit-price anchors. Strategic/bottleneck cases use milder exploratory price factors
than commercial cases and retain the independently estimated sustainability menu.

Each supplier has an advisory shortlist across different term packages. It uses
expected total cost, not predicted acceptance, and leaves all valid actions
selectable. The final model compares the plan, actual responses and cost uncertainty.
These are heuristics, not learned optimal policies or calibrated outcome forecasts.

Ksu's final-offer closing guard, one-standalone-question limit and escalation
argument remain. Non-counter messages now also mark unreferenced commercial
argument kinds as used. Universal claims that open suppliers cannot walk away are
replaced with explicit uncertainty and category-specific priorities.

The internal budget becomes 45 seconds within Arena's 60-second move window.
Proposer allocation is at most 12 seconds, with 28 seconds reserved before the
decision deadline for the final step; the final request cap is 30 seconds. HTTP
phase timeouts and a three-second reserve remain. This improves allocation but
is not a hard guarantee against network stalls or lengthy board construction.

## Verification and outcome

Source parsing, targeted static lint and diff checks passed before publication.
No local runtime tests were executed. Arena results will be recorded separately;
there is no claim that these changes achieve 0.7 before evaluation.

The source must be published with an authentic Entire checkpoint before the
frozen seven-session evaluation. No official cost formula or benchmark input is
modified. Original supplier facts and all executed choices remain auditable.
