"""Astra routing and failure behaviour without external calls or real credentials."""

import json
import time

import httpx
import pytest

from hollerau.analytical.router import ASTRA, Router

CASE = {
    "negotiable": ["unit_price", "contract_months", "index_clause"],
    "term_options": {
        "contract_months": [12, 24],
        "index_clause": [None],
    },
}
SOURCES = {"reply": "We require an index clause for a 24-month contract."}
REVIEW = {
    "issues": [{"source_id": "reply", "quote": SOURCES["reply"], "explanation": "Check the index."}],
    "conditions": [],
    "alternative_terms": [],
}


def response(obj=REVIEW, status="completed"):
    return {
        "status": status,
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(obj)}]},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 40},
    }


def test_astra_and_qwen_use_separate_hosts_keys_and_output_protocols():
    requests = []

    def handler(req):
        body = json.loads(req.content)
        requests.append((req, body))
        if req.url.host == "router.huggingface.co":
            assert req.headers["Authorization"] == "Bearer hf-test"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "interpretations": [],
                                        "signals": [],
                                        "ambiguities": [],
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        assert req.url == "https://api.openai.com/v1/responses"
        assert req.headers["Authorization"] == "Bearer openai-test"
        assert body["model"] == ASTRA and body["store"] is False
        assert body["reasoning"] == {"effort": "low"}
        assert body["max_output_tokens"] == 4096
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["strict"] is True
        assert "json" in body["input"].lower()  # Required by the live Responses JSON-mode validator.
        assert not {"temperature", "max_tokens", "chat_template_kwargs", "tools"} & body.keys()
        assert 0 < max(req.extensions["timeout"].values()) <= 12 + 1e-6
        return httpx.Response(200, json=response())

    router = Router("hf-test", httpx.MockTransport(handler), reviewer="astra", review_key="openai-test")
    router.analyse({}, [], time.monotonic() + 30)
    for _ in range(2):
        review = router.review(SOURCES, CASE, {}, time.monotonic() + 30)
    assert len(requests) == 2  # cached review costs nothing on repetition
    assert review["reviewer"] == ASTRA and review["issues"]
    assert router.calls[-1]["usage"]["output_tokens"] == 40
    assert "openai-test" not in json.dumps(router.calls)
    router.close()


@pytest.mark.parametrize("mode", ["incomplete", "refusal", "empty", "bad_quote", "timeout", "unauthorized"])
def test_astra_errors_fall_back_and_open_circuit_without_retry(mode):
    requests = []

    def handler(req):
        requests.append(req)
        if mode == "timeout":
            raise httpx.ReadTimeout("secret must not be logged")
        if mode == "unauthorized":
            return httpx.Response(401, text="secret must not be logged")
        out = response()
        if mode == "incomplete":
            out["status"] = "incomplete"
        elif mode == "refusal":
            out["output"][-1]["content"] = [{"type": "refusal", "refusal": "no"}]
        elif mode == "empty":
            out["output"] = []
        elif mode == "bad_quote":
            out = response({"issues": [{"source_id": "reply", "quote": "invented"}]})
        return httpx.Response(200, json=out)

    router = Router("hf-test", httpx.MockTransport(handler), reviewer="astra", review_key="openai-test")
    for _ in range(2):
        out = router.review(SOURCES, CASE, {}, time.monotonic() + 30)
        assert out["failed"] and out["alternative_terms"] == []
    assert router.review(SOURCES, CASE, {}, time.monotonic() + 30)["skipped"]
    assert len(requests) == 2 and router.large_failures == 0
    assert "secret must not be logged" not in json.dumps(router.calls)
    router.close()


def test_missing_openai_key_never_uses_hugging_face_key():
    def unexpected(req):
        pytest.fail("Astra must not be called without its own credentials")

    router = Router("hf-secret", httpx.MockTransport(unexpected), reviewer="astra", review_key="")
    assert router.enabled and not router.review_enabled
    assert router.review(SOURCES, CASE, {}, time.monotonic() + 30)["skipped"]
    assert not router.calls
    router.close()


def test_quota_error_is_diagnosable_without_logging_error_message_or_retrying():
    requests = []

    def handler(req):
        requests.append(req)
        return httpx.Response(
            429,
            json={
                "error": {
                    "type": "insufficient_quota",
                    "code": "insufficient_quota",
                    "param": None,
                    "message": "Sensitive account details and key openai-test",
                }
            },
        )

    router = Router("hf-test", httpx.MockTransport(handler), reviewer="astra", review_key="openai-test")
    assert router.review(SOURCES, CASE, {}, time.monotonic() + 30)["failed"]
    assert len(requests) == 1
    assert router.calls[0]["error_code"] == "insufficient_quota"
    assert "Sensitive" not in json.dumps(router.calls) and "openai-test" not in json.dumps(router.calls)
    router.close()


def test_offline_mode_disables_astra_even_with_a_key():
    router = Router("hf-test", enabled=False, reviewer="astra", review_key="openai-test")
    assert not router.enabled and not router.review_enabled
    assert router.review(SOURCES, CASE, {}, time.monotonic() + 30)["skipped"]
    router.close()


def test_astra_configuration_does_not_replace_qwen(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "hf")
    monkeypatch.setenv("ANALYTICAL_PRIMARY", "qwen")
    monkeypatch.setenv("HF_TOKEN", "hf-test")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
    monkeypatch.setenv("STRATEGIC_REVIEWER", "astra")
    router = Router()
    assert router.provider == "hf" and router.small.startswith("Qwen/")
    assert router.review_model == ASTRA and router.review_enabled
    router.close()
