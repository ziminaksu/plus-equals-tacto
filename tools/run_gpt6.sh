#!/usr/bin/env bash
# Play ONE practice case with gpt-6-astra on the OpenAI Responses API (LLM_API_KEY credits).
#   ./tools/run_gpt6.sh P08
# Needs LLM_API_KEY (OpenAI, with credits) in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
case_id="${1:?usage: ./tools/run_gpt6.sh P08}"
set -a; source .env; set +a
export OPENAI_API_KEY="$LLM_API_KEY"
unset ASTRA_BASE_URL ASTRA_MODEL
export ASTRA_SAFE=1  # normalize bookkeeping slips; an invalid answer becomes the offline move, not a lost case
export ASTRA_COMPACT=1  # a smaller board: the RFQ board hit the tokens-per-minute limit (429)
run_id="gpt6-$case_id-$(date +%H%M%S)"
# caffeinate: an idle-sleeping Mac froze a session until it expired (free Gemini P05, score 0)
caffeinate -i uv run tacto-bayes --run-id "$run_id" --max-sessions 1 --cases "case:$case_id" --primary astra --reviewer astra \
  2>&1 | grep -E "^(START|DONE|STOP)" || true
uv run python - "$run_id" <<'PY'
import json, sqlite3, sys
c = sqlite3.connect("hollerau/logs/analytical.sqlite")
rows = [json.loads(r[0]) for r in c.execute(
    "SELECT payload FROM events WHERE run_id=? AND kind='decision'", (sys.argv[1],))]
fallback = sum("fallback" in str(p.get("reason", "")) for p in rows)
tokens = [c.get("usage", {}) for p in rows for c in p.get("llm_calls", [])]
print("tokens in/out:", sum(t.get("input_tokens", 0) for t in tokens), sum(t.get("output_tokens", 0) for t in tokens))
print(f"decisions by the model: {len(rows) - fallback} of {len(rows)} (the rest: offline fallback)")
PY
