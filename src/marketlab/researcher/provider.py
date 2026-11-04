"""Provider adapter contract and the Perplexity Agent API implementation.

Contract (any replacement provider must satisfy it):
* ``run(request) -> ProviderResult`` with the raw response bytes and their SHA-256, the provider's
  response id and model, assistant text, parsed JSON (when a schema was requested), every search
  result (url/title/snippet/date as returned), URL-citation annotations, and usage/cost as reported.
* Failures raise ``ProviderError`` with a fixed label: AUTH, RATE_LIMITED (with retry_after),
  OVERLOADED, BAD_REQUEST, SERVER, TIMEOUT, MALFORMED, NOT_COMPLETED. Provider error text is not echoed.
* No credentials other than the provider key, no account data and no trading tools are ever sent.

Perplexity request/response shapes follow https://docs.perplexity.ai/api-reference/agent-post (read
5 Nov 2026): ``POST https://api.perplexity.ai/v1/agent`` with Bearer auth; ``model``, ``input``,
``instructions``, ``max_output_tokens``, ``max_steps``, ``store``, ``tools`` (``web_search`` with
``search_type``, ``max_results``, ``max_tokens``, ``max_tokens_per_page`` and ``filters``), and
``response_format`` ``{"type": "json_schema", "json_schema": {"name", "schema"}}``. Output text lives in
``output[].type == "message"`` content parts of type ``output_text``; search results are separate
``search_results`` output items; cost is ``usage.cost.total_cost``.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from ..netutil import NoRedirect, ResponseLimit, read_bounded

AGENT_URL = "https://api.perplexity.ai/v1/agent"
MAX_RESPONSE = 8 * 1024 * 1024


class ProviderError(RuntimeError):
    def __init__(self, label: str, retry_after: float | None = None, http_status: int | None = None, result=None):
        super().__init__(label + (f" (HTTP {http_status})" if http_status else ""))
        self.label, self.retry_after, self.http_status = label, retry_after, http_status
        self.result = result  # parsed response when one exists (e.g. NOT_COMPLETED can still carry billed usage)


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
                    results.append({k: r.get(k) for k in ("id", "url", "title", "snippet", "date", "last_updated",
                                                          "source")})
    usage = d.get("usage") if isinstance(d.get("usage"), dict) else {}
    cost = usage.get("cost", {}).get("total_cost") if isinstance(usage.get("cost"), dict) else None
    text = "".join(texts)
    parsed = None
    if want_json and text.strip():
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None  # validation reports SCHEMA_PARSE_FAILED; the raw response is still archived
    status = str(d.get("status") or "")
    return ProviderResult(
        response_id=str(d.get("id") or ""), status=status, model=str(d.get("model") or ""), text=text, parsed=parsed,
        search_results=tuple(results), citations=tuple(citations), usage=usage,
        cost_usd=Decimal(str(cost)) if cost is not None else None, raw=raw,
        raw_sha256=hashlib.sha256(raw).hexdigest(), latency_seconds=latency,
        tool_calls=usage.get("tool_calls_details") if isinstance(usage.get("tool_calls_details"), dict) else {})


class PerplexityAgent:
    name = "perplexity-agent"

    def __init__(self, api_key: str, *, opener=None, clock=time.monotonic):
        if not api_key or not api_key.strip():
            raise ValueError("PERPLEXITY_API_KEY is missing from the private env file")
        self._key = api_key.strip()
        self._opener = opener or build_opener(NoRedirect())
        self._clock = clock

    def run(self, req: ProviderRequest, timeout: float = 120.0) -> ProviderResult:
        data = json.dumps(req.body()).encode()
        http = Request(AGENT_URL, data=data, method="POST", headers={
            "Authorization": "Bearer " + self._key, "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": "MarketLab-Research/0.3"})
        start = self._clock()
        try:
            with self._opener.open(http, timeout=timeout) as r:
                raw = read_bounded(r, MAX_RESPONSE, deadline=timeout)
        except HTTPError as e:
            raise _http_error(e) from None
        except ResponseLimit:  # read deadline, size limit or a refused redirect
            raise ProviderError("TIMEOUT") from None
        except (URLError, TimeoutError, OSError):
            raise ProviderError("TIMEOUT") from None
        result = parse_response(raw, self._clock() - start, want_json=req.response_schema is not None)
        if result.status != "completed":
            raise ProviderError("NOT_COMPLETED", result=result)
        return result


def _http_error(e: HTTPError) -> ProviderError:
    retry = None
    try:
        retry = float(e.headers.get("Retry-After")) if e.headers and e.headers.get("Retry-After") else None
    except (TypeError, ValueError):
        retry = None
    try:
        body = json.loads(e.read(65536) or b"{}")
    except Exception:
        body = {}
    code = ""
    if isinstance(body, dict):
        err = body.get("error")
        code = (err.get("code") or err.get("type") or "") if isinstance(err, dict) else ""
    if e.code in (401, 403):
        return ProviderError("AUTH", http_status=e.code)
    if e.code == 429:
        return ProviderError("OVERLOADED" if code == "overloaded" else "RATE_LIMITED", retry_after=retry or 1.0,
                             http_status=429)
    if e.code in (400, 404, 413, 422):
        return ProviderError("BAD_REQUEST", http_status=e.code)
    if e.code in (502, 503, 529):
        return ProviderError("OVERLOADED", retry_after=retry, http_status=e.code)
    return ProviderError("SERVER", http_status=e.code)


class ArchivedProvider:
    """Replay provider: serves archived responses by request hash and never calls the network.

    Historical replay must consume saved point-in-time evidence; a request that was never archived is
    an error (NOT_ARCHIVED), not a reason to search today's internet.
    """
    name = "archive"

    def __init__(self, lookup):
        self._lookup = lookup  # request_hash -> raw bytes or None

    def run(self, req: ProviderRequest, timeout: float = 0) -> ProviderResult:
        raw = self._lookup(req.request_hash())
        if raw is None:
            raise ProviderError("NOT_ARCHIVED")
        return parse_response(raw, 0.0, want_json=req.response_schema is not None)


# ---- Search API: ranked results only (no model answer) ------------------------------------------------
# https://docs.perplexity.ai/api-reference/search-post (read 5 Nov 2026). Billed per successful request
# (an array of up to five queries is one billing unit): standard $0.005, fast $0.001. 429s are not billed.
# The response carries no cost, so the documented price is what the ledger settles.

SEARCH_URL = "https://api.perplexity.ai/search"
SEARCH_PRICE_USD = {"web": Decimal("0.005"), "fast": Decimal("0.001")}


@dataclass(frozen=True, slots=True)
class SearchRequest:
    queries: tuple  # 1 to 5 query strings
    max_results: int = 10
    max_tokens_per_page: int = 1024
    search_type: str = "fast"
    domains: tuple = ()  # search_domain_filter allowlist (max 20)
    after: str | None = None  # MM/DD/YYYY
    before: str | None = None  # MM/DD/YYYY
    country: str = "IN"

    def body(self) -> dict:
        if not 1 <= len(self.queries) <= 5 or not 1 <= self.max_results <= 20 or len(self.domains) > 20:
            raise ValueError("1-5 queries, 1-20 results and at most 20 domains")
        if self.search_type not in SEARCH_PRICE_USD:
            raise ValueError("search_type must be web or fast")
        body = {"query": list(self.queries) if len(self.queries) > 1 else self.queries[0],
                "max_results": self.max_results, "max_tokens_per_page": self.max_tokens_per_page,
                "search_type": self.search_type, "country": self.country}
        if self.domains:
            body["search_domain_filter"] = list(self.domains)
        if self.after:
            body["search_after_date_filter"] = self.after
        if self.before:
            body["search_before_date_filter"] = self.before
        return body

    @property
    def price_usd(self) -> Decimal:
        return SEARCH_PRICE_USD[self.search_type]


@dataclass(frozen=True, slots=True)
class SearchResult:
    search_id: str
    results: tuple  # {"title", "url", "snippet", "date", "last_updated"} as returned (dates are the provider's)
    raw: bytes
    raw_sha256: str
    latency_seconds: float


class PerplexitySearch:
    name = "perplexity-search"

    def __init__(self, api_key: str, *, opener=None, clock=time.monotonic):
        if not api_key or not api_key.strip():
            raise ValueError("PERPLEXITY_API_KEY is missing from the private env file")
        self._key, self._opener, self._clock = api_key.strip(), opener or build_opener(NoRedirect()), clock

    def run(self, req: SearchRequest, timeout: float = 60.0) -> SearchResult:
        http = Request(SEARCH_URL, data=json.dumps(req.body()).encode(), method="POST", headers={
            "Authorization": "Bearer " + self._key, "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": "MarketLab-Research/0.3"})
        start = self._clock()
        try:
            with self._opener.open(http, timeout=timeout) as r:
                raw = read_bounded(r, MAX_RESPONSE, deadline=timeout)
        except HTTPError as e:
            raise _http_error(e) from None
        except (ResponseLimit, URLError, TimeoutError, OSError):
            raise ProviderError("TIMEOUT") from None
        try:
            d = json.loads(raw)
            rows = d["results"]
            if not isinstance(rows, list):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise ProviderError("MALFORMED") from None
        results = tuple({k: r.get(k) for k in ("title", "url", "snippet", "date", "last_updated")}
                        for r in rows if isinstance(r, dict) and r.get("url"))
        return SearchResult(str(d.get("id") or ""), results, raw, hashlib.sha256(raw).hexdigest(),
                            self._clock() - start)
