"""Play an agent against simulated suppliers in-process: same message shapes as the arena, no HTTP,
no clock, no quota. Scores like the arena: (C_open - C_deal) / (C_open - C_best) with the
suppliers' true economics for the relationship term.
"""

import math
import random

from arena_kit.cost import must_haves_ok, score, total_cost
from arena_kit.play import latest, live_threads

from . import compliance, intel
from .persona import SimSupplier, random_traits


def make_suppliers(case, package, rng, llm=None):
    sups = {}
    for sid, (stated, std) in case["_openings"].items():
        dossier = intel.build(case, sid, package, stated.get("unit_price"))
        probe = {"standard": std, "full_cost": 1.0, "interest_rate": 0.08}
        from arena_kit.cost import supplier_value

        open_v = supplier_value(case, stated, probe)
        traits = random_traits(
            rng,
            open_v,
            should_cost=dossier.full_cost,
            cash_short=True if dossier.cash_short and rng.random() < 0.8 else None,
            persona="; ".join(dossier.notes[-4:]),
        )
        sups[sid] = SimSupplier(case, sid, traits, std, stated, llm=llm, rng=random.Random(rng.random()))
    return sups


def play_local(case, agent, package=None, seed=0, llm=None, verbose=False, log=False):
    rng = random.Random(seed)
    public = {k: v for k, v in case.items() if not k.startswith("_")}
    sups = make_suppliers(case, package, rng, llm)
    facts = dict(package.facts) if package else {}
    facts.update(case.get("facts") or {})
    threads = {sid: [s.opening_mail()] for sid, s in sups.items()}
    used, deal, steps, problems = set(), None, 0, []
    while live_threads(threads) and steps < 80:
        steps += 1
        d = agent.decide(public, threads)
        sid, msg = d["supplier_id"], d["message"]
        action = msg.get("action")
        if action:
            if action["type"] == "accept":
                deal = (sid, latest(threads[sid])["term_sheets"][0]["terms"])
            break
        if sum(m.get("from") == "buyer" for m in threads[sid]) >= case.get("round_limit", 10):
            problems.append(f"{sid}: message past the round limit")
            break
        if log:
            offers = {ts.get("term_sheet_id") for ev in threads.values() for m in ev for ts in m.get("term_sheets") or []}
            problems += [f"{sid}: {p}" for p in compliance.problems(public, msg, facts, offers, standard=sups[sid].standard)]
        reply = sups[sid].reply(msg, facts, used)
        threads[sid] += [{**msg, "from": "buyer"}, reply]
        if verbose:
            print(f"\n--- buyer -> {sid}\n{msg.get('body', '')}")
            for ts in msg.get("term_sheets") or []:
                print("   sheet:", ts["terms"])
            print(f"--- {sid} [{reply['status']}] claims={[r['result'] for r in reply['claim_results']]}\n{reply['body']}")
            if reply["term_sheets"]:
                print("   standing:", reply["term_sheets"][0]["terms"])
            print("   reasons:", sups[sid].trace[-1]["reasons"])
    if verbose:
        print(f"\n=== close: {d['message'].get('action')}")
    out = result(case, sups, deal, steps)
    out["problems"] = problems
    return out


def result(case, sups, deal, rounds):
    c_open = min(s.true_cost(s.opening) for s in sups.values())
    c_best_sup = min(s.best_c() for s in sups.values())
    alt = case["buyer"].get("alternative") or {}
    c_alt = total_cost(case, alt["terms"]) if (alt.get("terms") or {}).get("unit_price") else None
    c_best = min(c_best_sup, c_alt) if c_alt else c_best_sup
    if deal:
        sid, terms = deal
        s = sups[sid]
        c_deal = s.true_cost(terms)
        ok = must_haves_ok(case, terms, s.standard)
        sc = score(c_open, c_deal, c_best) if ok else 0.0
    else:
        c_deal, ok = None, None
        sc = score(c_open, c_alt, c_best) if c_alt else 0.0
    return {
        "case_id": case["case_id"],
        "goal": case["buyer"]["category_goal"],
        "type": case["type"],
        "deal": bool(deal),
        "c_open": c_open,
        "c_deal": c_deal,
        "c_best": c_best,
        "score": sc if math.isfinite(sc) else 0.0,
        "rounds": rounds,
        "walked": any(s.status == "walked_away" for s in sups.values()),
    }
