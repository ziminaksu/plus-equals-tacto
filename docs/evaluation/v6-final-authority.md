# V6: Astra has final decision authority

This change addresses the P02 payment concession and P18 premature closure found in the v5.1 audit. At implementation time it had no hosted Arena score. The subsequent [single P02 Arena run](v6-p02-arena.md) scored **0.096648**, below the previous **0.156989**. P18 has not been rerun with v6; its last observed score remains **0.339633**. The user subsequently stopped local testing and restricted future strategy evaluations to P02/P18 in Arena.

## Changes

- A separate Astra call selects every outgoing action, including information requests, confirmation, acceptance and walking away. Python validates and renders its exact selection; numerical response forecasts cannot veto it.
- Supplier `agreed` and `final_offer` statuses remain inputs to Astra. They do not trigger automatic acceptance. Confirming an indicative quote no longer promises to conclude.
- One final decision board compares all live suppliers. It presents direct costs, expected total costs, component breakdowns and weighted uncertainty consistently across both Astra roles. Relationship costs remain included; case-specified weights are preserved.
- Conditional payment/index/commitment packages include compensating prices at approximately equal direct buyer cost. Astra can choose up to three alternatives on later turns as well as the opening. A paired package may still have different relationship risk or supplier value.
- Payment-price and indexed-rebase inquiries are available without waiting for the supplier to volunteer them. Supplied notes make cost-walkthrough and approval-route questions available. Each standalone question reserves time for a reply and closure.
- Same-supplier/case SQLite retrieval supplies earlier exchanges, requests and quoted terms with provenance and an explicit reconfirmation requirement. It excludes result/benchmark records and current-session history. The generic Live Final path records exchanges too.
- Astra selects verified numeric evidence rather than losing it to a blanket digit ban. Python renders the sourced figures and complete terms. Unverified free-text factual assertions are not transmitted.
- A failed final authorization raises an explicit error; there is no silent strategic fallback. The move budget and wave-cap closure retain the same authority contract. Final decisions and their input boards are recorded for audit.

## Private real-model checks

One saved decision was replayed for each of P02 and P18, using the actual first supplier response from the v5.1 run and a learning snapshot from before that run. Public fictional challenge data was supplied to OpenAI. No Arena client was used; no supplier messages, new sessions or score queries were sent.

| Saved state | Astra's selected action | Observed time |
|---|---|---:|
| P02 | Re-propose the earlier indexed/rebased package and ask for a fresh fixed-versus-indexed comparison | 15.382 s |
| P18 | Ask for priced payment alternatives rather than automatically confirming and accepting the indicative quote | 17.406 s |

There were four attempted OpenAI calls in total: two proposal calls and two final decisions. The P02 proposal call timed out; its final call still produced a valid decision from available evidence and historical packages. P18 completed both calls. Neither final decision was overridden by Python. The raw boards, messages and usage records remain in ignored `hollerau/logs/v6-live-replay/`.

These were development smoke checks of the live model integration, not negotiation rollouts, independent trials or evidence of better scores. The supplier was not asked to accept these proposals. Subsequent memory and runner guards were checked locally. There is no claim that either action would close a deal or achieve 0.9.

To reproduce a saved-state check with local logs (OpenAI calls require `--live-model`):

```sh
uv run python -m tools.replay_astra_decisions
uv run python -m tools.replay_astra_decisions --live-model
```

The tool supports only P02/P18, one decision each, at most two model calls per case. It opens source databases read-only, checks that the learning snapshot predates the replayed run, uses an in-memory writable copy, and never constructs an Arena client.

## Regression coverage and limits

`tests/test_astra_authority.py` checks final-choice precedence, continued negotiation after supplier agreement, conditional packages, proactive discovery, consistent cost arithmetic, source-labelled memory, stale/foreign IDs, unsupported evidence, invalid selections, timeouts and wave-cap routing. It verifies that failed final authorization produces no substitute decision. Existing tests cover supplier responses and the local HTTP simulator.

Final validation: **156 passed, 1 optional hosted test skipped** (46.70 s), including 29 new authority regressions. Analytical-module/new-test/replay-tool/runner lint and Git whitespace checks passed. Credentials were absent from all 17 changed/new source and documentation files. `play` and `run` now default to the analytical Astra path; the local simulator retains its model-free default.

Run `uv run pytest -q`. The optional hosted test requires explicit `ARENA_TEST_URL` and `ARENA_TEST_KEY`; these were not configured. Passing local tests verifies software behaviour, not negotiation quality or calibration of supplier estimates.

Known limitations: a failed final decision can leave a live negotiation unfinished; history retrieval is deliberately restricted to the same case and supplier; the final reviewer chooses from validated proposed/calculated packages and question templates, rather than inventing new unchecked terms inside its last response. Buyer cost calculations still depend on uncertain supplier production costs for relationship penalties. Neither two Astra roles nor a strict response schema guarantees good strategy.

The Responses integration uses [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) and also validates action membership and current protocol state locally.
