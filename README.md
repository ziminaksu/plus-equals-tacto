# += Tacto Negotiation Arena

Autonomous AI buyer for Hollerau Pumpenwerke · EHL Munich 2026.

The agent negotiates with suppliers by e-mail to minimise **total cost**, not just unit price. In the analytical agent, Astra proposes packages and a separate Astra call chooses every final action. Python calculates costs and validates constraints. If final authorization fails, this path stops without sending a substitute offer or acceptance. Legacy agents retain their explicit fallback modes.

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

Fill `.env` locally with `ARENA_API_KEY` and `OPENAI_API_KEY`; never commit it. The default `play` and `run` commands now select the analytical Astra agent. `.env.example` also retains `LLM_API_KEY` and `BRAIN_MODEL` for explicit legacy `--brain llm` comparisons. OpenAI API usage is billed separately from ChatGPT plans.

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

## Analytical negotiation agent

`hollerau.analytical` uses `gpt-6-astra` for a negotiator and a separately prompted final decision-maker. The v7 controller gives Astra the last word on counters, questions, confirmation, acceptance and walking away, including after supplier agreement and near wave deadlines. Python cannot override that selection with its uncertain acceptance model.

Both roles receive consistent cost estimates, including relationship uncertainty. Astra can choose conditional payment/index/commitment packages, ask for cost walkthroughs and approval routes, and retrieve earlier same-supplier/case exchanges from SQLite. Historical quotes must be reconfirmed. Numeric evidence is rendered from verified facts. Qwen and model-free modes remain explicit comparisons. These mechanisms do not guarantee higher Arena scores.

V7 preserves original should-cost evidence, separates production-cost estimates from acceptance behaviour, and calibrates supplier economics using completed practice cost breakdowns. It includes higher-price sustainability alternatives and explicit downside comparisons. See [the implementation and assumptions](docs/evaluation/v7-supplier-economics.md). No local tests are run for this update.

The latest hosted P02 score is **0.097** with v6, below the previous best **0.157**: the relationship cost exceeded the estimate and outweighed the lower price. P18's last score remains **0.340** from v5.1; it has not been rerun with v6. See [the v6 P02 result and diagnosis](docs/evaluation/v6-p02-arena.md), [the v6 implementation validation](docs/evaluation/v6-final-authority.md), and [the earlier hosted evaluation](docs/evaluation/v51-arena-results.md). Per the user's latest instruction, future strategy evaluations use **P02 and P18 in Arena only**, with local tests stopped.

See [setup, parameters and current decision flow](docs/ANALYTICAL.md), [initial five-session results](docs/evaluation/FIVE_PRACTICE.md), and [improved five-session comparison](docs/evaluation/IMPROVED_FIVE_PRACTICE.md). `play` and `run` default to `--brain analytical`; the legacy agents remain explicitly selectable. Use `tacto-bayes` for bounded practice. `local` retains its model-free default.

The implementation uses Entire's supported external-agent import to attach actual scoped Codex development records. Earlier unrelated history and credentials are excluded; original source-session IDs, timestamps and record hashes are preserved. See the provenance section of the setup guide. Commit trailers and remote checkpoint refs are verified after publishing.
