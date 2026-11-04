"""Provider adapter contract for a search/extraction service. No provider is configured by default.

Owner decision (5 Nov 2026): the Perplexity adapters were removed; an LLM provider is not expected to add much to
the algorithm. The contract stays so one can be plugged in later without touching the queue, budget, schema,
templates or archive:

* ``run(request: ProviderRequest, timeout) -> ProviderResult`` with the raw response bytes and their SHA-256, the
  provider's response id and model, the assistant text, parsed JSON when a schema was requested, every retrieved
  search result (url/title/snippet/date as returned), URL-citation annotations and usage/cost as reported.
* Failures raise ``ProviderError`` with a fixed label: AUTH, RATE_LIMITED (with retry_after), OVERLOADED,
  BAD_REQUEST, SERVER, TIMEOUT, MALFORMED, NOT_COMPLETED, NOT_CONFIGURED, NOT_ARCHIVED. Provider text is never echoed.
* Only the provider's own key, public company identifiers and public facts are ever sent (enforced in jobs).

``parse_response`` reads the OpenAI "Responses"-style JSON shape (output[] message parts with ``output_text``
and ``url_citation`` annotations, ``search_results`` items, ``usage.cost.total_cost``) that compatible services
produce; an adapter for a different shape must convert to ``ProviderResult`` itself.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal


class ProviderError(RuntimeError):
    def __init__(self, label: str, retry_after: float | None = None, http_status: int | None = None, result=None):
        super().__init__(label + (f" (HTTP {http_status})" if http_status else ""))
        self.label, self.retry_after, self.http_status = label, retry_after, http_status
        self.result = result  # parsed response when one exists (NOT_COMPLETED can still carry billed usage)


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model: str
    instructions: str
    input: str
    max_output_tokens: int
    max_steps: int
    web_search: dict | None = None  # {"search_type", "max_results", "max_tokens", "max_tokens_per_page", "filters"}
    response_schema: dict | None = None
    schema_name: str = "evidence_v1"

    def body(self) -> dict:
        body = {"model": self.model, "instructions": self.instructions, "input": self.input,
                "max_output_tokens": self.max_output_tokens, "max_steps": self.max_steps, "store": False}
        if self.web_search is not None:
            body["tools"] = [{"type": "web_search", **self.web_search}]
        if self.response_schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": self.schema_name, "schema": self.response_schema}}
        return body

    def request_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.body(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderResult:
    response_id: str
    status: str
    model: str
    text: str
    parsed: dict | None
    search_results: tuple
    citations: tuple
    usage: dict
    cost_usd: Decimal | None
    raw: bytes
    raw_sha256: str
    latency_seconds: float
    tool_calls: dict = field(default_factory=dict)

    @property
    def retrieved_urls(self) -> frozenset:
        return frozenset([r["url"] for r in self.search_results if r.get("url")]
                         + [c["url"] for c in self.citations if c.get("url")])


def parse_response(raw: bytes, latency: float = 0.0, want_json: bool = False) -> ProviderResult:
    try:
        d = json.loads(raw)
    except ValueError:
        raise ProviderError("MALFORMED") from None
    if not isinstance(d, dict) or not isinstance(d.get("output"), list):
        raise ProviderError("MALFORMED")
    texts, citations, results = [], [], []
    for item in d["output"]:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    texts.append(str(part.get("text") or ""))
                    for a in part.get("annotations") or []:
                        if isinstance(a, dict) and a.get("type") == "url_citation" and a.get("url"):
                            citations.append({"url": str(a["url"]), "title": str(a.get("title") or "")})
        elif item.get("type") == "search_results":
            for r in item.get("results") or []:
                if isinstance(r, dict) and r.get("url"):
                    results.append({k: r.get(k) for k in ("id", "url", "title", "snippet", "date", "last_updated", "source")})
    usage = d.get("usage") if isinstance(d.get("usage"), dict) else {}
    cost = usage.get("cost", {}).get("total_cost") if isinstance(usage.get("cost"), dict) else None
    text = "".join(texts)
    parsed = None
    if want_json and text.strip():
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None  # validation reports SCHEMA_PARSE_FAILED; the raw response is still archived
    return ProviderResult(
        response_id=str(d.get("id") or ""), status=str(d.get("status") or ""), model=str(d.get("model") or ""), text=text,
        parsed=parsed, search_results=tuple(results), citations=tuple(citations), usage=usage,
        cost_usd=Decimal(str(cost)) if cost is not None else None, raw=raw, raw_sha256=hashlib.sha256(raw).hexdigest(),
        latency_seconds=latency,
        tool_calls=usage.get("tool_calls_details") if isinstance(usage.get("tool_calls_details"), dict) else {})


def http_error_label(status: int, error_code: str = "", retry_after: float | None = None) -> ProviderError:
    """Shared mapping for future HTTP adapters: fixed labels, never provider text."""
    if status in (401, 403):
        return ProviderError("AUTH", http_status=status)
    if status == 429:
        return ProviderError("OVERLOADED" if error_code == "overloaded" else "RATE_LIMITED", retry_after=retry_after or 1.0,
                             http_status=429)
    if status in (400, 404, 413, 422):
        return ProviderError("BAD_REQUEST", http_status=status)
    if status in (502, 503, 529):
        return ProviderError("OVERLOADED", retry_after=retry_after, http_status=status)
    return ProviderError("SERVER", http_status=status)


class NullProvider:
    """Default: no provider configured. Jobs stay queued until they expire; nothing is sent anywhere."""
    name = "none"

    def run(self, req: ProviderRequest, timeout: float = 0) -> ProviderResult:
        raise ProviderError("NOT_CONFIGURED")


class ArchivedProvider:
    """Replay provider: serves archived responses by request hash and never calls the network.

    Historical replay must consume saved point-in-time evidence; a request that was never archived is an error
    (NOT_ARCHIVED), not a reason to search today's internet.
    """
    name = "archive"

    def __init__(self, lookup):
        self._lookup = lookup  # request_hash -> raw bytes or None

    def run(self, req: ProviderRequest, timeout: float = 0) -> ProviderResult:
        raw = self._lookup(req.request_hash())
        if raw is None:
            raise ProviderError("NOT_ARCHIVED")
        return parse_response(raw, 0.0, want_json=req.response_schema is not None)
