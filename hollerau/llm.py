"""LLM access for the two LLM roles - the e-mail writer and the simulated supplier - over any
OpenAI-compatible endpoint, with a hard timeout. Qwen is the team's model; GPT is the stand-in.

.env (the first role that is set wins):
  QWEN_BASE_URL, QWEN_API_KEY, QWEN_MODEL     e.g. OpenRouter: https://openrouter.ai/api/v1,
                                              qwen/qwen3-235b-a22b-2507
  LLM_BASE_URL, LLM_API_KEY, WRITER_MODEL     fallback (OpenAI), WRITER_MODEL default gpt-6-astra
  BRAIN_MODEL                                 the negotiator that chooses every move (default gpt-6.1-sol)
  SIM_MODEL                                   the simulated supplier's model (default gpt-6.1-sol)
"""

import os

import httpx

QWEN_DEFAULT = "qwen/qwen3-235b-a22b-2507"


def endpoint(role="writer"):
    """(base_url, api_key, model, provider) for a role: Qwen if configured, else the OpenAI key."""
    if os.environ.get("QWEN_API_KEY"):
        return (
            os.environ.get("QWEN_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
            os.environ["QWEN_API_KEY"],
            os.environ.get("QWEN_MODEL", QWEN_DEFAULT),
            "qwen",
        )
    model = {
        "sim": os.environ.get("SIM_MODEL", "gpt-6.1-sol"),
        "brain": os.environ.get("BRAIN_MODEL", "gpt-6.1-sol"),
    }.get(role) or os.environ.get("WRITER_MODEL", "gpt-6-astra")
    return (
        os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        os.environ.get("LLM_API_KEY", ""),
        model,
        "openai",
    )


def make_complete(role="writer", timeout=20.0, model=None):
    """complete(system, user) -> text, raising on error or timeout (callers fall back to code)."""
    base, key, default_model, _ = endpoint(role)
    model = model or default_model
    client = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {key}"})

    def complete(system, user):
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        r = client.post(f"{base}/chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    complete.model = model
    return complete
