"""Case-specific structured outputs for the two Astra roles."""


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def enum_values(values):
    # Object enums are represented as strict objects whose scalar fields are enums.
    # Python subsequently validates the exact allowed combination, not just each field.
    variants, scalars = [], {}
    for value in values:
        if isinstance(value, dict):
            variants.append(obj({k: enum_values([v]) for k, v in value.items()}))
        else:
            kind = "null" if value is None else "boolean" if isinstance(value, bool) else (
                "number" if isinstance(value, (int, float)) else "string"
            )
            scalars.setdefault(kind, []).append(value)
    variants.extend({"type": kind, "enum": list(dict.fromkeys(items))} for kind, items in scalars.items())
    return variants[0] if len(variants) == 1 else {"anyOf": variants}


def decision_schema(case, review=False):
    text = {"type": "string"}
    fields = {}
    predicates = []
    for field in case.get("negotiable", []):
        options = case.get("term_options", {}).get(field)
        fields[field] = enum_values(options) if options else {"type": "number"}
        if field != "unit_price" and options:
            values = options + (["present"] if field == "index_clause" else [])
            predicates.append(obj({"field": {"type": "string", "enum": [field]}, "value": enum_values(values)}))
    predicate = {"anyOf": predicates} if predicates else obj({"field": text, "value": text})
    condition = obj({
        "source_id": text, "quote": text,
        "when": {"type": "array", "items": predicate},
        "requires": {"type": "array", "items": predicate},
    })
    properties = {
        "conditions": {"type": "array", "items": condition},
        "alternative_terms": {"type": "array", "items": obj(fields)},
        "quote_requests": {"type": "array", "items": obj({
            "kind": {"type": "string", "enum": ["index_rebase"]}, "source_id": text, "quote": text,
        })},
    }
    if review:
        properties["issues"] = {"type": "array", "items": obj({"source_id": text, "quote": text, "explanation": text})}
    else:
        properties.update({
            "interpretations": {"type": "array", "items": obj({"claim": text, "source_id": text, "quote": text})},
            "signals": {"type": "array", "items": obj({"kind": text, "source_id": text, "quote": text})},
            "ambiguities": {"type": "array", "items": text},
            "intro": text, "question": text,
        })
    return obj(properties)


def decode_conditions(output):
    """Convert strict predicate arrays to the internal equality maps."""
    for condition in output.get("conditions", []):
        for key in ("when", "requires"):
            values = condition.get(key)
            if isinstance(values, list):
                if len({v["field"] for v in values}) != len(values):
                    raise ValueError("duplicate condition predicate")
                condition[key] = {v["field"]: v["value"] for v in values}
    return output


def final_schema(board):
    def ids(values, maximum):
        return {"type": "array", "items": enum_values(list(values) or [""]), "maxItems": maximum}

    return obj({
        "action_id": enum_values(list(board["actions"])),
        "package_ids": ids(board["packages"], 3),
        "question_id": enum_values([""] + list(board["questions"])),
        "evidence_ids": ids(board["evidence"], 3),
        "tone": enum_values(["warm", "cooperative", "firm"]),
        "rationale": {"type": "string"},
        "reply_text": {"type": "string"},
        "plan": obj({
            "expected_response": enum_values([
                "accepted_proposal", "counteroffer", "unchanged_offer", "information_only", "walkout", "closed"
            ]),
            "expected_price_low": {"type": ["number", "null"]},
            "expected_price_high": {"type": ["number", "null"]},
            "basis_source_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            **{k: {"type": "string"} for k in ("basis", "if_counteroffer", "if_unchanged", "if_accepted",
                                               "if_walkout", "why_not_alternative", "revision_from_previous")},
            "rejected_alternative_id": enum_values([""] + list(board["actions"]) + list(board["packages"])),
        }),
        "continuation_review": obj({
            "target_package_id": enum_values([""] + list(board["packages"])),
            "walkout_probability_low": {"type": "number", "minimum": 0, "maximum": 1},
            "walkout_probability_high": {"type": "number", "minimum": 0, "maximum": 1},
            "risk_reason": {"type": "string"},
            "information_needed": {"type": "string"},
            "stop_condition": {"type": "string"},
        }),
    })
