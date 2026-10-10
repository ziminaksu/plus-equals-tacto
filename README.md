# += Tacto Negotiation Arena

Autonomous buyer for Hollerau Pumpenwerke · EHL Munich 2026.

**Purpose:** negotiate executable agreements that improve total buyer cost under
the case's constraints. Price, supply coverage, delivery, quality, financing and
applicable relationship costs all matter.

## Start here

| What you need | Read |
|---|---|
| What the system actually does, and who decides | [Current architecture](docs/CURRENT_ARCHITECTURE.md) |
| A clear contract for the next structural improvement | [Decision contract](docs/DECISION_CONTRACT.md) |
| Actual latest results, including failures | [V10 P02 report](docs/evaluation/v10-p02-results.md), [V9 baseline](docs/evaluation/v9-arena-results.md) |
| Setup, bounded runs and inspection | [Operating guide](docs/ANALYTICAL.md) |
| Original challenge and starter kit | [Brief](brief/README.md), [starter-kit guide](README-kit.md) |
| Earlier designs and evaluations | [Historical analytical notes](docs/history/ANALYTICAL-through-v82.md), [strategy announcements](docs/history/README-strategy-history.md) |

## Current state

Policy **`astra-v10-traceable-plans`** keeps Ksu's bargaining improvements and
adds one shared deadline, lossless prompt compaction, mandatory conditional plans,
linked reply-error records and reproducible experiment metadata. Python prices
and validates; Astra makes the final strategic choice; SQLite retains the evidence.

The v9 baseline had 16/19 proposer timeouts. V10 removes its approximately
7.2-second effective read limit and allocates up to 20 seconds within a shared
55-second turn budget. After an initial validation failure, a separately authorized
P02 run completed: all six calls returned and all three final decisions validated.
Its score was **0.235**, below the previous **0.255**; execution recovered without
demonstrating a strategy improvement. See the [results](docs/evaluation/v10-p02-results.md)
and [implementation scope](docs/evaluation/v10-traceable-plans.md).

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras
cp -n .env.example .env
uv run arena data
```

Configure `ARENA_API_KEY`, `ARENA_DATA` and `OPENAI_API_KEY` in ignored `.env`.
Never commit credentials. `play` and `run` default to the analytical Astra agent;
legacy modes remain explicit comparisons. See the operating guide before starting
practice sessions. Both authorized P02 starts are used; further Arena runs need
authorization. Local runtime tests remain stopped.

## Repository map

- `hollerau/analytical/` — default negotiation controller, models, evidence and storage.
- `arena_kit/` — API protocol, runner and published cost calculation.
- `hollerau/agent.py`, `brain.py` and other legacy modules — explicit comparison paths.
- `docs/` — current architecture and operating contract; `evaluation/` has versioned evidence.
- `hollerau/logs/` — ignored local databases and raw traces.
- `brief/`, `tests/`, `tools/` — challenge reference, existing tests and developer tools.

## Publishing with Entire

Entire is enabled with `git-refs` checkpoints and telemetry disabled. The team uses
its external-agent import to attach actual scoped Codex session records, excluding
unrelated history, internal reasoning and credentials. Verify the commit's
`Entire-Checkpoint` trailer and the corresponding remote checkpoint ref after
publishing. Configuration alone is not evidence of a recorded session.

Follow the [EHL Entire instructions](https://hack.entire.io/ehl-munich-2026/).
Submit the repository and exact final commit hash required by the challenge.

Starter-kit code: `LICENSE-kit` (MIT). Data: `LICENSE-data` (CC BY 4.0).

## Team contributors

- [IlyaKats2005](https://github.com/IlyaKats2005)
