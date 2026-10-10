# V10: reliable role budgets and traceable negotiation plans

Baseline: `4da51fb` (runtime source evaluated at `b7c1dbc`).
Policy: `astra-v10-traceable-plans`. User-authorized Arena scope: **P02 once only**.
No P18 session, replacement session, local simulator test or LLM replay is authorized.

## Evidence and changes

| Observed issue | Implemented change | How it is checked |
|---|---|---|
| Proposer 12-second allocation became `(12 - 3) * 0.8 = 7.2` seconds of read time; 16/19 calls timed out. | One monotonic deadline. Proposer up to 20 seconds, final up to 30, with a reserved final window. Async cancellation bounds the entire HTTP operation, without nested fractional reductions or automatic retries. | Per-role allocation, preparation, duration, success, usage and failure records in the P02 run. |
| Large duplicate cost/history boards and verbose scalar enums. | Lossless tables and exact repeated-string references; homogeneous enum values share one enum. All input records, offers, evidence and IDs survive. Production reconstruction is checked before dispatch. | Input character counts, schema sizes and hashes; final selection still validates against the full board. |
| Missing proposer advice was not explicit in final context. | Per-supplier model availability distinguishes success, partial validation, unavailable, skipped for budget, and closure-only turns. | Availability is stored in the board and visible to final Astra. |
| Rich deals but no mandatory linked negotiation sequence. | Structured expected reply/optional price interval; conditional actions; evidence basis; rejected alternative; explicit revision from the prior response. | Plan schema and semantic validation; linked `decision_record` / `plan_outcome`. |
| Acceptance/walkout subtotal could look like total continuation value. | Rename it a partial value and explicitly identify the unvalued counteroffer branch. Require Astra's conditional plan for that branch. | Inspect the actual plan; no invented precise multi-turn probability or value. |
| Menu construction influenced choice without a concise audit. | Generation provenance, duplicate counts, rejected candidate terms and policy-vs-protocol-vs-buyer-constraint labels. | Full board linked by event ID/hash from each decision. |
| Score changes were not reproducible or easy to interpret. | Record source/data/memory fingerprints, model settings and hypothesis; report plans alongside actual replies. | Freeze code for the single authorized run and publish all outcomes, including failures. |
| No graceful way to stop queued sessions. | Stop-file checked before each reservation. Active session can finish; no allowance mutation. | Source-level control-flow review in this pass; no additional practice run to exercise stopping. |

The controller uses 55 seconds from receipt, leaving five seconds outside it for
Arena dispatch/overhead. Preparation and attachments consume the same deadline.
Within it, the final step reserves 24 seconds plus three for board work and two
for execution; proposer is skipped if fewer than eight useful seconds remain.
These limits bound work; they cannot guarantee an external service responds on time.

Astra remains both proposer and final decision-maker. No provider/model substitution,
new buyer weights, hidden benchmark input or change to the official cost formula.
Future plan branches do not authorize future actions; each turn is decided afresh.
No claim that these structural fixes alone solve P02's negotiation strategy.

## Validation scope

Source parsing, targeted lint, diff inspection and credential checks before
publication. No local runtime tests under the user's standing instruction.
One P02 Arena run is authorized to check actual execution and decision records.
The batch is exploratory: several structural changes are bundled, there is no
matched baseline rerun, and one outcome does not demonstrate general superiority.

## Implementation references

- `budget.py`: allocation and reserves.
- `router.py`: cancellable Responses requests and role telemetry.
- `prompt_context.py`: reversible prompt encoding with production reconstruction check.
- `contracts.py`, `decision_record.py`: plan requirements, provenance and response comparison.
- `director.py`, `agent.py`: integration into the actual decision/observation loop.
- `experiment.py`, `cli.py`, `report.py`: fingerprints, graceful stop and readable audit.

The API design follows the official guidance on
[latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization)
and [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
Those guides support reducing repeated input and handling incomplete output;
observed improvements must come from our run, not from documentation claims.
