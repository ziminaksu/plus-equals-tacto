# V11 stability batch: plan (written before any session opened)

**Runtime:** `astra-v10-traceable-plans+gemini` (Ilya's v10 structure merged into `ziminaksu`),
final authority and proposer on **gpt-5-mini** (Azure, `reasoning_effort=low`) through the chat path
(`ASTRA_BASE_URL`). Entry point: `./tools/run_azure.sh <case>`.

## Hypothesis

The v10 structure with a chat model can run every practice case to a deal without execution
failures. Changes since the last batch, each from a trace:

| Change | Trace that motivated it |
|---|---|
| Invalid chat answer → offline move instead of ending the case | earlier zeros after `FinalDecisionUnavailable` (P01, P03, P10, P18) |
| `normalize_selection` + allowed package IDs in the correction prompt | Azure P08/P18 closing move: packages attached to `accept` twice |
| Thread refresh before each RFQ decision; refused accept looks again | P05: supplier timeouts produced unseen offers, stale accept crashed |
| No bare reply with rival suppliers live | P05: reply without term sheet, supplier walked away |
| RFQ: no counter after a supplier's own step of 5 % or more; no accept while a supplier is untried | P05: push after 33.00→30.00 made it walk; closed at 34.00 |
| `caffeinate` during runs | P05: idle sleep for 87 minutes expired the session |

## Design

- Cases: P01 P02 P03 P04 P05 P07 P08 P10 P11 P18. Two sessions each, 20 starts maximum,
  two parallel streams. No replacement sessions.
- Primary metric: deal rate and number of sessions without execution failure; then score
  (opening-to-deal improvement), its spread per case, and the share of decisions the model made.
- Stop condition: two zero-score sessions caused by execution (crash, timeout), or the practice
  quota error.
- Every attempt is reported, including no-deals. Historical best per case is context, not a control.
