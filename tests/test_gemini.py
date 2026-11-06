"""Gemini client: response parsing (thought parts, thinking tokens, finish states), HTTP error classification, and
the fallback chain's behaviour. Offline: an injected transport stands in for Google."""
import json

import pytest

from marketlab import gemini


def ok(text="answer", finish="STOP", thoughts=0, model="m"):
    usage = {"promptTokenCount": 100, "candidatesTokenCount": 40}
    if thoughts:
        usage["thoughtsTokenCount"] = thoughts
    return 200, {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
                 "usageMetadata": usage, "modelVersion": model}


def test_parse_excludes_thoughts_counts_thinking_as_output_and_maps_finish_states():
    body = {"candidates": [{"content": {"parts": [{"text": "think", "thought": True}, {"text": "A", "thoughtSignature": "x"},
                                                  {"text": "B"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "thoughtsTokenCount": 7}}
    out = gemini.parse(body, "gemini-3.8-flash")
    assert out["text"] == "AB" and out["state"] == "DONE"
    assert out["input_tokens"] == 10 and out["output_tokens"] == 12 and out["thinking_tokens"] == 7
    assert gemini.parse(ok(finish="MAX_TOKENS")[1], "m")["state"] == "TRUNCATED"
    assert gemini.parse(ok(finish="SAFETY")[1], "m")["state"] == "REFUSED"
    assert gemini.parse(ok(text="  ", finish="STOP")[1], "m")["state"] == "REFUSED"  # empty answer is not DONE
    blocked = gemini.parse({"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {"promptTokenCount": 3}}, "m")
    assert blocked["state"] == "REFUSED" and blocked["finish_reason"] == "PROMPT_BLOCKED:SAFETY"
    with pytest.raises(gemini.GeminiError):
        gemini.parse([], "m")


@pytest.mark.parametrize("code, err, label, billed", [
    (503, {"status": "UNAVAILABLE"}, "UNAVAILABLE", False),
    (429, {"status": "RESOURCE_EXHAUSTED"}, "RATE_LIMITED", False),
    (400, {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}, "AUTH", False),
    (401, {"status": "UNAUTHENTICATED"}, "AUTH", False),
    (403, {"status": "PERMISSION_DENIED"}, "PERMISSION_DENIED", False),
    (404, {"status": "NOT_FOUND"}, "MODEL_NOT_FOUND", False),
    (400, {"status": "FAILED_PRECONDITION"}, "FAILED_PRECONDITION", False),
    (400, {"status": "INVALID_ARGUMENT"}, "BAD_REQUEST", False),
    (500, {"status": "INTERNAL"}, "SERVER_ERROR", True),
    (504, {"status": "DEADLINE_EXCEEDED"}, "SERVER_ERROR", True),
])
def test_http_errors_map_to_fixed_labels_and_billing(code, err, label, billed):
    e = gemini.classify_http(code, {"error": err | {"message": "msg with KEY123 inside"}}, key="KEY123")
    assert (e.label, e.billed) == (label, billed) and "KEY123" not in e.message and e.hint


def test_retry_delay_is_read_from_google_retry_info():
    e = gemini.classify_http(429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}]}})
    assert e.retry_after == 7.0


def test_request_shape_header_auth_and_thinking_level_only_where_documented():
    sent = []

    def transport(method, url, headers, body):
        sent.append((url, headers, json.loads(body)))
        return ok()
    c = gemini.Client("AQ.key-value", transport=transport)
    c.generate(model="gemini-3.8-flash", system="S", user="U", max_tokens=6000, effort="medium")
    c.generate(model="gemini-3.5-flash-lite", system="S", user="U", max_tokens=6000, effort="medium")
    (u1, h1, b1), (u2, _, b2) = sent
    assert u1.endswith("/v1beta/models/gemini-3.8-flash:generateContent") and h1["x-goog-api-key"] == "AQ.key-value"
    assert "key=" not in u1  # the key travels in the header, never the URL (URLs end up in logs)
    assert b1["systemInstruction"]["parts"][0]["text"] == "S" and b1["contents"][0]["parts"][0]["text"] == "U"
    assert b1["generationConfig"] == {"maxOutputTokens": 6000, "thinkingConfig": {"thinkingLevel": "medium"}}
    assert b2["generationConfig"] == {"maxOutputTokens": 6000}  # no undocumented thinking field on Lite


def test_fallback_chain_moves_on_when_busy_waits_once_for_a_short_quota_and_stops_on_auth():
    waits, calls = [], []

    def busy_then_quota_then_ok(method, url, headers, body):
        model = url.split("/models/")[1].split(":")[0]
        calls.append(model)
        if model == "gemini-3.8-flash":
            return 503, {"error": {"status": "UNAVAILABLE"}}
        if model == "gemini-3.5-flash-lite" and calls.count(model) == 1:
            return 429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3s"}]}}
        return ok(model=model)
    c = gemini.Client("k" * 20, transport=busy_then_quota_then_ok, sleep=waits.append)
    out, attempts = c.generate_with_fallback(chain=gemini.chain_for("gemini-3.8-flash", True), system="S", user="U",
                                             max_tokens=100)
    assert out["model"] == "gemini-3.5-flash-lite" and waits == [3.0]
    assert [a["result"] for a in attempts] == ["UNAVAILABLE", "RATE_LIMITED", "DONE"]

    calls.clear()
    auth = lambda m, u, h, b: (calls.append(u) or (401, {"error": {"status": "UNAUTHENTICATED"}}))  # noqa: E731
    with pytest.raises(gemini.GeminiError) as e:
        gemini.Client("k" * 20, transport=auth).generate_with_fallback(chain=["gemini-3.8-flash", "gemini-3.5-flash-lite"],
                                                                      system="S", user="U", max_tokens=100)
    assert e.value.label == "AUTH" and len(calls) == 1  # another model would fail the same way


def test_long_quota_wait_moves_to_the_next_model_instead_of_blocking():
    waits = []

    def quota(method, url, headers, body):
        if "3.8" in url:
            return 429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3600s"}]}}
        return ok(model="lite")
    out, _ = gemini.Client("k" * 20, transport=quota, sleep=waits.append).generate_with_fallback(
        chain=gemini.chain_for("gemini-3.8-flash", True), system="S", user="U", max_tokens=100)
    assert waits == [] and out["text"] == "answer"


def test_chain_without_fallback_is_only_the_chosen_model_and_unknown_models_use_the_default():
    assert gemini.chain_for("gemini-3.5-flash-lite", False) == ["gemini-3.5-flash-lite"]
    assert gemini.chain_for("not-a-model", True)[0] == gemini.DEFAULT_MODEL
