#!/usr/bin/env bash
# Play ONE practice case with an Azure OpenAI deployment (Azure for Students credits).
#   ./tools/run_azure.sh P04
# Needs in .env: AZURE_OPENAI_ENDPOINT (https://<name>.openai.azure.com), AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT.
set -euo pipefail
cd "$(dirname "$0")/.."
case_id="${1:?usage: ./tools/run_azure.sh P04}"
set -a; source .env; set +a
export OPENAI_API_KEY="$AZURE_OPENAI_KEY"
export ASTRA_BASE_URL="${AZURE_OPENAI_ENDPOINT%/}/openai/v1"
export ASTRA_MODEL="$AZURE_OPENAI_DEPLOYMENT"
run_id="azure-$case_id-$(date +%H%M%S)"
uv run tacto-bayes --run-id "$run_id" --max-sessions 1 --cases "case:$case_id" --primary astra --reviewer astra \
  2>&1 | grep -E "^(START|DONE|STOP)" || true
uv run python - "$run_id" <<'PY'
import json, sqlite3, sys
c = sqlite3.connect("hollerau/logs/analytical.sqlite")
rows = [json.loads(r[0]) for r in c.execute(
    "SELECT payload FROM events WHERE run_id=? AND kind='decision'", (sys.argv[1],))]
fallback = sum("fallback" in str(p.get("reason", "")) for p in rows)
print(f"decisions by the Azure model: {len(rows) - fallback} of {len(rows)} (the rest: offline fallback)")
PY
