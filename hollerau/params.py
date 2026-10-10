"""The knobs of the strategy. Everything else is computed from the case and the data.

`span` below is C_reserve - C_goal: from the best deal we think the supplier would ever accept
(C_goal) to the worst deal we would still take (C_reserve = min(C_open, C_alt)).
"""

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

GOALS = ("stabilise", "secure_supply", "quality_first", "leverage", "routine")
DEFAULT_FILE = Path(__file__).with_name("params.json")


@dataclass(frozen=True)
class Params:
    # first offer: this share of span BELOW C_goal (an anchor the supplier will not take)
    anchor: float = 0.15
    # concession curve target(t) = goal + (reserve - goal) * (t / T) ** beta; > 1 concedes late
    beta: float = 2.5
    # rounds kept back at the end of the thread (T = round_limit - reserve_rounds)
    reserve_rounds: int = 2
    # accept a standing sheet within this share of span above our current target
    accept_gap: float = 0.08
    # accept when the supplier conceded less than this share of span over its last two replies
    stall: float = 0.02
    # our guess of the supplier's minimum margin when we have no better data
    min_margin: float = 0.06
    # guess of its margin over full cost in its opening quote when there is no should-cost
    open_margin: float = 0.14
    # never offer below our estimated floor price by more than this share (insulting otherwise)
    below_floor: float = 0.02
    # stabilise / secure_supply: extra margin points we leave above the sustainable margin
    margin_buffer: float = 0.5
    # term sheets per e-mail (1-3); extra ones are equal-cost trades that probe what it values
    n_sheets: int = 2
    # arguments in the first e-mail (the rest are kept for later rounds; max 3 per e-mail)
    claims_first: int = 2

    def tuned(self, **kw):
        return replace(self, **kw)


def load_params(path=DEFAULT_FILE):
    """{goal: Params}; goals missing from the file get the defaults."""
    data = json.loads(Path(path).read_text()) if Path(path).is_file() else {}
    names = {f.name for f in fields(Params)}
    base = Params(**{k: v for k, v in data.get("default", {}).items() if k in names})
    return {g: base.tuned(**{k: v for k, v in data.get(g, {}).items() if k in names}) for g in GOALS}


def save_params(by_goal, path=DEFAULT_FILE):
    Path(path).write_text(json.dumps({g: asdict(p) for g, p in by_goal.items()}, indent=2) + "\n")
