"""Lossless compact wire representation: no offer, cost or evidence pruning.

Repeated record keys are encoded once as columns. Exact repeated long strings are
stored once as references. The full ordinary JSON is retained in the audit log.
"""

import hashlib
import json
from collections import Counter

FORMAT = (
    "This JSON uses lossless tables. A {$columns:[...],$rows:[[...],...]} object is a list of "
    "records: zip each row with its columns. {$absent:true} cells mean a missing field, not null. "
    "A {$columns:[...],$entries:{id:[...]}} object "
    "is a dictionary of records keyed by the ORIGINAL id. Nested tables work the same way. "
    "{$text:id} means the exact string in text_dictionary[id]. {$object:[[key,value],...]} is a literal object. "
    "No records or fields were pruned. "
    "Use original action/package/evidence IDs in your answer, never table indices or text references."
)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def compact_context(data):
    strings = Counter()

    def count(value):
        if isinstance(value, str) and len(value) >= 160:
            strings[value] += 1
        elif isinstance(value, dict):
            for item in value.values():
                count(item)
        elif isinstance(value, list):
            for item in value:
                count(item)

    count(data)
    ids = {value: f"text:{i}" for i, (value, n) in enumerate(strings.items()) if n > 1}

    def table(records):
        if len(records) < 3 or not all(isinstance(r, dict) and r for r in records):
            return None
        keys = list(dict.fromkeys(k for r in records for k in r))
        # Sparse records retain the distinction between absent and explicit null.
        if len(keys) > 2 * max(len(r) for r in records):
            return None
        return keys, [[pack(r[k]) if k in r else {"$absent": True} for k in keys] for r in records]

    def pack(value):
        if isinstance(value, str):
            return {"$text": ids[value]} if value in ids else value
        if isinstance(value, list):
            packed = table(value)
            if packed:
                keys, rows = packed
                return {"$columns": keys, "$rows": rows}
            return [pack(v) for v in value]
        if isinstance(value, dict):
            if any(k in value for k in ("$text", "$columns", "$rows", "$entries", "$absent", "$object")):
                return {"$object": [[k, pack(v)] for k, v in value.items()]}
            packed = table(list(value.values()))
            if packed:
                keys, rows = packed
                return {"$columns": keys, "$entries": dict(zip(value, rows, strict=True))}
            return {k: pack(v) for k, v in value.items()}
        return value

    raw = dumps(data)
    packed = {"encoding": FORMAT, "text_dictionary": {i: v for v, i in ids.items()}, "data": pack(data)}
    # Always verify losslessness before sending a transformed prompt. This is a
    # production invariant, not an approximation of omitted context.
    if expand_context(packed) != data:
        raise ValueError("compact context did not preserve all input records")
    encoded = dumps(packed)
    # Small prompts need no wrapper. This choice does not change semantic content.
    text = encoded if len(encoded) < len(raw) else raw
    return text, {"raw_input_chars": len(raw), "input_chars": len(text),
                  "encoding": "lossless_tables_v1" if text is encoded else "plain_json",
                  "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                  "raw_input_sha256": hashlib.sha256(raw.encode()).hexdigest()}


def expand_context(envelope):
    """Restore compact input for audits and enforce the production invariant."""
    dictionary = envelope["text_dictionary"]

    def expand(value):
        if isinstance(value, list):
            return [expand(v) for v in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {"$text"}:
            return dictionary[value["$text"]]
        if set(value) == {"$object"}:
            return {k: expand(v) for k, v in value["$object"]}
        if "$columns" in value:
            def row(values):
                return {k: expand(v) for k, v in zip(value["$columns"], values, strict=True)
                        if v != {"$absent": True}}
            if "$entries" in value:
                return {k: row(v) for k, v in value["$entries"].items()}
            return [row(v) for v in value["$rows"]]
        return {k: expand(v) for k, v in value.items()}

    return expand(envelope["data"])
