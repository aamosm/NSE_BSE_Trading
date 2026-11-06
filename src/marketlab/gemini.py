"""Google Gemini (Developer API, REST ``generateContent``) for the optional per-stock explainer. Stdlib only.

Verified 2026-11-06 against Google's pages and with the owner's key:
  * auth: header ``x-goog-api-key``. Keys created in AI Studio after 28 May 2026 are "auth keys" starting ``AQ.``;
    they work on this endpoint exactly like the older ``AIza...`` keys (the format is not checked here beyond
    "no whitespace, plausible length": Google may change it again);
  * request: ``systemInstruction``, ``contents``, ``generationConfig.maxOutputTokens`` (thinking tokens count
    against it) and, for the models that document it, ``generationConfig.thinkingConfig.thinkingLevel``;
  * response: answer text in ``candidates[0].content.parts[*].text`` (parts may also carry a ``thoughtSignature``;
    any part marked ``thought`` is reasoning, never answer text); ``finishReason``; ``usageMetadata`` with
    ``promptTokenCount``, ``candidatesTokenCount`` and, when the model thought, ``thoughtsTokenCount`` (billed as
    output);
  * free tier: the flagship Flash model answers HTTP 503 UNAVAILABLE ("high demand") to free-tier projects for long
    stretches, while Flash-Lite answers. Hence the fallback chain: the chosen model, then the Lite models.

Errors carry a fixed label, whether the call could have been billed, and a plain-English hint; provider text is
never echoed beyond Google's own short ``message`` with the key scrubbed out.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELS = {
    "gemini-3.8-flash": {"label": "Gemini 3.8 Flash (most capable; often busy on the free tier, falls back to Lite)",
                         "thinking_levels": ("low", "medium", "high")},
    "gemini-3.6-flash": {"label": "Gemini 3.6 Flash", "thinking_levels": ("minimal", "low", "medium", "high")},
    "gemini-3.5-flash-lite": {"label": "Gemini 3.5 Flash-Lite (fast, reliable on the free tier)", "thinking_levels": ()},
    "gemini-3.1-flash-lite": {"label": "Gemini 3.1 Flash-Lite (cheapest)", "thinking_levels": ()},
}
DEFAULT_MODEL = "gemini-3.8-flash"
FALLBACK_CHAIN = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
MAX_RESPONSE = 8 * 1024 * 1024
MAX_RETRY_WAIT = 20.0  # seconds; a longer quota wait moves to the next model instead of blocking the ask

REFUSAL_FINISH = ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY", "LANGUAGE")
HINTS = {
    "UNAVAILABLE": "Google says the model is busy (HTTP 503 'high demand'). Free-tier projects are served last; "
                   "the Lite models usually still answer. Try again in a minute.",
    "RATE_LIMITED": "Quota reached (HTTP 429 RESOURCE_EXHAUSTED). Free-tier limits are per project per minute and "
                    "per day; AI Studio shows your current limits.",
    "AUTH": "Google rejected the key. Create a new key in AI Studio and set it in Controls & AI.",
    "PERMISSION_DENIED": "The key is valid but not allowed to call this API or model (key restrictions, a disabled "
                         "API, or a region the free tier does not serve).",
    "MODEL_NOT_FOUND": "This model name is not available to your key; pick another in Controls & AI.",
    "BAD_REQUEST": "Google rejected the request format.",
    "FAILED_PRECONDITION": "Google refused the request for this project (often billing or regional availability).",
    "SERVER_ERROR": "Google returned a server error; the request may have been processed.",
    "CONNECTION": "The connection to Google failed or timed out; the request may have been processed.",
    "BAD_RESPONSE": "Google's response did not have the expected shape.",
}


class GeminiError(RuntimeError):
    def __init__(self, label: str, *, billed: bool = False, retry_after: float | None = None, message: str = "",
                 model: str = ""):
        super().__init__(label)
        self.label, self.billed, self.retry_after, self.message, self.model = label, billed, retry_after, message, model

    @property
    def hint(self) -> str:
        return HINTS.get(self.label, "")


def _retry_delay(details: list) -> float | None:
    for d in details or []:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("RetryInfo"):
            m = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(d.get("retryDelay", "")))
            if m:
                return float(m.group(1))
    return None


def classify_http(code: int, body: dict | None, key: str = "", model: str = "") -> GeminiError:
    err = (body or {}).get("error") or {}
    status = str(err.get("status") or "")
    message = str(err.get("message") or "")[:200]
    if key:
        message = message.replace(key, "<key>")
    reasons = {str(d.get("reason")) for d in err.get("details") or [] if isinstance(d, dict) and d.get("reason")}
    retry = _retry_delay(err.get("details") or [])
    if code == 503 or status == "UNAVAILABLE":
        label, billed = "UNAVAILABLE", False
    elif code == 429 or status == "RESOURCE_EXHAUSTED":
        label, billed = "RATE_LIMITED", False
    elif code == 401 or status == "UNAUTHENTICATED" or "API_KEY_INVALID" in reasons:
        label, billed = "AUTH", False
    elif code == 403 or status == "PERMISSION_DENIED":
        label, billed = "PERMISSION_DENIED", False
    elif code == 404 or status == "NOT_FOUND":
        label, billed = "MODEL_NOT_FOUND", False
    elif status == "FAILED_PRECONDITION":
        label, billed = "FAILED_PRECONDITION", False
    elif 400 <= code < 500:
        label, billed = "BAD_REQUEST", False
    else:
        label, billed = "SERVER_ERROR", True  # 500/504: the request may have been processed
    return GeminiError(label, billed=billed, retry_after=retry, message=message, model=model)


def parse(body: dict, model: str) -> dict:
    """The answer, its finish state and the billed token counts from a generateContent response."""
    if not isinstance(body, dict):
        raise GeminiError("BAD_RESPONSE", model=model)
    usage = body.get("usageMetadata") or {}
    prompt_t = int(usage.get("promptTokenCount") or 0)
    cand_t = int(usage.get("candidatesTokenCount") or 0)
    think_t = int(usage.get("thoughtsTokenCount") or 0)
    tokens = {"input_tokens": prompt_t, "output_tokens": cand_t + think_t, "thinking_tokens": think_t}
    block = (body.get("promptFeedback") or {}).get("blockReason")
    cands = body.get("candidates") or []
    if block or not cands:
        return {"model": model, "model_version": body.get("modelVersion"), "text": "", "state": "REFUSED",
                "finish_reason": f"PROMPT_BLOCKED:{block}" if block else "NO_CANDIDATES", **tokens}
    c = cands[0] or {}
    parts = (c.get("content") or {}).get("parts") or []
    text = "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    finish = str(c.get("finishReason") or "")
    state = ("TRUNCATED" if finish == "MAX_TOKENS" else "REFUSED" if finish in REFUSAL_FINISH or not text.strip()
             else "DONE")
    return {"model": model, "model_version": body.get("modelVersion"), "text": text, "state": state,
            "finish_reason": finish or None, **tokens}


class Client:
    """One API key; ``transport(method, url, headers, body) -> (status, parsed_json)`` is injectable for tests."""

    def __init__(self, key: str, *, transport=None, sleep=time.sleep, timeout: float = 240.0):
        if not key or any(c.isspace() for c in key):
            raise GeminiError("AUTH")
        self._key, self._sleep, self._timeout = key, sleep, timeout
        self._transport = transport or self._http

    def _http(self, method: str, url: str, headers: dict, body: bytes | None):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                raw = r.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise GeminiError("BAD_RESPONSE")
                return r.status, json.loads(raw)
        except urllib.error.HTTPError as e:
            try:
                parsed = json.loads(e.read(65536) or b"{}")
            except ValueError:
                parsed = {}
            return e.code, parsed
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GeminiError("CONNECTION", billed=True) from None
        except ValueError:
            raise GeminiError("BAD_RESPONSE", billed=True) from None

    def generate(self, *, model: str, system: str, user: str, max_tokens: int, effort: str | None = None) -> dict:
        cfg: dict = {"maxOutputTokens": int(max_tokens)}
        levels = MODELS.get(model, {}).get("thinking_levels") or ()
        if effort and effort in levels:
            cfg["thinkingConfig"] = {"thinkingLevel": effort}
        payload = {"systemInstruction": {"parts": [{"text": system}]},
                   "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": cfg}
        code, body = self._transport("POST", f"{BASE}/models/{model}:generateContent",
                                     {"Content-Type": "application/json", "x-goog-api-key": self._key},
                                     json.dumps(payload).encode())
        if code != 200:
            raise classify_http(code, body, self._key, model)
        return parse(body, model)

    def generate_with_fallback(self, *, chain: list[str], **kw) -> tuple[dict, list[dict]]:
        """Try each model in ``chain``. Busy (503) moves on at once; a quota error (429) waits once when Google's
        retry delay is short, else moves on. Auth, permission and request errors stop: another model would fail
        the same way. Returns (result, attempts); raises the last error when every model fails."""
        attempts, last = [], None
        for model in chain:
            for retry in (False, True):
                try:
                    out = self.generate(model=model, **kw)
                    attempts.append({"model": model, "result": out["state"]})
                    return out, attempts
                except GeminiError as e:
                    attempts.append({"model": model, "result": e.label, "billed": e.billed})
                    last = e
                    if e.label == "RATE_LIMITED" and not retry and e.retry_after is not None \
                            and e.retry_after <= MAX_RETRY_WAIT:
                        self._sleep(e.retry_after)
                        continue
                    if e.label in ("UNAVAILABLE", "RATE_LIMITED", "SERVER_ERROR", "MODEL_NOT_FOUND"):
                        break  # next model
                    e.attempts = attempts
                    raise
        last.attempts = attempts
        raise last


def chain_for(model: str, fallback: bool) -> list[str]:
    chain = [model if model in MODELS else DEFAULT_MODEL]
    if fallback:
        chain += [m for m in FALLBACK_CHAIN if m not in chain]
    return chain
