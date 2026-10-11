#!/usr/bin/env bash
# Play ONE practice case with the free Gemini key (uses 1 practice session, no OpenAI credits).
#   ./tools/run_free.sh P04
# Needs GEMINI_API_KEY in .env. Prints the score and how many decisions Gemini itself made.
set -euo pipefail
cd "$(dirname "$0")/.."
case_id="${1:?usage: ./tools/run_free.sh P04}"
set -a; source .env; set +a
export OPENAI_API_KEY="$GEMINI_API_KEY"
export ASTRA_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
export ASTRA_MODEL="${ASTRA_MODEL_OVERRIDE:-gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash}"
# caffeinate: an idle-sleeping Mac froze a session until it expired (free Gemini P05, score 0)
run_id="free-$case_id-$(date +%H%M%S)"
caffeinate -i uv run tacto-bayes --run-id "$run_id" --max-sessions 1 --cases "case:$case_id" --primary astra --reviewer astra \
  2>&1 | grep -E "^(START|DONE|STOP)" || true
uv run python - "$run_id" <<'EOF'
import json, sqlite3, sys
c = sqlite3.connect("hollerau/logs/analytical.sqlite")
rows = [json.loads(r[0]) for r in c.execute(
    "SELECT payload FROM events WHERE run_id=? AND kind='decision'", (sys.argv[1],))]
fallback = sum("fallback" in str(p.get("reason", "")) for p in rows)
print(f"decisions by Gemini: {len(rows) - fallback} of {len(rows)} (the rest: offline fallback)")
EOF
