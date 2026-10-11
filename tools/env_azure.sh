# Source me: the decision model setup shared by practice runs and the Live Final.
#   source tools/env_azure.sh
# Primary: gpt-5-mini on Azure (student credits). Backups on 429/503/timeouts: Hugging Face, then Gemini.
set -a; source .env; set +a
export OPENAI_API_KEY="$AZURE_OPENAI_KEY"
export ASTRA_BASE_URL="${AZURE_OPENAI_ENDPOINT%/}/openai/v1"
export ASTRA_EFFORT="${ASTRA_EFFORT:-low}"   # 'minimal' broke the answer shape in 5 of 6 boards
export ASTRA_SAFE=1                          # normalize slips; a failed answer becomes a move from the board
backups=""
if [ -n "${HF_TOKEN:-}" ] && [ "${ASTRA_HF:-1}" != "0" ]; then
  backups="$backups,hf:openai/gpt-oss-120b:cerebras,hf:deepseek-ai/DeepSeek-V4.1-Flash"
fi
[ -n "${GEMINI_API_KEY:-}" ] && backups="$backups,gm:gemini-3.5-flash-lite,gm:gemini-3.1-flash-lite"
export ASTRA_MODEL="${ASTRA_MODEL_OVERRIDE:-${AZURE_OPENAI_DEPLOYMENT}${backups}}"
