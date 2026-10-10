"""Hollerau buyer agent: code decides (targets, term sheets, accept/walk), an LLM only writes.

Modules:
  params    the tunable knobs, per category_goal, loaded from params.json
  levers    term-sheet packages, the price that hits a target C, the supplier's floor price
  intel     the dossier: supplier estimate (full cost, cash rate) and checked arguments with figures
  agent     StrategicAgent - drop-in for the kit's play loop (`decide(case, threads)`)
  persona   a simulated supplier with hidden economics (optionally an LLM at the desk)
  cases     practice-like cases: the kit's sim cases, cases rebuilt from the data, cached arena cases
  simulate  plays the agent against personas in-process: no HTTP, no quota
  tune      searches the knobs on the simulator, per category_goal
"""

from .agent import StrategicAgent
from .params import Params, load_params

__all__ = ["Params", "StrategicAgent", "load_params"]
