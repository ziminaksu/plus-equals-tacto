"""Astra writes the reply; fixed facts and binding terms retain exact source values."""

import json
import re

from arena_kit.cost import closing_terms

TOKEN = re.compile(r"\{\{(fixed:[a-z_]+)\}\}")
SHAREABLE = {"volume_per_year", "contract_months", "payment_days", "lead_time_days", "effective_date",
             "incoterm", "ppm_commitment", "chargeback_eur_per_complaint", "tooling_eur", "index_clause"}


def reply_facts(case):
    return {f"fixed:{key}": {"value": value, "source": f"case.fixed_terms.{key}",
                            "placeholder": "{{fixed:" + key + "}}"}
            for key, value in case.get("fixed_terms", {}).items() if key in SHAREABLE and value is not None}


def render_reply(text, facts):
    if not isinstance(text, str) or not text.strip() or len(text) > 3000:
        raise ValueError("a concise Astra-authored reply is required")
    # Numbers belong to source substitutions or the exact appended term sheets.
    prose = TOKEN.sub("", text)
    if re.search(r"\d|\{\{|\}\}", prose):
        raise ValueError("reply numbers must use verified fixed-fact placeholders or binding packages")

    def substitute(match):
        fact = facts.get(match.group(1))
        if fact is None:
            raise ValueError("unknown fixed-fact placeholder")
        value = fact["value"]
        return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)

    return TOKEN.sub(substitute, text).strip()


def describe_complete(case, terms, standard):
    # Fixed volume used to disappear because only negotiable fields were rendered.
    full = closing_terms(case, terms, standard)
    labels = {"unit_price": "EUR {} per unit", "volume_per_year": "{} units per year",
              "payment_days": "payment {} days net", "contract_months": "{} months",
              "lead_time_days": "lead time {} days", "effective_date": "effective {}",
              "incoterm": "Incoterm {}", "tooling_eur": "tooling EUR {}",
              "ppm_commitment": "quality {} ppm", "chargeback_eur_per_complaint": "EUR {} per complaint"}
    parts = [labels[k].format(v) for k, v in full.items() if k in labels and v is not None]
    clause = full.get("index_clause")
    parts.append("no index clause" if not clause else "index clause " + json.dumps(clause, ensure_ascii=False))
    return "; ".join(parts)
