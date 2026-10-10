"""A simulated supplier with hidden economics - our local opponent for tuning.

Hard limits, in code, like the arena's suppliers: it never goes below its floor (full cost and a
minimum margin on the cash it gets, `supplier_value` with its own interest rate), moves at most
`approval_step` of its opening per reply without the boss, and gives nothing without a move from
the buyer. Inside them its traits decide: toughness (share of the gap it closes), patience
(lowballs and wrong data use it up), how far true data moves it, when it sends a final offer.

With `llm` set, a model plays the person at the desk: it reads the buyer's e-mail and picks a
move inside the band code allows, and writes the reply and its reasons. Without it, the traits
alone decide - fast enough for thousands of games.
"""

import json
import math
import random
import re
from dataclasses import dataclass, field

from arena_kit.cost import closing_terms, supplier_value, total_cost

from . import levers

ID_RE = re.compile(r"\b(?:idx|quote|offer|sc|qn|po|cost|fc|news|doc|ctr):[\w.:@#/-]*\w")


@dataclass
class Traits:
    full_cost: float
    min_margin: float  # floor: margin on cash it never goes below
    rate: float  # what money now is worth to it per year
    toughness: float  # share of the gap to the buyer it closes per real move (0.1 hard - 0.6 soft)
    approval_step: float  # max price move per reply as a share of the opening, without the boss
    patience: int
    data_weight: float  # how much a verified, relevant argument moves it (share of its gap)
    final_round: int
    lowball: float  # an offer this far below its floor value counts as an insult
    persona: str = ""  # who sits at the desk (for the LLM)


def random_traits(rng, opening_value, should_cost=None, cash_short=None, persona=""):
    """Traits around the data: full cost near the should-cost (5-15 % error) or below the opening."""
    if should_cost:
        full = should_cost * rng.uniform(0.88, 1.10)
    else:
        full = opening_value / (1 + rng.uniform(0.06, 0.25))
    min_margin = rng.uniform(0.0, 0.10)
    floor_v = full / (1 - min_margin)
    if floor_v >= opening_value * 0.985:  # an opening below its own floor: lower the floor
        floor_v = opening_value * rng.uniform(0.90, 0.98)
        min_margin = max(-0.05, 1 - full / floor_v)
        full = floor_v * (1 - min_margin)  # a supplier quotes above its own floor
    cash = rng.random() < 0.3 if cash_short is None else cash_short
    return Traits(
        full_cost=full,
        min_margin=min_margin,
        rate=rng.uniform(0.14, 0.35) if cash else rng.uniform(0.05, 0.10),
        toughness=rng.uniform(0.12, 0.55),
        approval_step=rng.uniform(0.015, 0.05),
        patience=rng.randint(2, 5),
        data_weight=rng.uniform(0.0, 0.35),
        final_round=rng.randint(4, 8),
        lowball=rng.uniform(0.05, 0.15),
        persona=persona,
    )


LLM_SYSTEM = """You play the sales person of an industrial supplier in a negotiation by e-mail
with a buyer. You decide like that person would, inside hard limits set by your company.

Reply with ONE JSON object and nothing else:
{"move": "counter" | "agree" | "final_offer" | "walk_away",
 "price_position": 0.0-1.0,   (counter/final_offer: 0 = your lowest allowed price, 1 = keep your current price)
 "patience_delta": -2..1,     (how this e-mail affects your goodwill: rude, lowball or false data -> negative)
 "body": "your reply e-mail, at most 90 words, no placeholders",
 "reasons": ["why, in your own words, 1-3 short items"]}

Rules: you may only "agree" if the buyer's best package is allowed (ALLOWED says so). Give little
without a move from the buyer. True data may disarm you, or meet "that's not our reality" when
something else weighs more for you. Threats and pressure make you tougher; respect and real trades
(faster payment if cash is tight, volume, longer contract) make you softer."""


@dataclass
class SimSupplier:
    case: dict
    sid: str
    traits: Traits
    standard: dict
    opening: dict  # opening term sheet (negotiable fields)
    llm: object = None
    rng: random.Random = field(default_factory=random.Random)

    def __post_init__(self):
        self.key = self.sid.split(":")[1]
        self.me = {
            "standard": self.standard,
            "full_cost": self.traits.full_cost,
            "interest_rate": self.traits.rate,
            "usual_rate": 0.08,
        }
        self.floor_v = self.traits.full_cost / (1 - self.traits.min_margin)
        self.open_v = self.value(self.opening)
        self.ask_v = self.open_v
        self.stated = dict(self.opening)
        self.round, self.status, self.patience = 0, "open", self.traits.patience
        self.best_buyer_v, self.offer_n = -math.inf, 0
        self.trace = []

    # -- economics ---------------------------------------------------------------------------------
    def value(self, terms):
        return supplier_value(self.case, terms, self.me)

    def price_for_value(self, package, v):
        """The unit price that makes this package worth `v` to it (value is linear in price)."""
        v0 = self.value({**package, "unit_price": 0.0})
        v1 = self.value({**package, "unit_price": 1.0})
        return (v - v0) / (v1 - v0)

    def best_c(self):
        """The cheapest C for the buyer it would ever accept (true economics, every lever)."""
        c, _, _ = levers.best_deal(
            self.case,
            self.standard,
            self.me,
            self.traits.min_margin,
            price_cap=self.opening.get("unit_price"),
        )
        return c

    def true_cost(self, terms):
        return total_cost(self.case, terms, self.standard, self.me)

    # -- documents ---------------------------------------------------------------------------------
    def quote_text(self, stated):
        from arena_kit.sim import NAMES, _fmt

        lines = [f"Quotation {self.sid}", "Offered terms"]
        lines += [f"{NAMES[k]} {_fmt(v)}" for k, v in stated.items() if k in NAMES]
        lines.append("Our standard terms")
        lines += [f"{NAMES[k]} {_fmt(v)}" for k, v in self.standard.items() if k in NAMES]
        return "\n".join(lines)

    def mail(self, status, stated, body, quote=False):
        self.offer_n += 1
        self.status, self.stated = status, dict(stated)
        sheet_id = f"offer:{self.key}-{self.offer_n}"
        return {
            "from": f"sales@{self.key}",
            "status": status,
            "body": body,
            "term_sheets": [] if status == "walked_away" else [{"term_sheet_id": sheet_id, "terms": dict(stated)}],
            "claim_results": [],
            "attachments": [{"name": "quote.pdf", "text": self.quote_text(stated)}] if quote else [],
        }

    def opening_mail(self):
        return self.mail("open", self.opening, "Please find our quotation attached.", quote=True)

    # -- a reply -----------------------------------------------------------------------------------
    def check_claims(self, msg, facts, used):
        refs = list(dict.fromkeys((msg.get("refs") or []) + ID_RE.findall(msg.get("body") or "")))
        results, verified = [], 0
        for i, ref in enumerate(refs[:3]):
            if ref not in facts:
                results.append({"index": i, "result": "contradicted"})
                continue
            fact = facts[ref]
            mine = fact.get("supplier") in (None, self.sid) or ref.startswith(("idx:", "quote:", "cost:"))
            if ref in used:
                res = "duplicate"
            elif not mine:
                res = "irrelevant"
            else:
                res = "verified"
                verified += 1
            used.add(ref)
            results.append({"index": i, "result": res})
        return results, verified

    def reply(self, msg, facts, used):
        self.round += 1
        t = self.traits
        results, verified = self.check_claims(msg, facts, used)
        contradicted = sum(r["result"] == "contradicted" for r in results)
        sheets = [ts["terms"] for ts in msg.get("term_sheets") or []]
        if self.status == "final_offer" and sheets:
            best = max(sheets, key=self.value)
            if self.value(best) >= self.ask_v - 1e-9:
                return self._out("agreed", best, "We agree to your terms.", results, ["meets our final offer"], True)
            if self.rng.random() < 0.6 or self.patience <= 1:
                return self._out("walked_away", self.stated, "We cannot go further and end here.", results,
                                 ["pushed past the final offer"])
            self.patience -= 1
            return self._out("final_offer", self.stated, "Our final offer stands.", results, ["final offer stands"], True)

        best = max(sheets, key=self.value) if sheets else None
        best_v = self.value(best) if best else -math.inf
        moved = best_v > self.best_buyer_v + 1e-6
        self.best_buyer_v = max(self.best_buyer_v, best_v)
        reasons = []
        # patience: lowballs and wrong data
        if best is not None and best_v < self.floor_v * (1 - t.lowball):
            self.patience -= 1
            reasons.append("offer far below what we can do")
        if contradicted:
            self.patience -= contradicted
            reasons.append("their figures do not match")
        # how far it is willing to go this round
        gap = self.ask_v - max(self.floor_v, best_v if best else self.floor_v)
        step = 0.0
        if moved and gap > 0:
            step += t.toughness * gap
        if verified:
            step += t.data_weight * (self.ask_v - self.floor_v) * min(verified, 2) / 2
            reasons.append("their data is right")
        cap = t.approval_step * self.open_v * (2 if self.round >= 4 else 1)  # the boss joins later
        step = min(step, cap)
        new_ask = max(self.floor_v, self.ask_v - step)
        llm_move = None
        if self.llm:
            llm_move = self._ask_llm(msg, best, best_v, new_ask, results)
            if llm_move:
                pos = min(1.0, max(0.0, float(llm_move.get("price_position", 0.5))))
                new_ask = max(self.floor_v, new_ask + pos * (self.ask_v - new_ask))
                self.patience += max(-2, min(1, int(llm_move.get("patience_delta", 0))))
        self.ask_v = new_ask
        if best is not None and best_v >= self.ask_v - 1e-9:
            if not llm_move or llm_move.get("move") in ("agree", "counter", "final_offer"):
                return self._out("agreed", best, (llm_move or {}).get("body") or "We agree.", results,
                                 reasons + ["the offer works for us"], True)
        if self.patience <= 0 or (llm_move and llm_move.get("move") == "walk_away" and self.patience <= 1):
            if self.status == "final_offer" or self.patience < 0:
                return self._out("walked_away", self.stated, "We end the negotiation here.", results, reasons + ["patience used up"])
        package = {k: v for k, v in (best or self.stated).items() if k != "unit_price"}
        price = round(self.price_for_value(package, self.ask_v) + 0.004, 2)
        counter = {**self.stated, **package, "unit_price": price}
        near_floor = self.ask_v - self.floor_v < 0.01 * self.floor_v
        final = (
            self.round >= t.final_round
            or near_floor
            or self.patience <= 0
            or (llm_move and llm_move.get("move") == "final_offer")
        )
        body = (llm_move or {}).get("body") or ("This is our final offer." if final else "Here is our counter-offer.")
        reasons += (llm_move or {}).get("reasons") or []
        return self._out("final_offer" if final else "open", counter, body, results, reasons or ["counter"], final)

    def _out(self, status, stated, body, results, reasons, quote=False):
        m = self.mail(status, stated, body, quote)
        m["claim_results"] = results
        self.trace.append({"round": self.round, "status": status, "terms": stated, "reasons": reasons})
        return m

    def _ask_llm(self, msg, best, best_v, low_v, results):
        package = {k: v for k, v in (best or self.stated).items() if k != "unit_price"}
        low_p = self.price_for_value(package, low_v)
        cur_p = self.price_for_value(package, self.ask_v)
        user = {
            "you": self.traits.persona or "a mid-sized German industrial supplier",
            "cash_is_tight": self.traits.rate > 0.12,
            "round": self.round,
            "your_current_price_for_their_package": round(cur_p, 2),
            "lowest_price_allowed_now": round(low_p, 2),
            "ALLOWED_to_agree_to_their_best_package": bool(best is not None and best_v >= low_v),
            "their_term_sheets": [ts["terms"] for ts in msg.get("term_sheets") or []],
            "data_checks_of_their_arguments": results,
            "their_email": (msg.get("body") or "")[:2000],
            "your_goodwill_left": self.patience,
        }
        try:
            out = self.llm(LLM_SYSTEM, json.dumps(user, ensure_ascii=False))
            return json.loads(re.search(r"\{.*\}", out, re.S).group(0))
        except Exception:
            return None

    def closing(self, sheet_terms):
        return closing_terms(self.case, sheet_terms, self.standard)
