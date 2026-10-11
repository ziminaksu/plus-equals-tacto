# V11 Gemini round: all ten practice cases, one session each (2026-10-11, 05:19–05:40)

Runtime: Ilya's v10 structure on `ziminaksu`, decisions by free Gemini (`gemini-3.5-flash-lite` first,
Hugging Face `gpt-oss-120b` / `DeepSeek-V4.1-Flash` as backup on 429/503), `ASTRA_SAFE=1`.
Entry point `./tools/run_free.sh <case>`. Two parallel streams; every attempt is listed.

| Case | Score | Historical best | Decisions by the model | Note |
|---|---:|---:|---:|---|
| P01 | 0.878 | 0.957 | 4/4 | |
| P02 | 0.722 | 0.735 | 2/2 | near its ceiling (stabilise, relationship penalty) |
| P03 | 0.942 | 0.974 | 6/6 | |
| P04 | 0.860 | 0.860 | 3/3 | same deal in every recent run |
| P05 | 0.824 | 0.875 | 5/5 | RFQ fixes (refresh, urgency, accept within 1 %, compact board) |
| P07 | 0.585 | 0.779 | 3/3 | opened at 80 % of the ask, +0.02 steps → final at once (fixed in f76db65) |
| P08 | 0.769 | 0.770 | 5/5 | |
| P10 | 0.562 | 0.686 | 2/3 | accepted the dearer of two sheets in one final (fixed in 59634f0) |
| P11 | 0.626 | 0.710 | 6/6 | steps of 0.1–0.2 against 46.00 (step rule in f76db65 came after its start) |
| P18 | 0.587 | 0.654 | 4/4 | |

**Ten deals out of ten, no execution failure, 40 of 41 decisions by the model** (one board fallback
after two answers with an unknown placeholder). Mean of this round 0.736; mean of historical bests 0.800.

Changes committed during the round (f76db65 at 05:24:56, 59634f0 at 05:30:27) applied only to sessions
started after them; the table says which. A single run per case is exploratory, not a matched comparison.
