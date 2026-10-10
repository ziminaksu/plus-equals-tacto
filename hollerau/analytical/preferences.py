"""Quoted, provisional supplier conditions; these never become buyer hard constraints."""

import json
import re


def validate_conditions(items, sources, negotiable, options=None):
    if not isinstance(items, list) or len(items) > 6:
        raise ValueError("invalid supplier conditions")
    valid = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid supplier condition")
        ref, quote = item.get("source_id"), item.get("quote")
        if ref not in sources or not isinstance(quote, str) or not quote or quote not in sources[ref]:
            raise ValueError("unsupported condition quote")
        when, requires = item.get("when", {}), item.get("requires", {})
        if not isinstance(when, dict) or not isinstance(requires, dict) or not requires:
            raise ValueError("invalid condition predicates")
        for predicates in (when, requires):
            for field, value in predicates.items():
                if field not in negotiable or field == "unit_price":
                    raise ValueError("condition reopens fixed or unsupported field")
                if value == "present" and field == "index_clause":
                    continue
                allowed = (options or {}).get(field)
                if not allowed or value not in allowed:
                    raise ValueError("condition value is not permitted")
        valid.append({"source_id": ref, "quote": quote, "when": when, "requires": requires})
    return valid


def matches(terms, predicates):
    return all(
        bool(terms.get(k)) if k == "index_clause" and v == "present" else terms.get(k) == v
        for k, v in predicates.items()
    )


def violated(terms, condition):
    return matches(terms, condition["when"]) and not matches(terms, condition["requires"])


def extract_explicit_conditions(sources, case, current):
    """Small offline fallback for explicit index requirements, including quoted durations.

    Unrecognised wording is left to the source-checked LLM. No keyword-only inference
    from mentions of capacity, partnership or liquidity is made here.
    """
    if not {"index_clause", "contract_months"} <= set(case["negotiable"]):
        return []
    conditions = []
    for ref, text in sources.items():
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            lower = sentence.lower()
            explicit = re.search(r"must (?:include|insist)|require|provided|cannot (?:offer )?fix", lower)
            if not explicit or not re.search(r"index|fixed price|fix prices", lower):
                continue
            if re.search(r"(?:not|never|no longer) require|do not need|without (?:an? |the )?index", lower):
                continue
            months = [int(n) for n in re.findall(r"\b(\d+)[ -]month", lower)]
            years = re.findall(r"\b(\d+|one|two|three)[ -]year", lower)
            months += [12 * ({"one": 1, "two": 2, "three": 3}.get(y) or int(y)) for y in years]
            if not months and any(w in lower for w in ("this period", "this term", "this length", "this duration")):
                months = [current.get("contract_months")]
            for duration in months:
                if duration in case.get("term_options", {}).get("contract_months", []):
                    conditions.append(
                        {
                            "source_id": ref,
                            "quote": sentence,
                            "when": {"contract_months": duration},
                            "requires": {"index_clause": "present"},
                        }
                    )
    # Multiple snippets can describe the same condition; preserve only one evidence item.
    return list({json.dumps([c["when"], c["requires"]], sort_keys=True): c for c in conditions}.values())[:6]
