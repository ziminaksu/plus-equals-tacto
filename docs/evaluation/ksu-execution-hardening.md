# Execution hardening on Ksu’s latest structure

Base: `9dfc5d6` on `ziminaksu`. This is the first reliability patch; opening windows,
concession schedules, supplier selection and cost weights are unchanged.

- Chat requests have a cancellable total monotonic deadline, including response bodies.
- Expired final decisions cannot trigger a Python fallback; fallback completion is checked again.
- Incomplete model output is rejected even if its text happens to parse as JSON.
- JSON-mode retries require a format-related error, rather than every HTTP 400.
- Explicit `ASTRA_COMPACT=0` disables compaction for chat providers.
- The free launcher requires explicit configuration for cross-provider fallback,
  preserves the runner exit status, exposes errors, and reports actual model/provider calls.
- Local ChatGPT authorization files are ignored.

Validation: six focused transport, deadline and existing thread-refresh tests passed;
shell syntax and targeted lint passed. No model calls or Arena sessions were started.
There is no measured negotiation-score improvement from this patch.

Remaining work: unify fallback validation/state updates with normal execution, replace
rigid strategy restrictions with conditional trade menus, calibrate response estimates,
and evaluate against a frozen baseline. Monotonic timing alone does not cover machine
suspend on every platform; keep the existing sleep prevention during live runs.
