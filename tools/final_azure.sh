#!/usr/bin/env bash
# LIVE FINAL: all five waves with gpt-5-mini on Azure (backups: Hugging Face, then Gemini).
#   ./tools/final_azure.sh            # writes hollerau/logs/final-<time>.log
# Same decision setup as ./tools/run_azure.sh (tools/env_azure.sh). Keep the Mac on power and awake.
set -euo pipefail
cd "$(dirname "$0")/.."
source tools/env_azure.sh
log="hollerau/logs/final-$(date +%H%M%S).log"
echo "models: $ASTRA_MODEL"
echo "log: $log"
caffeinate -i uv run python -m hollerau.cli --verbose run --set final --brain analytical --parallel 10 2>&1 | tee "$log"
