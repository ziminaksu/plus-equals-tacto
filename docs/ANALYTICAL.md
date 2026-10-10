# Analytical buyer agent

`hollerau.analytical` extends the team's existing repository without replacing its agent.
Python chooses actions; Qwen interprets source evidence and writes the non-binding prose.
The existing `hollerau.agent` and `hollerau.brain` remain available for comparison.

## Run the bounded practice experiment

```sh
uv sync --all-extras --locked
# Configure ARENA_API_KEY, HF_TOKEN and ARENA_DATA in ignored .env first.
uv run tacto-bayes --run-id my-five-case-experiment --max-sessions 5 \
  --cases case:P01 case:P04 case:P05 case:P10 case:P11
```

Every remote session start is reserved in SQLite **before** the request. A timeout or crash still
counts as an attempted session. Reusing the same run ID cannot exceed its original cap or rerun
the same case. The command refuses more than five starts, never replaces failed sessions, and
stops on an error. Do not delete its database or choose a new run ID to circumvent an agreed
limit. This limit applies to this runner; the team's legacy CLI has its original behaviour.

```sh
uv run python -m hollerau.analytical.report --run-id my-five-case-experiment
```

Open `hollerau/logs/audit.html` to inspect evidence, belief versions, candidate evaluations,
model calls, decisions and responses. The SQLite database is local and ignored by Git.

## Responsibilities

| Module | Contract |
|---|---|
| `intel.py` (existing) | Case-specific supplier dossier and source-grounded factual arguments |
| `analytical/beliefs.py` | Weighted joint scenarios; four preference parameters, a capacity-response parameter and uncertain production cost |
| `analytical/agent.py` | Valid candidate terms, full cost, uncertainty-aware choice and safe closure |
| `analytical/router.py` | HF small/large model routing, exact-source validation, timeouts and bounded prose |
| `analytical/storage.py` | Versioned append-only audit events; transactional practice-start reservation |
| `analytical/cli.py` | Five-session-limited practice driver, no automatic restart after errors |
| `analytical/report.py` | Read-only local audit viewer; no API calls |

## Interpretable parameters

Each supplier starts with 64 joint scenarios, reproducibly seeded from its ID. Priors are
heuristics derived from available cost estimates and reference terms, not calibrated truths.

- `r`: effective acceptance threshold in EUR/unit at the frozen opening reference terms.
- `b_pay`: EUR/unit value of receiving payment 30 days earlier.
- `b_term`: EUR/unit value of 12 extra contract months; it may be negative.
- `b_flex`: EUR/unit value of seven more delivery days.
- `full_cost`: uncertain actual cost estimate used for the published sustainability penalty;
  **it is not r**.
- `b_capacity`: only in capacity cases, a learned scenario coefficient penalising demands above
  the latest offered allocation; acceptance is multiplied by `exp(-b_capacity * fractional_uplift)`.
  Initial range 3–15 is a conservative modelling assumption, not a physical capacity limit.

Supplier effective value uses the kit's cash-equivalent adjustments for other terms, plus the
three preference terms. Payment is removed from that cash calculation to avoid double-counting
`b_pay`. Candidate accept probability is a logistic function of `(value-r)/tau` conditional on
not walking away. A separate pressure-response model predicts walking away. The residual
probability is a counteroffer. All probabilities are initial approximations.

After a new response, scenarios are reweighted by outcome likelihood with tempering and a
likelihood floor. Repeated copies of one observation cannot count twice. Parameter ranges and
the full weighted scenarios are stored after each update. Learning is session-local; practice
outcomes do not silently tune a global policy or leak into final runs.

**Not yet learned from five cases:** `tau`, walk-away intercept, pressure slope and repeat-demand
slope remain pooled defaults, explicitly labelled in every belief snapshot. They need controlled
comparisons before tuning. The system does not claim calibrated trust scores, infer hidden costs
as facts, or train Qwen weights. Text interpretations generate questions/context; they do not
arbitrarily rewrite numerical coefficients.

## Offer selection and safety

Candidate prices are 0%, 2%, 5% and 8% below the latest supplier quote. Enumerate reference and
one-lever changes, plus all combinations returned by the kit (up to its 600-package cap). Rank the best 64 by central estimated buyer cost
before evaluating all scenarios. This is bounded heuristic search, not a globally optimal solver.
After making an offer, reject a later package with a lower posterior mean supplier value, so a
counteroffer cannot accidentally trigger a worse price without a compensating concession.

Reject invalid options and mandatory-constraint violations. Compare
`P(accept)*deal_cost + P(counter)*continuation_cost + P(walk)*fallback_cost`,
then add 0.25 times the standard deviation of scenario expected costs. This is a risk preference,
not an empirically learned weight. Current feasible standing deals approximate continuation;
fallback expenditure without a qualified alternative is labelled a risk proxy, not a guaranteed
sourcing option. Report actual Arena score separately from this surrogate objective.

Use the official total-cost function with supplier full-cost scenarios so sustainability is not
silently zero. Consider all live rival offers before accepting or walking away. Stop and accept
an admissible standing offer at a final offer/agreement or with one move left. Acceptance checks
compare costs to the opening and fallback under the same estimates.

## Qwen and latency

Default IDs: `Qwen/Qwen3.8-27B:deepinfra`, `Qwen/Qwen3.8-2.4T-A95B:deepinfra`.
Override `QWEN_SMALL_MODEL` and `QWEN_LARGE_MODEL` in `.env`.
The small model analyses first. Contradictions, missing terms, interpretation ambiguity or a
scenario-dependent candidate ranking can trigger one large-model call. An unsupported quote,
malformed JSON or timeout preserves the uncertainty and falls back to code/template output.

The large model requires thinking; use its documented `reasoning_effort=low` to fit the turn
budget. Calls have a maximum 12-second timeout and share a 40-second decision deadline. HTTP
read timeouts can still incur provider charges. The log reports returned usage; it is not a
complete invoice when calls time out. A model being available is not proof of latency suitability.

The writer cannot change term sheets or numeric evidence: code appends the selected terms and
validated claim sentences. Source text is untrusted. Schema/quote checks constrain model output;
semantic interpretation still has uncertainty and the safe template remains available.

## Tests and provenance

`uv run pytest -q` includes local simulator coverage, coefficient update behaviour, source
validation, ambiguity routing and persistent quota checks. The optional hosted test stays skipped
unless dedicated `ARENA_TEST_*` variables are explicitly configured; never set these during a
quota-limited experiment.

Entire is configured in the repository. Desktop work outside this checkout's hook scope can be
attached using its supported external-agent import protocol: `tools/export_codex_session.py`
exports genuine visible records of the authorised implementation turn; the read-only
`tools/entire-agent-codex-export` adapter supplies them to `entire session attach`. No synthetic
session or invented activity is created. Earlier unrelated chat, image pixels and credentials
are omitted, transformations and source-record hashes are recorded, and the original Codex log
is untouched. Keep `.entire/settings.local.json` and `.entire/tmp/` untracked. Verify the resulting
commit trailer and checkpoint ref on GitHub after pushing; enabling hooks alone is not proof.
