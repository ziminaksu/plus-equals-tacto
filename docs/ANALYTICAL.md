# Analytical agent — operating guide

Current policy: `astra-v10-traceable-plans`. Start with
[the current architecture](CURRENT_ARCHITECTURE.md) for responsibilities and
[the decision contract](DECISION_CONTRACT.md) for the implemented planning structure.
Earlier version descriptions and experiments are preserved in
[historical notes](history/ANALYTICAL-through-v82.md).

## Current authorization and status

The user authorized one P02 session after the v10 fixes. No P18 session is authorized for this batch. Local tests,
simulations and LLM replays remain stopped under the user's instruction. The
examples below explain operation; they are not instructions to launch a batch.

## Configuration

Use Python 3.12 and the repository dependencies. Keep secrets in ignored `.env`:
`ARENA_API_KEY`, `ARENA_DATA` and `OPENAI_API_KEY`. The default model roles both use
`gpt-6-astra`. Their separate prompts do not make their judgments statistically
independent. Qwen and model-free modes are explicit comparisons, not fallbacks
silently selected for this default path.

## Bounded practice, when authorized

Example of one explicitly authorized session:

```sh
uv run tacto-bayes --primary astra --reviewer astra \
  --run-id experiment-name --max-sessions 1 --cases case:P02 \
  --hypothesis "Verify proposer availability and linked plan outcomes"
uv run python -m hollerau.analytical.report --run-id experiment-name
```

The CLI permits up to five distinct cases per invocation. Reserve attempts before
HTTP. Failed or ambiguous starts still count; no automatic replacements. Reuse
the same run ID on inspection/recovery and do not change run IDs or databases to
bypass a cap. An interrupted process does not prove the remote session never opened.

To stop after the active session, create `hollerau/logs/stop-<run-id>` or use
`--stop-file PATH` and create that file. The runner checks it before each new
reservation and exits normally. It does not reset or mutate the allowance. V9's
manual allowance intervention remains documented in its historical report.

Every experiment records a hypothesis, source hashes, commit, public-data
fingerprint, initial memory fingerprint and model settings before opening a session.
These fingerprints identify differences; they do not by themselves control them.

## Inspect one decision

The SQLite `events` table links records by run, case, session and supplier:

| Event kind | Read it to answer |
|---|---|
| `experiment`, `case`, `opened` | Which configuration and public context were active? |
| `evidence`, `cost_evidence`, `coefficients` | Which facts and estimates were available? |
| `final_board` | Which packages, costs, actions and restrictions did Astra see? |
| `decision_record`, `decision` | What did Astra select and why? Which calls succeeded? What did it expect and plan to do next? |
| `plan_outcome`, `decision_dispatch` | Was the action attempted? How did the actual reply differ from the forecast? |
| `sent`, `received`, `exchange` | What was transmitted and what did the supplier return? |
| `observation`, `cost_feedback` | What was updated from that evidence? |
| `result`, `completed`, `error`, `final_decision_failed` | How did the session or action end? |

Raw logs and the database stay private. Publish sanitized, source-linked reports,
not credentials or hidden benchmark inputs. Scores belong to evaluation, not the
strategy retrieval context. Use the [v9 report](evaluation/v9-arena-results.md)
for the current measured batch.

## Source responsibilities

Use the file map in [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md), not old
version descriptions, to find the default execution path. `director.py` builds
options, invokes final selection and validates execution. `router.py` owns model
calls; `contracts.py` owns the current structured-output schemas. The current schema requires a conditional plan, and final validation checks its IDs
and prediction types before sending.

## Publish a change

Record the intended behavior and validation. Review the exact diff and exclude
credentials, local databases and unrelated files. Attach the authentic scoped
Codex records through Entire, then verify the commit trailer and remote checkpoint
reference alongside the pushed code. Preserve existing history and teammates' work.

Source parsing, documentation link checks and result aggregation are permitted
static/read-only checks here. They are not a substitute for runtime evaluation,
and must not be reported as successful Arena tests.
