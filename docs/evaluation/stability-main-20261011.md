# Stability and record consistency — 11 October 2026

Policy: `ksu-stability-contract-v2`. Built on Ksu's `a8705b9` and the capped
GPT-6 branch at `9434b8b`. Runtime source fingerprint: `92a6475dae2d138ecb6c5a10df20e87ffec6cfeaf87025071a228b3918670982`.

## What changed

- Supplier refreshes share a six-second total deadline, including rate limiting.
  Changed threads refresh concurrently. Closed suppliers are removed immediately;
  unread or replaced quotes cannot keep an old standing offer available. Acceptance
  retries use bounded reads and require exactly equal terms under the new ID.
- Valid model-proposed packages remain selectable outside the heuristic concession
  schedule. Early confirmation/acceptance must compare a real available alternative,
  without forcing another counter. Confirmation is explicitly nonbinding.
- All approved packages survive rendering. At most two model-selected claims are
  accepted by both schema and validator; existing supported automatic attachments
  remain. Failed drafts restore evidence/question/pending state.
- Logs distinguish attempts, confirmed sends and unknown outcomes. Record schema 2
  includes confirmation packages and continuation/exit context. Raw returned model
  choices and actual per-call token settings remain visible. Response acceptance
  updates willingness estimates, not independent supplier cost distributions.
- Contract fixtures now supply the current required decision fields and test current
  cost semantics. The billing test restores its environment. CI installs the local
  integration dependencies instead of silently skipping those checks.
- README and architecture now separate historical bests from actual measured batches.
  Earlier result files are not rewritten. Entire exports redact credential patterns,
  configured secrets and hidden benchmark values in nested tool outputs.

## Verification

**202 passed, 1 skipped** in the full local suite. The single skip is the deliberately
unconfigured hosted Arena test. The local HTTP contract simulator is included; its
results establish protocol behavior, not negotiation quality. Focused lint, Python
compilation and whitespace checks passed. GitHub runs the same full suite; merging
is conditional on its successful check in [PR #8](https://github.com/ziminaksu/plus-equals-tacto/pull/8).

The first sandboxed suite could not bind the local test server; the full suite
subsequently ran successfully with local-server permission. No hosted session or
paid model request was used for this revision.

## Scores and spending

| Evidence | Recorded result | Interpretation |
|---|---:|---|
| Historical reported best per case | 0.808 mean | Mixed versions and attempts; not a current batch |
| [Full Azure batch](azure-all-cases-20261011.md) | 0.624269 mean; 9/10 deals | Includes the P05 no-deal |
| Previous Azure P18 | 0.508944 | Separate exploratory attempt |
| [Funded GPT-6 P18](budget-recovery-20261011.md) | 0.466961 | No demonstrated improvement |
| This revision | No live score | Free engineering verification only |

The unchanged shared $1 ledger accounts for **$0.499877**, leaving **$0.500123**
of the authorized improvement allowance, with no unknown-outcome reservation.
**Additional spend: $0.** This is a conservative local spending ledger, not the
provider's account balance or invoice. The Azure budget is separate.

Limits remain: supplier responses vary, response probabilities are not calibrated,
and asynchronous suppliers may expire despite bounded refreshes. Passing tests does
not guarantee a higher score or perfect operation on every unseen case.
