"""Research jobs: queue, per-kind policy, runner, archive and point-in-time fact store.

Runs in its own process (``marketlab research-run``); the collector and the decision engine never wait
for it. A fact becomes usable by a decision only from its ``extraction_completed_at`` time (the Store's
``available_at``), so a late result can never improve an earlier decision. Historical replay uses
``ArchivedProvider`` and never searches the live internet.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as clock, timedelta
from decimal import Decimal
from pathlib import Path

from ..common import IST, now, timestamp
from ..store import Store
from . import evidence, templates
from .budget import BudgetExceeded, Ledger, Limits, Policy, worst_case_usd
from .provider import ProviderError, ProviderRequest

DEFAULT_MODEL = "openai/gpt-6-luna"  # $0.10 / $0.50 per 1M tokens (5 Nov 2026); compatibility verified by smoke test


@dataclass(frozen=True, slots=True)
class KindPolicy:
    priority: int  # 1 = most urgent
    limits: Limits
    ttl: timedelta
    off_hours_only: bool = False  # never during 09:00-15:30 IST on weekdays


KINDS = {
    "material_event_investigation": KindPolicy(1, Limits(1500, 5, 3500, 3000, 8), timedelta(hours=3)),
    "upcoming_event_verification": KindPolicy(2, Limits(1200, 3, 3000, 3000, 6), timedelta(hours=24)),
    "contradiction_resolution": KindPolicy(2, Limits(1500, 4, 3500, 3000, 8), timedelta(hours=24)),
    "overnight_update": KindPolicy(3, Limits(1500, 4, 3000, 3000, 8), timedelta(hours=10)),
    "bounded_company_research": KindPolicy(5, Limits(2000, 8, 4000, 4000, 10, "web"), timedelta(hours=72), True),
}
TERMINAL = {"DONE", "FAILED", "EXPIRED", "DUPLICATE"}
STALE_RUNNING = timedelta(minutes=15)
PRIVATE_MARKERS = ("access_token", "request_token", "api_secret", "kite_user_id")


@dataclass(frozen=True)
class ResearchJob:
    job_id: str
    kind: str
    entity: dict  # isin, nse_symbol, bse_code, name, aliases (public identifiers only)
    window_start: datetime
    window_end: datetime
    allowed: dict  # source type -> registrable domains
    requested_fields: tuple = ()
    known_facts: tuple = ()  # public facts: fact_id, fact_key, event_key, event_type, period, dates, values, url
    trigger: dict | None = None
    created_at: datetime = field(default_factory=now)
    expires_at: datetime | None = None

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"Unknown research job kind {self.kind}")
        if not re.fullmatch(r"IN[A-Z0-9]{10}", self.entity.get("isin", "")) or not self.entity.get("name"):
            raise ValueError("A verified ISIN and legal name are required")
        if timestamp(self.window_end) <= timestamp(self.window_start):
            raise ValueError("Empty time window")
        forbidden = {"quantity", "holdings", "cash", "positions", "account", "pnl"} & set(self.entity)
        if forbidden:
            raise ValueError(f"Private account fields must never be sent to a research provider: {sorted(forbidden)}")
        domains = [d for v in self.allowed.values() for d in v]
        if not domains or len(domains) > 20:
            raise ValueError("Between 1 and 20 allowed domains (provider search_domain_filter limit)")

    @property
    def dedup_key(self) -> str:
        key = [self.kind, self.entity["isin"], self.window_start.isoformat(), self.window_end.isoformat(),
               sorted(self.requested_fields), sorted(f.get("fact_id", "") for f in self.known_facts),
               (self.trigger or {}).get("url")]
        return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:32]

    def expiry(self) -> datetime:
        return timestamp(self.expires_at) if self.expires_at else timestamp(self.created_at) + KINDS[self.kind].ttl

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, default=str, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "ResearchJob":
        d = json.loads(s)
        for k in ("window_start", "window_end", "created_at", "expires_at"):
            if d.get(k):
                d[k] = timestamp(d[k])
        d["requested_fields"] = tuple(d.get("requested_fields") or ())
        d["known_facts"] = tuple(d.get("known_facts") or ())
        return cls(**d)


class Queue:
    """Append-only job table plus state events; the current state is the latest event."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL,
                priority INTEGER NOT NULL, dedup_key TEXT NOT NULL, expires_at TEXT NOT NULL, spec TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS job_events (job_id TEXT NOT NULL, seq INTEGER NOT NULL, at TEXT NOT NULL,
                state TEXT NOT NULL, detail TEXT NOT NULL, PRIMARY KEY (job_id, seq));
            CREATE TRIGGER IF NOT EXISTS jobs_no_update BEFORE UPDATE ON jobs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS jobs_no_delete BEFORE DELETE ON jobs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS ev_no_update BEFORE UPDATE ON job_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS ev_no_delete BEFORE DELETE ON job_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        """)

    def event(self, job_id, state, at=None, **detail):
        with self.db:
            seq = self.db.execute("SELECT coalesce(max(seq), 0) + 1 FROM job_events WHERE job_id=?", (job_id,)).fetchone()[0]
            self.db.execute("INSERT INTO job_events VALUES (?,?,?,?,?)",
                            (job_id, seq, timestamp(at or now()).isoformat(), state, json.dumps(detail, default=str)))

    def state(self, job_id):
        row = self.db.execute("SELECT state, detail FROM job_events WHERE job_id=? ORDER BY seq DESC LIMIT 1",
                              (job_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else (None, {})

    def submit(self, job: ResearchJob, at=None) -> str:
        """QUEUED, or DUPLICATE when the same work is queued, running or done and unexpired."""
        at = timestamp(at or now())
        for (other,) in self.db.execute("SELECT job_id FROM jobs WHERE dedup_key=?", (job.dedup_key,)).fetchall():
            st, _ = self.state(other)
            exp = timestamp(self.db.execute("SELECT expires_at FROM jobs WHERE job_id=?", (other,)).fetchone()[0])
            if st not in ("FAILED", "EXPIRED") and (st != "DONE" or at < exp):
                return "DUPLICATE"
        with self.db:
            self.db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                            (job.job_id, timestamp(job.created_at).isoformat(), job.kind, KINDS[job.kind].priority,
                             job.dedup_key, job.expiry().isoformat(), job.to_json()))
        self.event(job.job_id, "QUEUED", at)
        return "QUEUED"

    def pending(self, at=None):
        at = timestamp(at or now())
        out = []
        for job_id, priority, created, expires, spec in self.db.execute(
                "SELECT job_id, priority, created_at, expires_at, spec FROM jobs"):
            st, detail = self.state(job_id)
            if st == "RUNNING":
                started = self.db.execute("SELECT at FROM job_events WHERE job_id=? ORDER BY seq DESC LIMIT 1",
                                          (job_id,)).fetchone()[0]
                if at - timestamp(started) > STALE_RUNNING:
                    # A crashed worker: the job fails; its open reservation stays counted as spent (conservative).
                    self.event(job_id, "FAILED", at, error="STALE_RUNNING")
                continue
            if st in TERMINAL:
                continue
            if timestamp(expires) <= at:
                self.event(job_id, "EXPIRED", at)
                continue
            if st == "DEFERRED" and detail.get("until") and timestamp(detail["until"]) > at:
                continue
            out.append((priority, created, ResearchJob.from_json(spec)))
        out.sort(key=lambda x: (x[0], x[1]))
        return [j for _, _, j in out]

    def close(self):
        self.db.close()


class Archive:
    """Raw provider responses (gzip) plus metadata in an append-only Store; facts in the same Store."""

    def __init__(self, base: Path):
        self.base = base
        self.store = Store(base / "evidence.sqlite3", max_bytes=512 * 1024 * 1024)

    def save_response(self, job, req: ProviderRequest, result, received_at, template_sha, provider_name):
        rel = Path("raw") / received_at.strftime("%Y-%m") / f"{result.raw_sha256}.json.gz"
        path = self.base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".part-")
            with os.fdopen(fd, "wb") as f:
                f.write(gzip.compress(result.raw, mtime=0))
            os.replace(tmp, path)
        meta = {"job_id": job.job_id, "kind": job.kind, "request_hash": req.request_hash(), "provider": provider_name,
                "model_requested": req.model, "model_reported": result.model, "response_id": result.response_id,
                "template_id": templates.TEMPLATES[job.kind].template_id, "template_sha256": template_sha,
                "schema_version": evidence.SCHEMA_VERSION, "schema_sha256": evidence.SCHEMA_SHA256,
                "raw_sha256": result.raw_sha256, "path": rel.as_posix(), "usage": result.usage,
                "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
                "latency_seconds": round(result.latency_seconds, 3),
                "search_result_urls": sorted(result.retrieved_urls)}
        self.store.append("research_response", "provider:" + provider_name, job.job_id, meta, received_at=received_at)
        return meta

    def lookup(self, request_hash: str):
        for (payload,) in self.store.db.execute("SELECT payload FROM observations WHERE kind='research_response'"):
            meta = json.loads(payload)
            if meta.get("request_hash") == request_hash:
                return gzip.decompress((self.base / meta["path"]).read_bytes())
        return None

    def save_facts(self, job, assessment, response_meta, response_received_at, completed_at):
        for status, facts in (("ACCEPTED", assessment.accepted), ("CANDIDATE", assessment.candidates)):
            for f in facts:
                self.store.append("research_fact", "research:" + job.kind, job.entity["isin"], {
                    "status": status, "fact": f, "job_id": job.job_id, "response_id": response_meta["response_id"],
                    "raw_sha256": response_meta["raw_sha256"], "response_received_at": response_received_at,
                    "extraction_completed_at": completed_at}, received_at=completed_at)
        for c in assessment.contradictions:
            self.store.append("research_contradiction", "research:" + job.kind, job.entity["isin"], {
                "contradiction": c, "job_id": job.job_id, "raw_sha256": response_meta["raw_sha256"],
                "extraction_completed_at": completed_at}, received_at=completed_at)

    def facts_as_of(self, isin: str, decision_time) -> list:
        """Facts this system had validated by ``decision_time`` (never later results)."""
        return [r["payload"] for r in self.store.as_of("research_fact", isin, decision_time)]

    def close(self):
        self.store.close()


def guard_private(text: str, private_values) -> None:
    low = text.lower()
    if any(m in low for m in PRIVATE_MARKERS):
        raise ValueError("Prompt contains a private marker; refusing to send")
    for v in private_values:
        if v and len(v) >= 6 and v in text:
            raise ValueError("Prompt contains a private credential or identifier; refusing to send")


def market_hours(at: datetime) -> bool:
    local = timestamp(at)
    return local.weekday() < 5 and clock(9, 0) <= local.time() < clock(15, 30)


def build_request(job: ResearchJob, model=DEFAULT_MODEL) -> tuple[ProviderRequest, str]:
    policy = KINDS[job.kind]
    instructions, text = templates.render(job)
    lim = policy.limits
    domains = [d for v in job.allowed.values() for d in v]
    search = {"search_type": lim.search_type, "max_results": lim.max_results, "max_tokens": lim.search_max_tokens,
              "max_tokens_per_page": min(lim.search_max_tokens, 2000),
              "filters": {"search_domain_filter": domains,
                          "search_after_date_filter": timestamp(job.window_start).strftime("%m/%d/%Y"),
                          "search_before_date_filter": (timestamp(job.window_end) + timedelta(days=1)).strftime("%m/%d/%Y")}}
    req = ProviderRequest(model=model, instructions=instructions, input=text, max_output_tokens=lim.max_output_tokens,
                          max_steps=lim.max_steps, web_search=search, response_schema=evidence.SCHEMA)
    return req, templates.TEMPLATES[job.kind].sha256


def run_one(queue: Queue, provider, ledger: Ledger, archive: Archive, *, private_values=(), at=None,
            sleep=time.sleep, max_attempts=3, model=DEFAULT_MODEL) -> dict:
    """Process at most one job. Returns an outcome summary (no provider text)."""
    at = timestamp(at or now())
    for job in queue.pending(at):
        if KINDS[job.kind].off_hours_only and market_hours(at):
            continue
        return _run_job(queue, provider, ledger, archive, job, private_values, at, sleep, max_attempts, model)
    return {"result": "IDLE"}


def _run_job(queue, provider, ledger, archive, job, private_values, at, sleep, max_attempts, model):
    req, template_sha = build_request(job, model)
    try:
        guard_private(req.instructions + "\n" + req.input, private_values)
    except ValueError:
        queue.event(job.job_id, "FAILED", at, error="PRIVATE_DATA_BLOCKED")
        return {"result": "FAILED", "job_id": job.job_id, "error": "PRIVATE_DATA_BLOCKED"}
    reserve = worst_case_usd(model, KINDS[job.kind].limits)
    try:
        rid = ledger.reserve(job.job_id, job.kind, reserve, at)
    except BudgetExceeded as e:
        until = (at + timedelta(hours=1)) if e.label in ("DAILY_CAP", "DAILY_COUNT") else job.expiry()
        queue.event(job.job_id, "DEFERRED", at, reason=e.label, until=until.isoformat())
        return {"result": "DEFERRED", "job_id": job.job_id, "reason": e.label}
    queue.event(job.job_id, "RUNNING", at, reserved_usd=str(reserve))
    attempt = 0
    while True:
        attempt += 1
        try:
            result = provider.run(req, timeout=KINDS[job.kind].limits.timeout_seconds)
            break
        except ProviderError as e:
            if e.label == "RATE_LIMITED":
                ledger.release(rid, "HTTP 429 (not billed)")
            else:
                billed = e.result.cost_usd if e.result is not None else None
                ledger.settle(rid, billed, detail={"error": e.label})
            retry = e.label in ("RATE_LIMITED", "OVERLOADED") and attempt < max_attempts \
                and now() + timedelta(seconds=e.retry_after or 2 ** attempt) < job.expiry()
            if not retry:
                queue.event(job.job_id, "FAILED", now(), error=e.label, attempts=attempt)
                return {"result": "FAILED", "job_id": job.job_id, "error": e.label}
            sleep(min(e.retry_after or 2 ** attempt, 30))
            try:
                rid = ledger.reserve(job.job_id, job.kind, reserve, now())
            except BudgetExceeded as b:
                queue.event(job.job_id, "DEFERRED", now(), reason=b.label, until=job.expiry().isoformat())
                return {"result": "DEFERRED", "job_id": job.job_id, "reason": b.label}
    received = now()
    charged = ledger.settle(rid, result.cost_usd, received, {"response_id": result.response_id})
    meta = archive.save_response(job, req, result, received, template_sha, getattr(provider, "name", "provider"))
    assessment = evidence.assess(result.parsed, job_id=job.job_id, isin=job.entity["isin"], allowed=job.allowed,
                                 result=result, known_facts=job.known_facts, received_at=received)
    completed = now()
    if assessment.ok:
        archive.save_facts(job, assessment, meta, received.isoformat(), completed.isoformat())
    summary = {"accepted": len(assessment.accepted), "candidates": len(assessment.candidates),
               "rejected": len(assessment.rejected), "contradictions": len(assessment.contradictions),
               "unknown_fields": assessment.unknown_fields, "errors": assessment.errors[:5],
               "cost_usd": str(charged), "reserved_usd": str(reserve), "raw_sha256": result.raw_sha256}
    queue.event(job.job_id, "DONE" if assessment.ok else "FAILED", completed,
                **({"error": "VALIDATION"} if not assessment.ok else {}), **summary)
    return {"result": "DONE" if assessment.ok else "FAILED_VALIDATION", "job_id": job.job_id, **summary}


def new_job(kind, entity, window_start, window_end, allowed, **kw) -> ResearchJob:
    return ResearchJob(job_id=f"{kind[:3]}-{uuid.uuid4().hex[:12]}", kind=kind, entity=entity,
                       window_start=timestamp(window_start), window_end=timestamp(window_end), allowed=allowed, **kw)
