# Team += · Tacto Negotiation Arena (EHL Munich 2026)

An AI buyer agent for Hollerau Pumpenwerke that negotiates with the arena's supplier bots by e-mail.
**A configurable OpenAI API model chooses negotiation moves; code calculates total cost and enforces the rules.**

## New: Bayesian Qwen agent

The new implementation is available alongside the original agent. It learns supplier preference
ranges during negotiation, lets Python select complete deals, uses Qwen3.8-27B for routine
interpretation and Qwen3.8-2.4T-A95B for ambiguity, and records the reasoning in SQLite.

```bash
uv sync --all-extras --locked
# Set HF_TOKEN, ARENA_API_KEY and ARENA_DATA in .env
uv run tacto-bayes --run-id my-five-case-experiment --max-sessions 5 \
  --cases case:P01 case:P04 case:P05 case:P10 case:P11
```

[Architecture, coefficients, limitations and audit viewer](docs/ANALYTICAL.md).
The five-session cap applies to `tacto-bayes`; legacy commands below retain their original behaviour.

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
3. **Decide and write** (`hollerau/brain.py`): the configured model (`BRAIN_MODEL`, or Qwen when `QWEN_API_KEY` is
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
cp .env.example .env         # add NEW OpenAI and Arena keys locally, never commit them
```
Environment variables (`.env`, never committed):

| Variable | Meaning |
|---|---|
| `ARENA_URL` | `https://arena.tacto.ai` |
| `ARENA_API_KEY` | the team's arena key |
| `ARENA_DATA` | `data/package` |
| `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY` | OpenAI-compatible endpoint and key |
| `BRAIN_MODEL` | negotiator model (`gpt-4.1-mini` in `.env.example`); benchmark latency and costs |
| `QWEN_BASE_URL`, `QWEN_API_KEY`, `QWEN_MODEL` | optional: use Qwen instead |

## Run
```bash
uv run python -m hollerau local --brain llm        # local cases vs simulated suppliers (no arena quota)
uv run python -m hollerau play case:P01            # one practice case on the arena (uses 1 of 200)
uv run python -m hollerau run --set final --parallel 10 > final.log 2>&1   # Live Final, start before 12:00
```
The final runner never reads `/v1/events`, `/screen`, `/leaderboard` or `/results`.

## OpenAI API credits and safety
The ChatGPT subscription is separate from OpenAI API usage. Create a fresh project API key on platform.openai.com, set the project budget and rate limits, and check usage in the OpenAI dashboard. The model used by `hollerau/llm.py` is selected by `BRAIN_MODEL`, not just `LLM_MODEL`. Keep `QWEN_API_KEY` unset to use the OpenAI endpoint. A key ever pasted into a chat must be revoked and replaced. A GitHub connection does not grant this agent access to secrets on your Mac. Verify `git status --ignored` and `git diff --cached` before pushing.

## Entire
Entire checkpoint recording is enabled by `.entire/settings.json` (git-refs, telemetry off); Claude Code hooks are registered in `.claude/settings.json`. On the Mac verify the `entire` executable is installed and accessible (`command -v entire`) and that checkpoint/history recording works. The special event-specific requirements at https://hack.entire.io/ehl-munich-2026/ should be checked directly: the page could not be retrieved automatically. Do not remove `.entire/` or `.claude/` merely to tidy the repository.

## Credits
`arena_kit/`, `brief/` and the Dockerfile are the Tacto starter kit (MIT, `LICENSE-kit`); data CC BY 4.0
(`LICENSE-data`). Our code: `hollerau/`.
