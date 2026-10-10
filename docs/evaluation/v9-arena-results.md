# V9 Arena results — stopped for architecture review

Evaluated commit: `b7c1dbc4c377c39bf7a52534a026f53d61abf77a`. Policy: `astra-v9-category-playbooks`.

Seven cases were selected. Six sessions completed; the user stopped further
experiments while P07 was already running. P07 finished, and P08 never started.
No local tests, simulations, LLM replays or replacement sessions ran.

## Outcomes

| Case | Previous best | Previous latest | V9 | Change vs best |
|---|---:|---:|---:|---:|
| P01 | 0.619 | 0.619 | 0.784 | +0.165 |
| P02 | 0.255 | 0.255 | 0.255 | +0.000 |
| P05 | 0.433 | 0.383 | 0.470 | +0.038 |
| P07 | 0.648 | 0.648 | 0.694 | +0.046 |
| P08 | 0.383 | 0.383 | Not started | — |
| P10 | 0.686 | 0.686 | 0.663 | -0.023 |
| P11 | 0.626 | 0.626 | 0.543 | -0.084 |

Three improved over their previous best, one tied and two declined. All six
completed sessions produced deals. Each is a single new run; historical best
and latest values are context, not matched control runs.

## Observed differences

| Case | What happened | What we can conclude |
|---|---|---|
| P01 | Closed at EUR 136.80 with 14-day payment and April effectiveness. | Better realized cost and score than the previous best. This batch cannot isolate which change caused it. |
| P02 | Closed again at EUR 364.12 with 14-day payment and the indexed package. | Different available proposals did not change the final deal or score. |
| P05 | Approached all three suppliers and closed with Fuchsreiter at EUR 31.50. | Better result than prior best, but still below 0.7. |
| P07 | Closed at EUR 5.40, 14-day payment and a 36-month commitment. | Improved from 0.648 to 0.694. |
| P10 | Closed at EUR 31.70, full 23,400-unit volume, 24 months and 56-day lead time. Earlier best had EUR 31.40 and 36 months. | Full volume was secured; the desired delivery improvement did not occur and this deal cost more. |
| P11 | Closed at EUR 46.50, 300 ppm and zero complaint reimbursement; prior best price was EUR 46.00. | Same quality/reimbursement combination with a worse price. Earlier terms were not a live offer guaranteed in this session. |

## Execution evidence

| Role | Successful calls | Read timeouts |
|---|---:|---:|
| Astra proposer | 3 | 16 |
| Astra final decision | 20 | 0 |

The advertised two-call architecture often ran without fresh proposer output.
This is an execution diagnosis, not proof of the cause of every poor result.
P05 also logged an attachment-budget warning and continued with received terms.
No completed session in this report was replaced.

## Stopping and reproducibility

- The runtime source hashes in the frozen manifest remained unchanged through all six sessions.
- Group A had four reserved starts (P01, P02, P05, P07). Its durable local allowance was lowered from five to four to block P08 after the user requested a pause in experiments.
- P07 completed. Before P08 reservation, the CLI raised `ValueError: cannot change a run's practice cap`. This was the intentional queue stop; it was not an Arena failure for P07 or an opened P08 session.
- Group B had already completed P10 and P11. Total starts: six.
- The stop changed the run allowance, not supplier messages, scores or runtime policy.

Multiple strategy changes, memory integration and timing changes shipped together.
Memory and supplier/model variation were not controlled against a matched rerun.
This batch therefore supports operational observations and exploratory comparisons,
not causal claims about individual fixes.

## Evidence

- [Frozen baseline](v9-baseline.json)
- [Implementation scope](v9-category-playbooks.md)
- [Machine-readable outcomes, decisions and exchanges](v9-arena-results.json)
- [Current architecture](../CURRENT_ARCHITECTURE.md)
- [Proposed decision contract](../DECISION_CONTRACT.md)
