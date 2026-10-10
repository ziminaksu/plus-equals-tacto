# V8.3: two Arena runs, no score improvement

Run `ehl-v83-memory-two-20261010` used source commit
`7c646fdebf59878234a8974a684804a78e768998`, Entire checkpoint
`01M4KEFBWM6P2NVN7GX2A1VG1X`. Exactly two sessions completed, one per case.
The analytical source and runner hashes remained unchanged during both sessions.
No local tests, simulations, model replays or replacement sessions ran.

| Case | Previous run | V8.3 | Previous best |
|---|---:|---:|---:|
| P02 | 0.254765 | 0.254765 | 0.254765 |
| P18 | 0.273018 | 0.273018 | 0.339633 |

## Recorded behaviour

P02 session `bf51092df64ae6f8`: Astra opened with EUR 367 fixed and EUR 364.12
copper-indexed alternatives, both with 14-day payment. It sent the shareable
forecast; the supplier acknowledged the evidence and accepted the indexed
alternative. Astra closed, citing poor prospects for further supported
concessions. Both proposer calls and both final-director calls succeeded.
The deal cost EUR 2,270,803.51 and met the required constraints.

P18 session `4211b33ca11e8be6`: opening board event 1172 contained the earlier
EUR 5.25 fixed buyer packages as selectable IDs `sup:70740:p4` (36 months) and
`sup:70740:p5` (24 months), linked to historical reply 855 and marked as opening
moves. Final Astra instead selected the same EUR 5.60/deadband and EUR
5.50/no-deadband indexed opening used in v8.1. The supplier returned EUR
5.60/no-deadband and EUR 5.70/deadband alternatives. Astra confirmed and accepted
EUR 5.70 with 5% deadband, 14-day payment and 24 months, costing EUR 275,373.46.
All required constraints were met.

All three P18 proposer calls timed out (11.202, 11.242 and 11.242 seconds).
All three final-director calls succeeded. Five actions across the pair were
Astra-authorized; there was no automatic replacement decision.

## Interpretation

The memory intervention exposed the missing historical buyer moves, but Astra
did not choose them in this P18 run. Therefore the missing menu entry alone
does not explain this run's unchanged result. Proposal timeouts remain an
observed execution problem; their causal effect on score is not established.
The historical EUR 5.25 route remains untested by this new policy because it
was not selected. The results do not prove that forcing it would help.

This is one run per case, without a matched baseline rerun. Comparison with
v8.1 also includes previously unevaluated v8.2 evidence retrieval and accumulated
memory. These runs show no measured improvement; they do not isolate every
component's causal contribution.

[Machine-readable results, messages, choices and model-call statuses](v83-arena-results.json).
