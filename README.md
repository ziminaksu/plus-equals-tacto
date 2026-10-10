# += Tacto Negotiation Arena

Autonomous buyer for Hollerau Pumpenwerke · EHL Munich 2026.

**Purpose:** negotiate executable agreements that improve total buyer cost under
the case's constraints. Price, supply coverage, delivery, quality, financing and
applicable relationship costs all matter.

## Start here

| What you need | Read |
|---|---|
| What the system actually does, and who decides | [Current architecture](docs/CURRENT_ARCHITECTURE.md) |
| A clear contract for the next structural improvement | [Decision contract — proposed](docs/DECISION_CONTRACT.md) |
| Actual latest results, including regressions and timeouts | [V9 Arena report](docs/evaluation/v9-arena-results.md) |
| Setup, bounded runs and inspection | [Operating guide](docs/ANALYTICAL.md) |
| Original challenge and starter kit | [Brief](brief/README.md), [starter-kit guide](README-kit.md) |
| Earlier designs and evaluations | [Historical analytical notes](docs/history/ANALYTICAL-through-v82.md), [strategy announcements](docs/history/README-strategy-history.md) |

## Current state

Policy **`astra-v9-category-playbooks`**, evaluated at commit `b7c1dbc`, combines
Ksu's negotiation changes with action/response memory and category-specific
packages. Astra proposes options and a separate Astra call selects the final move.
Python generates additional options, calculates costs, applies constraints and
sends the validated selection. SQLite retains exchanges and learning evidence.

Experiments are stopped for architecture review. Six v9 cases completed: three
improved over their previous best, one tied and two declined. P08 did not start.
16 of 19 proposer calls timed out; all 20 final calls succeeded. These results do
not isolate the effect of each simultaneous change. The new decision contract is
a proposed structure, not an implemented strategy or a promise of better scores.

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
practice sessions. This review starts no new runs or local tests.

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

Team contributor: [IlyaKats2005](https://github.com/IlyaKats2005).
