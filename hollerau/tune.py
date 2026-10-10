"""Search the strategy's knobs on the simulator, per category_goal, and write params.json.

    uv run python -m hollerau.tune --trials 60 --seeds 4            # scripted personas, minutes
    uv run python -m hollerau.tune --check --llm gpt-6.1-sol        # current params vs an LLM supplier

Random search with successive halving: every trial plays the goal's cases on a few seeds; the best
third is replayed on more seeds; the winner must also beat the current params on fresh seeds
(held-out), so we do not keep a lucky draw. Mean score, not the best one.
"""

import argparse
import os
import random
import statistics
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, fields

from .params import GOALS, Params, load_params, save_params

SPACE = {
    "anchor": (0.0, 0.6),
    "beta": (0.6, 5.0),
    "reserve_rounds": (1, 4),
    "accept_gap": (0.0, 0.3),
    "stall": (0.0, 0.08),
    "min_margin": (0.0, 0.12),
    "open_margin": (0.05, 0.25),
    "below_floor": (0.0, 0.08),
    "margin_buffer": (0.0, 4.0),
    "n_sheets": (1, 3),
    "claims_first": (0, 3),
}
_PKG = _CASES = None


def _init(seed, n_random):
    global _PKG, _CASES
    from arena_kit.data import DataPackage

    from .cases import suite

    _PKG = DataPackage(os.environ.get("ARENA_DATA", "data/package"))
    _PKG.lookup("")
    _CASES = suite(_PKG, seed=seed, n_random=n_random)


def _eval(job):
    """Mean score of params over the cases of a goal and seeds (runs in a worker)."""
    from .agent import StrategicAgent
    from .simulate import play_local

    params, goal, seeds = job
    scores = []
    for case in _CASES:
        if goal and case["buyer"]["category_goal"] != goal:
            continue
        for s in seeds:
            try:
                scores.append(play_local(case, StrategicAgent(params, _PKG), _PKG, seed=s)["score"])
            except Exception:
                scores.append(0.0)
    return statistics.mean(scores) if scores else 0.0


def sample(rng, base):
    kw = {}
    for name, (lo, hi) in SPACE.items():
        kw[name] = rng.randint(lo, hi) if isinstance(lo, int) else round(rng.uniform(lo, hi), 3)
    # half the trials stay near the current params (local search), half explore
    if rng.random() < 0.5:
        kw = {
            k: (v if rng.random() < 0.4 else getattr(base, k))
            for k, v in kw.items()
        }
    return Params(**kw)


def tune_goal(pool, goal, base, trials, seeds, rng):
    cands = [base] + [sample(rng, base) for _ in range(trials)]
    s1 = list(range(seeds))
    scores = list(pool.map(_eval, [(p, goal, s1) for p in cands]))
    ranked = sorted(zip(scores, range(len(cands))), reverse=True)[: max(3, len(cands) // 3)]
    s2 = list(range(seeds, seeds * 3))
    finals = list(pool.map(_eval, [(cands[i], goal, s2) for _, i in ranked]))
    best_i = max(range(len(ranked)), key=lambda k: finals[k])
    best = cands[ranked[best_i][1]]
    held = list(range(1000, 1000 + seeds * 2))
    b_new, b_old = pool.map(_eval, [(best, goal, held), (base, goal, held)])
    return (best, b_new, b_old) if b_new > b_old else (base, b_old, b_old)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hollerau.tune")
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--random-cases", type=int, default=60)
    ap.add_argument("--goals", default=",".join(GOALS))
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--check", action="store_true", help="only score the current params")
    ap.add_argument("--llm", default=None, help="check against an LLM supplier, e.g. gpt-6.1-sol")
    args = ap.parse_args(argv)
    current = load_params()
    if args.check:
        return check(current, args)
    rng = random.Random(7)
    out = dict(current)
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(11, args.random_cases)) as pool:
        for goal in args.goals.split(","):
            best, new, old = tune_goal(pool, goal, current[goal], args.trials, args.seeds, rng)
            out[goal] = best
            changed = {f.name: getattr(best, f.name) for f in fields(Params) if getattr(best, f.name) != getattr(current[goal], f.name)}
            print(f"{goal:14s} held-out {old:.3f} -> {new:.3f}  {changed or 'kept'}", flush=True)
    if not args.no_save:
        save_params(out)
        print("saved hollerau/params.json")


def check(current, args):
    """Current params against scripted personas or an LLM supplier (costs API calls)."""
    from arena_kit.data import DataPackage

    from .agent import StrategicAgent
    from .cases import suite
    from .simulate import play_local

    pkg = DataPackage(os.environ.get("ARENA_DATA", "data/package"))
    pkg.lookup("")
    cases = suite(pkg, seed=99, n_random=args.random_cases)
    llm = make_llm(args.llm) if args.llm else None
    rows = []

    def one(case):
        from arena_kit.agents.naive import NaiveAgent

        r = play_local(case, StrategicAgent(current, pkg), pkg, seed=5, llm=llm)
        n = play_local(case, NaiveAgent(), pkg, seed=5, llm=llm)
        return r, n

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(16 if llm else 1) as ex:
        for r, n in ex.map(one, cases):
            rows.append((r, n))
            print(f"{r['case_id']:16s} {r['goal']:14s} {r['type']:15s} ours {r['score']:.2f}  naive {n['score']:.2f}"
                  f"  deal {r['deal']} rounds {r['rounds']}", flush=True)
    print(f"mean ours {statistics.mean(r['score'] for r, _ in rows):.3f}  naive {statistics.mean(n['score'] for _, n in rows):.3f}")


def make_llm(model):
    import httpx

    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"}

    def complete(system, user):
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=60.0)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    return complete


if __name__ == "__main__":
    main()


__all__ = ["asdict", "main"]
