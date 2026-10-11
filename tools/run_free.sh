#!/usr/bin/env bash
# Play ONE practice case with the free Gemini key (uses 1 practice session, no OpenAI credits).
#   ./tools/run_free.sh P04
# Needs GEMINI_API_KEY in .env. Reports actual models and Python fallback decisions.
set -euo pipefail
cd "$(dirname "$0")/.."
case_id="${1:?usage: ./tools/run_free.sh P04}"
set -a; source .env; set +a
export OPENAI_API_KEY="$GEMINI_API_KEY"
export ASTRA_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
export ASTRA_SAFE=1  # normalize bookkeeping slips; a failed answer becomes a move from the current board
# Gemini first. The team opted in to Hugging Face as backup (HF_TOKEN in .env, 2026-10-11): its models
# answer only when Gemini is rate-limited/overloaded/too slow; set ASTRA_HF=0 to keep everything on Gemini.
chain="gemini-3.5-flash-lite,gemini-3.1-flash-lite"
if [ -n "${HF_TOKEN:-}" ] && [ "${ASTRA_HF:-1}" != "0" ]; then
  chain="$chain,hf:openai/gpt-oss-120b:cerebras,hf:deepseek-ai/DeepSeek-V4.1-Flash"
fi
export ASTRA_MODEL="${ASTRA_MODEL_OVERRIDE:-$chain,gemini-3.6-flash}"
# caffeinate: an idle-sleeping Mac froze a session until it expired (free Gemini P05, score 0)
run_id="free-$case_id-$(date +%H%M%S)"
set +e
caffeinate -i uv run tacto-bayes --run-id "$run_id" --max-sessions 1 --cases "case:$case_id" --primary astra --reviewer astra

run_status=$?
set -e
uv run python - "$run_id" <<'EOF'
import json, sqlite3, sys
c = sqlite3.connect("hollerau/logs/analytical.sqlite")
rows = [json.loads(r[0]) for r in c.execute(
    "SELECT payload FROM events WHERE run_id=? AND kind='decision'", (sys.argv[1],))]
fallback = sum("fallback" in str(p.get("reason", "")) for p in rows)
from collections import Counter
models = Counter((call.get("provider", "unknown"), call.get("model", "unknown"))
                 for row in rows for call in row.get("llm_calls", [])
                 if call.get("status") == "ok" and call.get("role") == "final_decision")
print(f"Decisions: {len(rows)}; Python fallbacks: {fallback}")
print("Successful final calls by provider/model:", dict(models))
EOF

exit "$run_status"
