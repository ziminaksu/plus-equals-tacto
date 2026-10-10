# P02 and P18 retest: 10 October 2026

The user authorised two new sessions after the v5.1 repair: one P02 and one P18. Both used the unchanged published code at `b3498a9adb5cb7a4cba9d2e9b665ad6ac46b0918`, with Astra as negotiator and independent reviewer. No additional sessions were started.

| Case | Previous run | This run | Earlier best | Deal |
|---|---:|---:|---:|---|
| P02 | 0.156989 | **0.156989** | 0.156989 | EUR 368.45, 14-day payment, no index |
| P18 | 0.000000 | **0.339633** | 0.339633 | EUR 5.60, 14-day payment, 24 months, AS-14404 index with 5% deadband |

P18 recovered from the previous timeout, but neither case exceeded its earlier best score. These are Arena's actual scores. [Structured results and decision timings](v51-arena-results.json) contain the session IDs and source revision.

## P02: the remaining discovery gap

The supplier never explicitly offered an indexed rebasing route in this run. The source-backed discovery gate therefore remained inactive. Astra's supplier-facing questions focused on payment terms; the controller continued unindexed price counters and accepted the same final offer as before. All six model calls succeeded. Logged counter decisions took about 7.5–19.6 seconds.

The repair handles an opportunity once the supplier offers it. It does not yet reliably discover that opportunity proactively. A next experiment should ask for a complete, non-binding indexed price comparison when the case permits it and price negotiation stalls, without waiting for the supplier to volunteer the route. That change was not made during this run, and no extra experiment was launched.

## P18: successful confirmation and close

The supplier quoted an alternative at EUR 5.60 with a shorter commitment and a 5% index deadband. Its estimated total cost was lower than the supplier's EUR 5.50 / 36-month / zero-deadband standing quote. Python requested confirmation of the exact alternative, the supplier agreed, and Python accepted its new standing ID. Arena's final total cost was EUR 270,542.35.

The opening reviewer call hit its local read timeout. The fallback still returned the opening decision in about 24.1 seconds; the Arena negotiation completed successfully. The negotiator's other calls succeeded. The result matches the earlier best P18 score, so this is recovery, not a new record or proof of superior reasoning.

## Limits

There was one stochastic session per case. Existing learning state was retained and backed up before the run. Timing safeguards and quote confirmation worked along the observed P18 path, but this does not guarantee future completion or higher scores. No score of 0.9 was achieved. Only evaluation documentation was changed after these runs.
