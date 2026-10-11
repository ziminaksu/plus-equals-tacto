#!/usr/bin/env bash
# Play ONE practice case with gpt-5-mini on Azure (student credits; ~5 cents a session).
#   ./tools/run_azure.sh P08
# Needs AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
case_id="${1:?usage: ./tools/run_azure.sh P08}"
source tools/env_azure.sh
run_id="azure-$case_id-$(date +%H%M%S)"
# caffeinate: an idle-sleeping Mac froze a session until it expired (free Gemini P05, score 0)
set +e
caffeinate -i uv run tacto-bayes --run-id "$run_id" --max-sessions 1 --cases "case:$case_id" --primary astra --reviewer astra
run_status=$?
set -e
uv run python - "$run_id" <<'PY'
import json, sqlite3, sys
c = sqlite3.connect("hollerau/logs/analytical.sqlite")
rows = [json.loads(r[0]) for r in c.execute(
    "SELECT payload FROM events WHERE run_id=? AND kind='decision'", (sys.argv[1],))]
fallback = sum("fallback" in str(p.get("reason", "")) for p in rows)
from collections import Counter
print("final calls:", dict(Counter(c.get("model") for p in rows for c in p.get("llm_calls", [])
                                    if c.get("role") == "final_decision" and c.get("status") == "ok")))
print(f"decisions by the model: {len(rows) - fallback} of {len(rows)} (the rest: offline fallback)")
PY

exit "$run_status"
