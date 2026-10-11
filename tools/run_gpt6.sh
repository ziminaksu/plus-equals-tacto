#!/usr/bin/env bash
# Play ONE practice case with gpt-6-astra on the OpenAI Responses API.
#   ./tools/run_gpt6.sh P08
# Needs OPENAI_API_KEY (or legacy LLM_API_KEY) with credits in ignored .env.
set -euo pipefail
cd "$(dirname "$0")/.."
case_id="${1:?usage: ./tools/run_gpt6.sh P08}"
set -a; source .env; set +a
export OPENAI_API_KEY="${OPENAI_API_KEY:-${LLM_API_KEY:-}}"
: "${OPENAI_API_KEY:?Set OPENAI_API_KEY in .env}"
unset ASTRA_BASE_URL ASTRA_MODEL
# Budget mode supplies its own compact context and exact decision validation.
run_id="gpt6-$case_id-$(date +%H%M%S)"
# Reuse the SAME ledger across cases/restarts. It never resets itself.
spend_cap="${GPT6_MAX_SPEND_USD:-1}"
spend_ledger="${GPT6_SPEND_LEDGER:-hollerau/logs/gpt6-spend.sqlite}"
mkdir -p hollerau/logs
# caffeinate: an idle-sleeping Mac froze a session until it expired (free Gemini P05, score 0)
caffeinate -i uv run tacto-bayes --run-id "$run_id" --max-sessions 1 --cases "case:$case_id" --primary astra --reviewer astra \
  --max-spend-usd "$spend_cap" --spend-ledger "$spend_ledger" --openai-model "${GPT6_MODEL:-gpt-6-astra}" \
  2>&1 | tee "hollerau/logs/$run_id.log"
uv run python - "$run_id" <<'PY'
import json, sqlite3, sys
c = sqlite3.connect("hollerau/logs/analytical.sqlite")
rows = [json.loads(r[0]) for r in c.execute(
    "SELECT payload FROM events WHERE run_id=? AND kind='decision'", (sys.argv[1],))]
fallback = sum(p.get("authority") != "astra" for p in rows)
tokens = [c.get("usage", {}) for p in rows for c in p.get("llm_calls", [])]
print("tokens in/out:", sum(t.get("input_tokens", 0) for t in tokens), sum(t.get("output_tokens", 0) for t in tokens))
print(f"decisions by the model: {len(rows) - fallback} of {len(rows)} (the rest: fallback or budget closure)")
PY
