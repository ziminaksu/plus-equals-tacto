# V7: preserve supplier-cost evidence and learn from practice feedback

P02 v6 reduced the unit price but scored 0.096648, below the earlier 0.156989. Its relationship cost was €126,143.57 versus an estimate of €54,255.00. The source estimate of production cost (€374.95/unit) had not reached the final reviewer; an uncalibrated quote-implied mixture reduced the working cost estimate to about €338.

## Changes

- Both Astra roles now receive the original should-cost fact, reference and uncertainty, even when that evidence argues against a price reduction. Supplier-facing argument selection remains separate from internal evidence.
- `SupplierEconomics` supplies independent cost scenarios. Acceptance, rejection, concessions and statements no longer shift this cost distribution. The earlier 50/50 quote-implied cost mixture and quote-profitability reweighting are removed.
- SQLite stores whitelisted completed-practice terms, actual cost components, predicted components and forecast errors. Existing completed hosted runs are migrated from their audit records. Scores, `C_best`, leaderboard data and Live Final outcomes are excluded from calibration.
- Positive relationship penalties are inverted through the published formula into an **effective-cost interval**, allowing uncertainty in supplier financing and cash value. Zero penalty supplies only an upper bound. Duplicate observations do not create false confidence. Conflicting intervals are flagged and widened, not silently averaged. These are estimates, not access to audited production costs.
- Calibration is restricted to the same supplier, practice case and public case context. It is not transferred to unfamiliar final suppliers. Original public evidence remains visible as a separate cost scenario.
- For strategic/bottleneck goals, numerical search proposes mean-cost and downside-cost packages across payment and index options, including prices above the current offer. Astra may select these packages, its own proposals, questions or closure. Python does not force a selected optimum or treat it as a guaranteed supplier quote.
- Every proposed package shows its cost difference from the standing offer and opening under shared cost scenarios. The standing offer is also compared with previous actual practice packages. Historic offers still require fresh confirmation.
- Completed practice feedback is persisted at the end of the shared play loop. The CLI's caching wrapper forwards session/deadline/final-authority methods so these behaviours remain available through the ordinary CLI.

## Explicit assumptions and limits

Public should-cost uncertainty remains an estimate. Practice inversion uses financing scenarios of 4–18% plus the existing supplier estimate, and a ±0.5% effective cash-value allowance. These are adjustable modelling assumptions, not statistically calibrated confidence intervals. A positive penalty can identify an effective cost much more closely than an acceptance message, but other unobserved supplier cash effects may still invalidate the inference.

The cost menu is calculated with a bounded price grid and two refinements. It is an approximate menu, not proof of a global optimum. Supplier acceptance remains uncertain. A second Astra call can still make a poor decision, and an unavailable final call still stops rather than silently handing control to Python.

## Evaluation

Per the user's instruction, **no local tests, simulator runs or private model replays** are used for this update. Static syntax/name checks, diff review and publication checks were performed. The authorised hosted evaluation completed **one P02 and one P18 run**, with no replacement sessions: P02 scored **0.254765**, while P18 scored **0** following a supplier walkout. See [the complete results and remaining closing-policy weakness](v7-arena-results.md). The code was published before these runs; this outcome paragraph was added afterwards.

The implementation and its scoped development session are published using Entire before the hosted code freeze. Raw runtime logs, learning data and credentials stay ignored.
