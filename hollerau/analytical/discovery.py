"""Evidence-backed requests for missing quotes, separate from binding offers."""

import re


def supports_rebase(quote):
    text = " ".join(quote.lower().split())
    if not re.search(r"index|preisgleit", text):
        return False
    if re.search(r"(?:cannot|won't|will not|not willing|not open|do not|don't)\b", text):
        return False
    return bool(re.search(
        r"open to introduc|willing to (?:offer|introduc)|"
        r"base price.{0,90}(?:recalculat|rebas|exclud)|"
        r"(?:calculat|rebas).{0,60}(?:revised |new )?base price", text,
    ))


def validate_quote_request(item, sources, fields, options):
    if set(item) != {"kind", "source_id", "quote"} or item.get("kind") != "index_rebase":
        raise ValueError("unsupported quote request")
    source, quote = item.get("source_id"), item.get("quote")
    if not isinstance(source, str) or not source.startswith("reply:"):
        raise ValueError("quote request needs supplier evidence")
    if not isinstance(quote, str) or not quote or quote not in sources.get(source, ""):
        raise ValueError("unsupported quote request evidence")
    if "index_clause" not in fields or not any((options or {}).get("index_clause", [])):
        raise ValueError("index clause not negotiable")
    if not supports_rebase(quote):
        raise ValueError("supplier has not offered an indexed pricing route")
    return item


def discover_quote_requests(sources, case):
    """Narrow deterministic fallback when an LLM omits the actionable output field."""
    replies = [(key, text) for key, text in sources.items() if key.startswith("reply:")]
    if not replies:
        return []
    key, text = replies[-1]
    item = {"kind": "index_rebase", "source_id": key, "quote": text}
    try:
        return [validate_quote_request(item, sources, case["negotiable"], case.get("term_options"))]
    except ValueError:
        return []


REBASE_QUESTION = (
    "Thank you. Please provide a complete alternative quote with a symmetrical index clause "
    "and the corresponding recalculated base unit price, excluding any raw-material increases "
    "already covered by the clause to avoid double-counting. Please state the index series, "
    "base month, material share, deadband and all remaining terms. "
    "This is a request for a priced alternative for comparison, not acceptance of indexation "
    "or of the current price. Please also confirm whether your existing unindexed offer remains available."
)
