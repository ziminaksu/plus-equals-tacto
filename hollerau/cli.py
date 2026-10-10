"""`hollerau` command: our agent on the kit's play loop - locally, on arena-sim, or on the arena.

    uv run python -m hollerau local                      # all local cases vs simulated suppliers (no quota)
    uv run python -m hollerau local --llm-supplier       # the suppliers played by an LLM (API credits)
    uv run python -m hollerau play case:P01              # ONE arena session (uses 1 of the 200 practice tries)
    uv run python -m hollerau run --set final            # the Live Final runner (waves, in parallel)

Every arena session caches its case file and opening quotes in hollerau/cases/ for local replays.
--writer llm lets the LLM (Qwen if QWEN_API_KEY is set, else WRITER_MODEL) write the e-mails;
the template is the fallback on any timeout, error or rule break.
"""

import argparse
import json
import logging
import os
import statistics

from arena_kit.cli import load_env


def make_agent_factory(writer="template", package=None, brain="llm"):
    """brain=llm: the LLM (GPT-6 / Qwen) chooses every move from the code's menu and writes;
    brain=code: the code decides and `writer` writes (template or LLM)."""
    from .agent import StrategicAgent
    from .brain import BrainAgent
    from .llm import make_complete
    from .params import load_params
    from .writer import llm_writer

    params = load_params()
    if brain == "llm":
        complete = make_complete("brain", timeout=25.0)
        print(f"brain: {complete.model} chooses every move; code checks the rules and is the fallback")
        return lambda: BrainAgent(params, package, complete)
    write = llm_writer(make_complete("writer", timeout=20.0)) if writer == "llm" else None
    return lambda: StrategicAgent(params, package, write)


class CachingAgent:
    """Wraps an agent: saves the case and its opening quotes the first time it sees them."""

    def __init__(self, agent):
        self.agent, self.seen = agent, False

    def decide(self, case, threads):
        if not self.seen:
            from .cases import cache_case

            try:
                cache_case(case, threads)
            except Exception:
                pass
            self.seen = True
        return self.agent.decide(case, threads)


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="hollerau")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lo = sub.add_parser("local", help="play local cases against simulated suppliers (no arena)")
    lo.add_argument("--llm-supplier", action="store_true", help="suppliers played by SIM_MODEL / Qwen")
    lo.add_argument("--writer", default="template", choices=["template", "llm"])
    lo.add_argument("--brain", default="code", choices=["code", "llm"])
    lo.add_argument("--cases", type=int, default=20, help="random cases on top of kit, letter and cached cases")
    lo.add_argument("--only", default=None, help="case ids, comma-separated")
    lo.add_argument("--seed", type=int, default=5)
    lo.add_argument("--show", action="store_true", help="print every e-mail")
    p = sub.add_parser("play", help="play ONE arena case (uses a practice try)")
    p.add_argument("case_id")
    p.add_argument("--writer", default="llm", choices=["template", "llm"])
    p.add_argument("--brain", default="llm", choices=["code", "llm"])
    r = sub.add_parser("run", help="play every case of a set (final: the wave runner)")
    r.add_argument("--set", default="practice")
    r.add_argument("--writer", default="llm", choices=["template", "llm"])
    r.add_argument("--brain", default="llm", choices=["code", "llm"])
    r.add_argument("--parallel", type=int, default=10)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(message)s")

    from arena_kit.data import DataPackage

    package = DataPackage(os.environ.get("ARENA_DATA", "data/package"))
    package.lookup("")
    factory = make_agent_factory(args.writer, package, args.brain)
    if args.cmd == "local":
        return local(args, package, factory)

    from arena_kit.client import ArenaClient, ArenaError
    from arena_kit.cli import summary
    from arena_kit.play import RemoteTable, hosted, play, play_all, play_waves

    client = ArenaClient()
    if args.cmd == "play":
        table = RemoteTable(client)
        try:
            result = play(table, args.case_id, CachingAgent(factory()))
        except ArenaError as e:
            raise SystemExit(str(e)) from None
        print(json.dumps(summary(result), indent=2))
        if replay := client.session(table.session_id).get("replay_url"):
            print(f"replay: {os.environ['ARENA_URL'].rstrip('/')}{replay}")
    elif args.set == "final":
        out = play_waves(client, lambda: CachingAgent(factory()), 5, min(args.parallel, 10))
        print({c: (r if isinstance(r, Exception) else summary(r)) for c, r in out.items()})
    else:
        ids = [c["case_id"] for c in hosted(client.cases(args.set))]
        out = play_all(lambda: RemoteTable(client), ids, lambda: CachingAgent(factory()), min(args.parallel, 10))
        for cid, res in out.items():
            print(cid, res if isinstance(res, Exception) else summary(res))
    if client.practice_remaining is not None:
        print(f"practice sessions left today: {client.practice_remaining}")


def local(args, package, factory):
    from arena_kit.agents.naive import NaiveAgent

    from .cases import suite
    from .llm import make_complete
    from .simulate import play_local

    cases = suite(package, seed=99, n_random=args.cases)
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["case_id"] in keep]
    llm = make_complete("sim", timeout=60.0) if args.llm_supplier else None
    if llm:
        print(f"suppliers played by {llm.model}")
    from concurrent.futures import ThreadPoolExecutor

    def one(case):
        ours = play_local(case, factory(), package, seed=args.seed, llm=llm, verbose=args.show, log=True)
        naive = play_local(case, NaiveAgent(), package, seed=args.seed, llm=llm)
        return ours, naive

    rows = []
    with ThreadPoolExecutor(12 if (llm or args.writer == "llm" or args.brain == "llm") and not args.show else 1) as ex:
        for ours, naive in ex.map(one, cases):
            rows.append((ours, naive))
            flag = "" if not ours["problems"] else f"  RULES: {ours['problems'][:2]}"
            print(
                f"{ours['case_id']:15s} {ours['goal']:14s} {ours['type']:15s} ours {ours['score']:.2f} "
                f"naive {naive['score']:.2f}  deal={ours['deal']} rounds={ours['rounds']}{flag}",
                flush=True,
            )
    m = statistics.mean(o["score"] for o, _ in rows)
    n = statistics.mean(x["score"] for _, x in rows)
    broken = sum(bool(o["problems"]) for o, _ in rows)
    print(f"\nmean score  ours {m:.3f}   naive {n:.3f}   cases {len(rows)}   rule problems in {broken} cases")


if __name__ == "__main__":
    main()
