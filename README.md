# += Tacto Negotiation Arena

Autonomous AI buyer for Hollerau Pumpenwerke · EHL Munich 2026.

The agent negotiates with suppliers by e-mail to minimise **total cost**, not just unit price. Deterministic code calculates offers and checks constraints; an OpenAI API model selects a move and drafts the message. A code-only fallback handles model errors and timeouts.

## Strategy

- Read the case, supplier data, quotes, history and evidence (`hollerau/intel.py`).
- Calculate total costs, alternatives and viable term sheets (`hollerau/agent.py`, `hollerau/levers.py`).
- Select a negotiating move and draft a concise e-mail (`hollerau/brain.py`).
- Validate must-haves, numeric claims, evidence IDs, offer limits and acceptance decisions (`hollerau/compliance.py`).
- Accept a suitable deal or walk away when the alternative is better.

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras
cp -n .env.example .env
uv run arena data
```

Fill `.env` locally with `ARENA_API_KEY` and `LLM_API_KEY`; never commit it. `.env.example` defines the OpenAI endpoint and default model. The negotiation model uses `BRAIN_MODEL` (default in the template: `gpt-4.1-mini`). OpenAI API usage is billed separately from ChatGPT plans.

## Run

```bash
uv run pytest -q
uv run python -m hollerau local --brain code --cases 5
uv run python -m hollerau local --brain llm --cases 5
uv run python -m hollerau play case:P01
```

For the Live Final, start before **11 October 2026, 12:00 (Munich time)**:

```bash
uv run python -m hollerau run --set final --brain analytical --parallel 10 > final.log 2>&1
```

Refresh the arena data after the Sunday 08:00 release. The final runner does not call the forbidden `/v1/events`, `/screen`, `/leaderboard` or `/results` endpoints. Submit the Git repository URL, the **exact final commit hash**, a short description and pitch slides on ehl.gg.

## Entire

The repository contains Entire configuration in `.entire/settings.json` with checkpoint mode `git-refs` and telemetry disabled. Scoped development-session imports and checkpoint delivery have been verified for the analytical-agent commits. For future local sessions, check:

```bash
command -v entire
entire --version
git show-ref | grep -i entire
```

Git configuration alone does not prove that checkpoints have been recorded. Follow the [EHL Entire event instructions](https://hack.entire.io/ehl-munich-2026/) for event-specific requirements.

## Project

- `hollerau/` — team agent and local simulation
- `arena_kit/` — Tacto API client, runner and cost model
- `brief/` — official competition requirements
- `tests/` — tests

Starter-kit code: `LICENSE-kit` (MIT). Data: `LICENSE-data` (CC BY 4.0).

## Team contributors

- [IlyaKats2005](https://github.com/IlyaKats2005)

## Bayesian Qwen agent

`hollerau.analytical` uses Qwen to interpret supplier evidence **before** Python updates estimates and selects a complete offer. It compares all standing term sheets, searches discounts and premiums for non-price trade-offs, prevents unproductive repeated demands, and saves cautious supplier/category learning in SQLite. A single small-model call also supplies prose; the large model is reserved for material unresolved interpretation.

See [setup, parameters and current decision flow](docs/ANALYTICAL.md), [initial five-session results](docs/evaluation/FIVE_PRACTICE.md), and [improved five-session comparison](docs/evaluation/IMPROVED_FIVE_PRACTICE.md). The existing agents remain available; select `--brain analytical` explicitly for the new agent in the team runner. Use `tacto-bayes` for bounded practice.

The implementation uses Entire's supported external-agent import to attach actual scoped Codex development records. Earlier unrelated history and credentials are excluded; original source-session IDs, timestamps and record hashes are preserved. See the provenance section of the setup guide. Commit trailers and remote checkpoint refs are verified after publishing.
