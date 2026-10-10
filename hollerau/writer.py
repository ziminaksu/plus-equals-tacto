"""The e-mail writer: the LLM gets the finished numbers and arguments and only formulates.

It must not change a figure, add a data ID or promise anything not in the term sheets; the
compliance check runs on its text and, if anything is off, the template is sent instead.
"""

import json

from .agent import describe

SYSTEM = """You write e-mails for the purchasing team of Hollerau Pumpenwerke, a German pump maker,
to an industrial supplier. Code has already decided the offer and the arguments; you only write.

Rules:
- Keep EVERY argument sentence's data ID and figure exactly as given (you may rephrase around them,
  one argument per sentence). Add no other data IDs and no other numbers than those given.
- Present the options exactly as given (prices, days, months, Incoterms). Do not invent terms.
- Never mention urgency, deadlines, a budget, or that we lack alternatives. No threats.
- Polite, factual, warm where the notes show a long relationship; at most 130 words.
- If the supplier seems short of cash and an option pays faster, say we can pay faster.
- End with "Kind regards, Purchasing, Hollerau Pumpenwerke". Output only the e-mail body."""


def llm_writer(complete):
    def write(ctx):
        d = ctx["dossier"]
        user = {
            "round": ctx["round"],
            "supplier_status": ctx["status"],
            "arguments_keep_ids_and_figures": ctx["claims"],
            "options": [describe(s, ctx["standard"]) for s in ctx["sheets"]],
            "supplier_notes": d.notes[-5:],
            "supplier_short_of_cash": d.cash_short,
            "supplier_wants_partnership": d.wants_partnership,
            "ask_for_cost_breakdown": ctx["round"] <= 2,
        }
        return complete(SYSTEM, json.dumps(user, ensure_ascii=False)).strip()

    return write
