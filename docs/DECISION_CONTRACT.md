# Decision contract and controlled improvement

**Status: core contract implemented in v10; one completed P02 trace after an
initial validation failure.** See [observed results and limits](evaluation/v10-p02-results.md).
`contracts.py` requires a plan; `decision_record.py` validates it and records linked
outcomes. [The current architecture](CURRENT_ARCHITECTURE.md) maps the execution
path. More records do not prove better decisions or a score gain.

## One shared decision record

Every turn should be understandable from one record, with six sections:

| Section | Required contents | Who owns it? |
|---|---|---|
| Case | Buyer objective, negotiable fields, fixed terms, allowed options, hard requirements, official cost coefficients | Python copies the public case; Astra cannot redefine it. |
| State | Current offer IDs/terms, supplier status, remaining moves, our previous move and their response, available suppliers | Python derives state from Arena events. Historical and live offers remain separate. |
| Evidence | Claim/value, source event or document, scope/date, and status: observed, estimated or assumed | Python retains provenance; Astra interprets text and cites the source. Uncertainty remains visible. |
| Options | Candidate package, provenance, buyer cost by component/range, feasibility, concessions we give and request | Astra proposes; Python validates/prices. Record which generation rule added or excluded an option. |
| Plan | Chosen action, expected reply, conditional next action, stop condition, main alternative rejected and why | Final Astra is responsible for strategic judgment. A numerical probability is optional, not invented to fill a field. |
| Outcome | Exact sent action, actual reply/terms, change from prediction, estimate updated and why | Python records; interpretation cites the response. The final score belongs to evaluation. |

The contract makes **deal** and **move** distinct. A deal is a complete package
we could buy. A move is a request, question, acceptance or other action intended
to change the negotiation. The cheapest proposed deal may be a poor next move.

Each `decision_record` now links the full board event, current state, evidence
provenance, generation counts/rejections, selected packages, model availability,
timing and validated plan. `plan_outcome` compares response class and an optional
forecast price interval with the actual reply. The next board contains the prior
plan and its observed errors. Raw observations still drive supplier estimates;
Astra forecasts do not become learning labels. Evidence quotations are validated
where supported by existing checks; semantic truth of all prose is not guaranteed.

## Decision authority

1. The case defines what is legal and what the buyer values.
2. Python performs arithmetic and checks constraints and factual references.
3. Astra chooses the strategy among visible options. If useful options are missing,
   candidate generation must expose that limitation instead of presenting the menu
   as exhaustive.
4. Python executes exactly a valid selection. An invalid selection becomes an
   explicit error; it does not silently become a different commercial decision.
5. Outcome evidence updates estimates. A developer changes policy only through
   a named, measurable hypothesis.

Separate **protocol checks**, **buyer constraints** and **strategy rules** in the
record. For example, a live offer ID is required for acceptance; a maximum ppm
may be a buyer constraint; refusing to counter `final_offer` is a policy rule.
All currently applicable checks remain until deliberately revised.

## A readable example using P11

Observed v9 facts: payment was fixed at 60 days. The run closed at EUR 46.50,
300 ppm and zero complaint reimbursement. Its previous best closed at EUR 46.00
with the same quality/reimbursement combination. The score fell from 0.626 to
0.543. Historical EUR 46.00 terms were not a live executable offer in the new run.

A proposed decision record would make these separate:

- **Fact:** faster payment is unavailable; do not offer it as a concession.
- **Fact:** the current live price and quality terms, with the actual offer ID.
- **Evidence:** a prior negotiation obtained EUR 46.00; this does not guarantee
  the new supplier session will repeat it.
- **Question for economics:** how much does a feasible change in reimbursement,
  price or quality cost us over this case's demand and horizon?
- **Question for strategy:** what permitted exchange could improve the live deal?
  What observed supplier statement supports it? What will we do if they refuse?
- **After the reply:** did the requested change happen, did the supplier require
  something else, or did we hit a closing condition? Update that specific belief.

This explains a next action. Saying only “apply more pressure” does not.

## A small state machine

Use the same phases across suppliers, driven by events rather than case IDs:

| Phase | Decision to make | Evidence needed to leave the phase |
|---|---|---|
| Understand | What do we need and what can be traded? | Case fields, executable offers, important unknowns. |
| Open | Which credible package and evidence start the negotiation? | A sent proposal and actual supplier reply. |
| Exchange | Which concession buys which improvement? | Changed terms, a condition, refusal, or an answer that changes the plan. |
| Close | Accept a live offer or take another allowed closing action? | Current IDs, feasibility, costs, status and deadline. |
| Learn | Which prediction was wrong and what is now supported? | The linked move/reply and permitted result components. |

V10 records open/exchange/close phases from current state and action, then learn
on the linked outcome. Understanding is the evidence preparation stage, not an
extra model call. A missing terminal reply is recorded as unobserved rather than
inventing a rejection or walkout.

## Improvement order

| Order | Deliverable | Completion criterion |
|---|---|---|
| 1. Establish truth | Canonical architecture, frozen results, honest current/proposed labels | One entry point; source/runtime references agree; every launched run is accounted for. This documentation pass supplies it. |
| 2. Make execution visible | Joined decision records and per-role timing/availability | Every action can be traced to the board and model output actually available at that turn; missing proposer output is visible. |
| 3. Make planning explicit | Conditional next moves and reply-error comparison | The record distinguishes a bad prediction from a missing option, invalid action or deliberate closing decision. |
| 4. Improve one behavior | One targeted change supported by the trace | The intended action changes under the stated conditions; economics and regressions are reported. |

V10 corrects the proposer deadline, adds cancellable request deadlines and
lossless prompt compaction. Calls log allocated time, preparation time, actual
request time, schema size, input size and usage. A timeout or budget skip is visible
to the final decision; it cannot masquerade as successful proposer advice.

## Experiment discipline

For the next authorized Arena batch, record **before** opening sessions:

- One hypothesis and the observable behavior it should change.
- Code commit, policy, model roles/settings, memory snapshot hash and public data
  fingerprint. Changing any of these changes the experiment.
- Selected cases, baseline selection rule, maximum starts and stop condition.
- Primary metric: realized total-cost improvement. Also report official score,
  deal/no-deal, component costs, actions, model failures and timing.

An improvement claim needs a fair same-case comparison. Where the platform permits,
use repeated baseline/candidate runs with fixed initial learning snapshots and
report all attempts and variability. Do not claim controlled opponent seeds unless
Arena actually exposes them. Treat a single run as exploratory evidence.
Historical best and historical latest are useful context but are not matched controls.

Preserve no-deals, timeouts and unfavorable outcomes. Do not select only successful
runs or change memory during a comparison without recording it. No minimum score
is guaranteed. Local simulator tests remain stopped under the current instruction;
the initial P02 and separately authorized additional P02 have both finished.
Further Arena runs need authorization.

## File boundaries

Keep `arena_kit/` for the protocol and published economics. Within
`hollerau/analytical/`, separate coordination, evidence/state, option generation,
economics, final decision, execution and observation. Existing files are mapped in
[the architecture](CURRENT_ARCHITECTURE.md); split the large `director.py` in a later
behavior-preserving refactor. New budget, prompt, decision-record and experiment
responsibilities already have separate modules.
Retain SQLite and the current entry points. Keep legacy agents clearly marked as
comparisons, outside the explanation of the default path.
