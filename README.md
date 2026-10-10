# Team += · Tacto Negotiation Arena (EHL Munich 2026)

An AI buyer agent for Hollerau Pumpenwerke that negotiates with the arena's supplier bots by e-mail.
**GPT-6 runs the negotiation; code does the numbers and enforces the rules.**

## How it works
1. **Prepare** (`hollerau/intel.py`): reads the case file and the data package - should-cost, cost
   drivers and index series, the trigger letter vs. the contract's notice, scorecards, rival quotes,
   and the supplier's notes, letters and news (cash need, spare capacity, stale costing, approval
   ladder). Every argument is built from `facts.json` with its ID and figure, so it verifies.
2. **Compute** (`hollerau/levers.py`, `agent.py`): for every combination of negotiable terms the exact
   total cost C (`arena_kit.total_cost`), our estimate of the supplier's floor (`supplier_value`),
   the best deal it would accept (C_goal), our reserve (min of best opening, alternative, best rival)
   and a concession curve. From this code builds a **menu**: accept, hold, a step, a bigger step,
   equal-cost trades (e.g. faster payment for a lower price), each with its C.
3. **Decide and write** (`hollerau/brain.py`): GPT-6 (`BRAIN_MODEL`, or Qwen when `QWEN_API_KEY` is
   set) reads the supplier and the thread, picks the move and the arguments (max 3) and writes the
   e-mail, with a one-line reason logged to `hollerau/logs/` for the replay walk-through.
4. **Check** (`hollerau/compliance.py`): every message and accept is checked - must-haves, never
   worse than the alternative or the best opening, at most 3 term sheets / 3 arguments, only known
   data IDs, no figures the model made up, no leaks of urgency/budget/no alternative, no threats.
   Anything off, a timeout or an error -> the code's own move, so no round is lost.
5. **Close**: accept when the standing sheet is near our target, on a final offer below our
   reserve, on a stall or at the last round; stop pursuing a thread whose last word loses to our
   alternative (in an RFQ we never walk away while a rival is good).

Parameters per category goal (`hollerau/params.py`) are tuned on a local supplier simulator
(`hollerau/persona.py`, `tune.py`) with hidden economics built from the data, not on the arena.

## Setup
```bash
uv sync --all-extras
uv run arena data            # data package (again on Sunday after 08:00 for the release)
cp .env.example .env         # then fill in the variables below
```
Environment variables (`.env`, never committed):

| Variable | Meaning |
|---|---|
| `ARENA_URL` | `https://arena.tacto.ai` |
| `ARENA_API_KEY` | the team's arena key |
| `ARENA_DATA` | `data/package` |
| `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY` | OpenAI-compatible endpoint and key |
| `BRAIN_MODEL` | negotiator model (default `gpt-6.1-sol`) |
| `QWEN_BASE_URL`, `QWEN_API_KEY`, `QWEN_MODEL` | optional: use Qwen instead |

## Run
```bash
uv run python -m hollerau local --brain llm        # local cases vs simulated suppliers (no arena quota)
uv run python -m hollerau play case:P01            # one practice case on the arena (uses 1 of 200)
uv run python -m hollerau run --set final --parallel 10 > final.log 2>&1   # Live Final, start before 12:00
```
The final runner never reads `/v1/events`, `/screen`, `/leaderboard` or `/results`.

## Credits
`arena_kit/`, `brief/` and the Dockerfile are the Tacto starter kit (MIT, `LICENSE-kit`); data CC BY 4.0
(`LICENSE-data`). Our code: `hollerau/`.
