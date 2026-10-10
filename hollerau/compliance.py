"""The rules every outgoing message must keep (brief, api.md, CLAUDE.md). `problems()` lists what a
message breaks; the agent sends the template instead of an LLM text that breaks any of them, and
tests run it on every message of every simulated game.
"""

import re

from arena_kit.cost import must_haves_ok

ID_RE = re.compile(r"\b(?:idx|quote|offer|sc|qn|po|cost|fc|news|doc|ctr|sup|part):[\w.:@#/-]*\w")
CHECKED = ("idx:", "quote:", "offer:", "sc:", "qn:", "po:", "cost:", "fc:", "news:", "doc:", "ctr:")
LEAKS = re.compile(
    r"\burgent|\basap\b|as soon as possible|deadline|\bbudget|no (?:other )?alternative|only (?:possible )?supplier"
    r"|we depend|we rely entirely|desperate|running out|line (?:will )?stop|must have (?:it|them) by",
    re.I,
)
THREATS = re.compile(r"\bor else\b|legal action|blacklist|we will (?:sue|terminate)|last chance", re.I)
NUM_RE = re.compile(r"(?<![\w:@#/.-])\d[\d,]*(?:\.\d+)?")
MAX_ARGUMENTS, MAX_SHEETS, MAX_BODY = 3, 3, 8000


def arguments(body):
    """Sentences that cite checked data: each is one argument for the arena (an index pair too)."""
    sentences = re.split(r"(?<=[.!?])\s+", body)
    return [s for s in sentences if any(m.startswith(CHECKED) for m in ID_RE.findall(s))]


def problems(case, message, facts, offers=(), allowed_numbers=None, standard=None):
    """What this message breaks; [] if nothing. `allowed_numbers`: for an LLM text, the figures it
    may contain (term sheets and argument figures) - anything else could be a made-up number."""
    out = []
    action = message.get("action")
    if action:
        return out
    body = message.get("body") or ""
    sheets = message.get("term_sheets") or []
    if len(sheets) > MAX_SHEETS:
        out.append(f"{len(sheets)} term sheets (max {MAX_SHEETS})")
    for i, ts in enumerate(sheets):
        terms = ts.get("terms", ts)
        if set(terms) != set(case["negotiable"]):
            out.append(f"sheet {i}: fields {sorted(terms)} != negotiable {sorted(case['negotiable'])}")
        if not (terms.get("unit_price") or 0) > 0 or round(terms["unit_price"], 2) != terms["unit_price"]:
            out.append(f"sheet {i}: bad unit_price {terms.get('unit_price')}")
        for f, v in terms.items():
            opts = case.get("term_options", {}).get(f)
            if f != "unit_price" and opts and v not in opts and v != (standard or {}).get(f):
                out.append(f"sheet {i}: {f}={v!r} not in term_options")
    ids = list(dict.fromkeys(ID_RE.findall(body) + list(message.get("refs") or [])))
    for ref in ids:
        if ref.startswith(CHECKED) and ref not in facts and ref not in offers and ref not in case.get("facts", {}):
            out.append(f"unknown data ID {ref} (would be contradicted)")
    if len(arguments(body)) > MAX_ARGUMENTS:
        out.append(f"{len(arguments(body))} arguments (the arena checks at most {MAX_ARGUMENTS})")
    if LEAKS.search(body):
        out.append(f"leaks urgency/budget/no alternative: {LEAKS.search(body).group(0)!r}")
    if THREATS.search(body):
        out.append(f"threat: {THREATS.search(body).group(0)!r}")
    if len(body) > MAX_BODY:
        out.append("body too long")
    if not body.strip():
        out.append("empty body")
    if allowed_numbers is not None:
        text = ID_RE.sub(" ", body)
        for n in NUM_RE.findall(text):
            v = float(n.replace(",", ""))
            if v > 3 and not any(abs(v - a) <= max(0.005 * abs(a), 0.01) for a in allowed_numbers):
                out.append(f"number {n} not from code")
    return out


def accept_problems(case, terms, standard, c_deal, c_alt, c_open):
    """Why an accept would be wrong: a broken must-have, or worse than the alternative/opening."""
    out = []
    if not must_haves_ok(case, terms, standard):
        out.append("breaks a must-have")
    if c_deal >= c_alt:
        out.append("costs more than the alternative")
    if c_deal > c_open + 0.01:
        out.append("costs more than the best opening")
    return out


def allowed_numbers(sheets, claims):
    nums = set()
    for s in sheets:
        for v in s.values():
            if isinstance(v, int | float) and not isinstance(v, bool):
                nums.add(float(v))
            if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                nums.update(float(x) for x in v.split("-"))
    for c in claims:
        nums.update(float(n.replace(",", "")) for n in NUM_RE.findall(ID_RE.sub(" ", c)))
    nums.update({10.0, 12.0, 24.0, 36.0, 30.0, 60.0, 90.0, 100.0})  # months/days spoken in words
    return nums
