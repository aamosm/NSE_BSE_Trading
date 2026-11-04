"""Evidence schema (``evidence.v1``) and validation of provider output.

Two layers:
* ``SCHEMA``: conservative JSON Schema sent as ``response_format`` (types, enums, required, closed
  objects). Provider support for further keywords is not documented, so bounds are checked locally.
* ``assess()``: semantic rules applied to every response before anything becomes a fact:
  - task id and ISIN must match the job;
  - every source URL must be HTTPS, on an allowed domain for its source type, and among the URLs the
    provider actually retrieved (search results or citations) - links typed by the model are not trusted;
  - every passage must be found (normalised) in retrieved text before the fact is ACCEPTED; otherwise
    the fact is a CANDIDATE that needs verification;
  - dates and times must parse; a publication time later than receipt (+1 day tolerance) is rejected;
  - amounts must be finite with an enumerated unit and basis;
  - novelty is recomputed here from fact identity, never taken from the model;
  - there is no field for opinions; extra fields are rejected by the closed schema.
Retrieved text is untrusted data: nothing in it is ever executed or treated as an instruction.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from ..common import IST, timestamp

SCHEMA_VERSION = "evidence.v1"
EVENT_TYPES = [
    "FINANCIAL_RESULTS", "RESULTS_DATE_ANNOUNCED", "BOARD_MEETING_OUTCOME", "DIVIDEND", "BONUS", "SPLIT", "RIGHTS",
    "BUYBACK", "MERGER_DEMERGER", "FUNDRAISE", "ORDER_OR_CONTRACT", "GUIDANCE", "CREDIT_RATING",
    "MANAGEMENT_CHANGE", "PROMOTER_HOLDING_OR_PLEDGE", "REGULATORY_ACTION", "LITIGATION", "AGM_EGM", "INSOLVENCY",
    "TRADING_STATUS", "CLARIFICATION", "OTHER_MATERIAL",
]
DATE_KINDS = ["MEETING_DATE", "RESULTS_DATE", "RECORD_DATE", "EX_DATE", "PAYMENT_DATE", "EFFECTIVE_DATE", "OTHER"]
FIELDS = [
    "REVENUE", "EBITDA", "PROFIT_BEFORE_TAX", "NET_PROFIT", "EPS_BASIC", "EPS_DILUTED", "DIVIDEND_PER_SHARE",
    "BONUS_NEW_SHARES", "BONUS_HELD_SHARES", "SPLIT_OLD_FACE_VALUE", "SPLIT_NEW_FACE_VALUE", "ORDER_VALUE",
    "ISSUE_SIZE", "ISSUE_PRICE", "SHARES_ISSUED", "TOTAL_DEBT", "CASH_AND_EQUIVALENTS", "PROMOTER_HOLDING_PERCENT",
    "PROMOTER_PLEDGED_PERCENT", "GUIDANCE_GROWTH_PERCENT", "OTHER",
]
UNITS = ["INR", "INR_THOUSAND", "INR_LAKH", "INR_MILLION", "INR_CRORE", "PER_SHARE_INR", "PERCENT", "SHARES",
         "RATIO", "COUNT", "OTHER"]
BASES = ["CONSOLIDATED", "STANDALONE", "NOT_APPLICABLE", "UNKNOWN"]
SOURCE_TYPES = ["EXCHANGE", "REGULATOR", "COMPANY_IR", "NEWS"]
NOVELTY = ["NEW", "CONFIRMS_KNOWN", "UPDATES_KNOWN", "UNCLEAR"]

_SOURCE = {"type": "object", "additionalProperties": False, "required": ["url", "passage", "source_type"],
           "properties": {"url": {"type": "string"}, "passage": {"type": "string"},
                          "source_type": {"type": "string", "enum": SOURCE_TYPES}}}
_FACT = {
    "type": "object", "additionalProperties": False,
    "required": ["event_type", "summary", "published_at", "period", "dates", "values", "sources", "known_fact_id",
                 "novelty"],
    "properties": {
        "event_type": {"type": "string", "enum": EVENT_TYPES},
        "summary": {"type": "string"},
        "published_at": {"type": ["string", "null"]},
        "period": {"type": ["string", "null"]},
        "dates": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["kind", "date"],
                                             "properties": {"kind": {"type": "string", "enum": DATE_KINDS},
                                                            "date": {"type": "string"}}}},
        "values": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["field", "amount", "unit", "basis"],
            "properties": {"field": {"type": "string", "enum": FIELDS}, "amount": {"type": ["number", "null"]},
                           "unit": {"type": "string", "enum": UNITS}, "basis": {"type": "string", "enum": BASES}}}},
        "sources": {"type": "array", "items": _SOURCE},
        "known_fact_id": {"type": ["string", "null"]},
        "novelty": {"type": "string", "enum": NOVELTY},
    },
}
_CONTRADICTION = {
    "type": "object", "additionalProperties": False,
    "required": ["known_fact_id", "field", "known_value", "reported_value", "sources"],
    "properties": {"known_fact_id": {"type": "string"}, "field": {"type": "string"},
                   "known_value": {"type": ["string", "number", "null"]},
                   "reported_value": {"type": ["string", "number", "null"]}, "sources": {"type": "array", "items": _SOURCE}},
}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "task_id", "isin", "facts", "contradictions", "unknown_fields", "no_new_evidence"],
    "properties": {
        "schema_version": {"type": "string", "enum": [SCHEMA_VERSION]},
        "task_id": {"type": "string"},
        "isin": {"type": "string"},
        "facts": {"type": "array", "items": _FACT},
        "contradictions": {"type": "array", "items": _CONTRADICTION},
        "unknown_fields": {"type": "array", "items": {"type": "string"}},
        "no_new_evidence": {"type": "boolean"},
    },
}
SCHEMA_SHA256 = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True).encode()).hexdigest()
LIMITS = {"facts": 20, "sources_per_fact": 5, "passage_max": 600, "passage_min": 12, "summary_max": 300,
          "values_per_fact": 10, "contradictions": 10}
OFFICIAL_DOMAINS = {"EXCHANGE": ("nseindia.com", "bseindia.com"), "REGULATOR": ("sebi.gov.in",)}

_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list, "null": type(None)}


def schema_errors(value, schema, path="$") -> list[str]:
    """Validate the subset of JSON Schema used above (type, enum, required, properties,
    additionalProperties=false, items)."""
    errors = []
    types = schema.get("type")
    if types is not None:
        allowed = types if isinstance(types, list) else [types]
        ok = False
        for t in allowed:
            if t == "number":
                ok |= isinstance(value, (int, float)) and not isinstance(value, bool)
            elif t == "integer":
                ok |= isinstance(value, int) and not isinstance(value, bool)
            else:
                ok |= isinstance(value, _TYPES[t])
        if not ok:
            return [f"{path}: expected {allowed}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not one of the allowed values")
    if isinstance(value, dict) and "properties" in schema:
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: missing")
        if schema.get("additionalProperties") is False:
            errors += [f"{path}.{k}: not allowed" for k in value if k not in schema["properties"]]
        for key, sub in schema["properties"].items():
            if key in value:
                errors += schema_errors(value[key], sub, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += schema_errors(item, schema["items"], f"{path}[{i}]")
    return errors


def normalise_url(url: str) -> str:
    u = urlsplit(url.strip())
    return urlunsplit((u.scheme.lower(), (u.hostname or "").lower(), u.path.rstrip("/") or "/", u.query, ""))


def domain_allowed(host: str, domains) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


def normalise_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = t.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-").replace("₹", "rs.")
    return re.sub(r"\s+", " ", t).strip()


def passage_found(passage: str, text: str) -> bool:
    p = normalise_text(passage)
    return len(p) >= LIMITS["passage_min"] and p in normalise_text(text)


def parse_time(value: str | None):
    """ISO date or date-time. A date-time without an offset is refused (ambiguous), a date is kept as a date."""
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("time without offset")
    return t.astimezone(IST)


def fact_identity(isin: str, fact: dict) -> str:
    """Identity of the underlying event, independent of wording and of how many articles repeat it."""
    values = sorted((v["field"], None if v["amount"] is None else repr(float(v["amount"])), v["unit"], v["basis"])
                    for v in fact.get("values", []))
    dates = sorted((d["kind"], d["date"]) for d in fact.get("dates", []))
    key = [isin, fact["event_type"], fact.get("period"), dates, values]
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:24]


def event_identity(isin: str, fact: dict) -> str:
    """Coarser identity: same event type and period regardless of values (detects updates/contradictions)."""
    key = [isin, fact["event_type"], fact.get("period"), sorted(d["date"] for d in fact.get("dates", [])
                                                                if d["kind"] in ("MEETING_DATE", "RECORD_DATE",
                                                                                 "EX_DATE", "RESULTS_DATE"))]
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:24]


def registrable(host: str) -> str:
    parts = (host or "").lower().split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "gov", "nic", "ac", "org", "net") and parts[-1] == "in":
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _words(passage: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalise_text(passage))


def same_passage(a: str, b: str, threshold=0.6) -> bool:
    """Near-identical wording (syndicated or copied text): equal or contained word sequences, or a
    5-word-shingle Jaccard similarity of at least ``threshold``."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    ja, jb = " ".join(wa), " ".join(wb)
    if ja == jb or (min(len(wa), len(wb)) >= 8 and (ja in jb or jb in ja)):
        return True
    sa = {" ".join(wa[i:i + 5]) for i in range(max(1, len(wa) - 4))}
    sb = {" ".join(wb[i:i + 5]) for i in range(max(1, len(wb) - 4))}
    return len(sa & sb) / len(sa | sb) >= threshold


def independent_sources(sources) -> int:
    """Distinct publishers; publishers carrying near-identical passages count once (syndication/copies)."""
    items = [(registrable(urlsplit(s["url"]).hostname or ""), s.get("passage", "")) for s in sources]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i][0] == items[j][0] or same_passage(items[i][1], items[j][1]):
                parent[find(i)] = find(j)
    return len({find(i) for i in range(len(items))})


@dataclass
class Assessment:
    accepted: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    rejected: list = field(default_factory=list)  # (fact or contradiction, [reasons])
    contradictions: list = field(default_factory=list)
    unknown_fields: list = field(default_factory=list)
    errors: list = field(default_factory=list)  # document-level problems

    @property
    def ok(self) -> bool:
        return not self.errors


def _check_sources(sources, allowed, retrieved, texts):
    reasons, verified = [], True
    if not 1 <= len(sources) <= LIMITS["sources_per_fact"]:
        return ["SOURCE_COUNT"], False
    for s in sources:
        u = urlsplit(s["url"])
        if u.scheme != "https" or not u.hostname:
            reasons.append("SOURCE_NOT_HTTPS")
            continue
        domains = allowed.get(s["source_type"], ())
        if not domain_allowed(u.hostname, domains):
            reasons.append(f"DOMAIN_NOT_ALLOWED_FOR_{s['source_type']}")
        if normalise_url(s["url"]) not in retrieved:
            reasons.append("CITATION_NOT_RETRIEVED")
        if not LIMITS["passage_min"] <= len(s["passage"]) <= LIMITS["passage_max"]:
            reasons.append("PASSAGE_LENGTH")
        page = texts.get(normalise_url(s["url"]), "")
        if not passage_found(s["passage"], page):
            verified = False
    return reasons, verified


def assess(doc, *, job_id: str, isin: str, allowed: dict, result, known_facts=(), page_texts=None,
           received_at=None) -> Assessment:
    """Validate one provider document. ``allowed`` maps source type -> allowed registrable domains.

    ``page_texts`` maps normalised URL -> retrieved text (search snippets and any archived page copies);
    a passage counts as verified only if found in that text.
    """
    a = Assessment()
    if not isinstance(doc, dict):
        a.errors.append("SCHEMA_PARSE_FAILED")
        return a
    errs = schema_errors(doc, SCHEMA)
    if errs:
        a.errors += ["SCHEMA:" + e for e in errs[:20]]
        return a
    if doc["task_id"] != job_id or doc["isin"] != isin:
        a.errors.append("TASK_OR_ISIN_MISMATCH")
        return a
    if len(doc["facts"]) > LIMITS["facts"] or len(doc["contradictions"]) > LIMITS["contradictions"]:
        a.errors.append("TOO_MANY_ITEMS")
        return a
    received = timestamp(received_at) if received_at else None
    retrieved = {normalise_url(u) for u in result.retrieved_urls}
    texts = dict(page_texts or {})
    for r in result.search_results:
        key = normalise_url(r["url"])
        texts[key] = texts.get(key, "") + " " + " ".join(str(r.get(k) or "") for k in ("title", "snippet"))
    known = {f.get("fact_key"): f for f in known_facts if f.get("fact_key")}
    known_events = {f.get("event_key"): f for f in known_facts if f.get("event_key")}
    a.unknown_fields = list(doc["unknown_fields"])
    for fact in doc["facts"]:
        reasons = []
        if not fact["summary"].strip() or len(fact["summary"]) > LIMITS["summary_max"]:
            reasons.append("SUMMARY_LENGTH")
        if len(fact["values"]) > LIMITS["values_per_fact"]:
            reasons.append("TOO_MANY_VALUES")
        try:
            published = parse_time(fact["published_at"])
            for d in fact["dates"]:
                date.fromisoformat(d["date"])
        except ValueError:
            reasons.append("BAD_DATE_OR_TIME")
            published = None
        if received and isinstance(published, datetime) and published > received + timedelta(days=1):
            reasons.append("PUBLISHED_AFTER_RECEIPT")
        for v in fact["values"]:
            if v["amount"] is not None and not math.isfinite(float(v["amount"])):
                reasons.append("NON_FINITE_AMOUNT")
        src_reasons, verified = _check_sources(fact["sources"], allowed, retrieved, texts)
        reasons += src_reasons
        if reasons:
            a.rejected.append((fact, sorted(set(reasons))))
            continue
        key, ekey = fact_identity(isin, fact), event_identity(isin, fact)
        novelty = ("CONFIRMS_KNOWN" if key in known else "UPDATES_KNOWN" if ekey in known_events else "NEW")
        primary = all(s["source_type"] in ("EXCHANGE", "REGULATOR", "COMPANY_IR") for s in fact["sources"])
        record = {**fact, "fact_key": key, "event_key": ekey, "novelty_model": fact["novelty"], "novelty": novelty,
                  "independent_sources": independent_sources(fact["sources"]), "passages_verified": verified,
                  "primary_sources_only": primary}
        (a.accepted if verified and primary else a.candidates).append(record)
    for c in doc["contradictions"]:
        src_reasons, verified = _check_sources(c["sources"], allowed, retrieved, texts)
        if src_reasons or c["known_fact_id"] not in {f.get("fact_id") for f in known_facts}:
            a.rejected.append((c, sorted(set(src_reasons + ([] if c["known_fact_id"] in {f.get("fact_id") for f in
                                                                                         known_facts}
                                                           else ["UNKNOWN_FACT_ID"])))))
            continue
        a.contradictions.append({**c, "passages_verified": verified,
                                 "independent_sources": independent_sources(c["sources"])})
    return a
