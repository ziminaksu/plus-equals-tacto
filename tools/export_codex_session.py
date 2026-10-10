"""Export real visible Codex records since a timestamp; no fabricated messages.
Original session is never modified. Drop internal reasoning, system/developer context,
image pixels and unrelated earlier turns. Preserve source record indices and hashes.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--secrets-env", type=Path)
    args = ap.parse_args()
    secrets = []
    if args.secrets_env:
        for line in args.secrets_env.read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if any(s in key for s in ("KEY", "TOKEN", "SECRET")) and value.strip():
                    secrets.append(value.strip().strip("\"'"))
    rows = []
    source_id = None
    for i, line in enumerate(args.source.open()):
        record = json.loads(line)
        p = record.get("payload", {})
        if record.get("type") == "session_meta":
            source_id = p.get("id")
        if record.get("timestamp", "") < args.since or record.get("type") != "response_item":
            continue
        kind = p.get("type")
        role = p.get("role")
        if kind == "message" and role in ("user", "assistant") and p.get("channel") != "analysis":
            text = "\n".join(
                c.get("text", "[image omitted]")
                for c in p.get("content", [])
                if c.get("type") in ("input_text", "output_text", "input_image")
            )
            out = {"type": role, "message": {"role": role, "content": text}}
        elif kind in ("function_call", "custom_tool_call"):
            out = {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": p.get("call_id"),
                            "name": p.get("name"),
                            "input": {"original_arguments": p.get("arguments", p.get("input"))},
                        }
                    ],
                },
            }
        elif kind in ("function_call_output", "custom_tool_call_output"):
            out = {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": p.get("call_id"), "content": p.get("output")}],
                },
            }
        else:
            continue
        out.update(
            timestamp=record.get("timestamp"),
            source_session_id=source_id,
            import_scope_id=args.output.stem,
            source_record=i,
            source_sha256=hashlib.sha256(line.encode()).hexdigest(),
        )
        raw = json.dumps(out, ensure_ascii=False)
        raw = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[image pixels omitted]", raw)
        for secret in secrets:
            raw = raw.replace(secret, "[REDACTED_CREDENTIAL]")
        rows.append(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(rows) + "\n")
    manifest = {
        "source_session_id": source_id,
        "import_scope_id": args.output.stem,
        "scope_start": args.since,
        "records_exported": len(rows),
        "transformations": [
            "earlier turns omitted",
            "internal/system context omitted",
            "images omitted",
            "visible messages and tool events converted to Entire JSONL",
            "known credentials redacted",
        ],
        "export_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
