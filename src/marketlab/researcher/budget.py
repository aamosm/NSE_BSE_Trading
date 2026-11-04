"""Software-enforced runtime spending limits for research providers (USD).

A sentence in a prompt is not a budget. Every provider call must first *reserve* its worst-case cost
in this append-only ledger; the call is refused if the reservation would exceed the job's cap, the
day's cap or the month's cap. After the call the reservation is settled with the provider-reported
cost (``usage.cost.total_cost``), or with the full reserved amount when the cost is unknown
(timeouts, malformed responses). A 429 is released (Perplexity documents that 429s are not billed).
A settled cost above its reservation records an OVERRUN and suspends that job kind until reviewed.

Days and months are IST calendar periods.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from ..common import now, timestamp

D = Decimal
# USD per 1M tokens (input, output). Empty by design: a provider is enabled only after its price is verified
# against the provider's published list and recorded here with the source and date (spec: no invented capabilities).
MODEL_PRICES: dict[str, tuple[Decimal, Decimal]] = {}
# USD per tool invocation, likewise recorded with their source when a provider is enabled.
TOOL_PRICES: dict[str, Decimal] = {"web_search": D("0.0025"), "web_search_fast": D("0.001")}
HARD_MONTHLY_CEILING = D("10.00")  # owner's stated range is $5-10/month; config can never exceed this


class BudgetExceeded(RuntimeError):
    """The reservation would break a cap. ``label`` is one of JOB_CAP, DAILY_CAP, MONTHLY_CAP, KIND_SUSPENDED."""

    def __init__(self, label, detail=""):
        super().__init__(f"{label}: {detail}" if detail else label)
        self.label = label


@dataclass(frozen=True, slots=True)
class Limits:
    max_output_tokens: int
    max_steps: int
    prompt_tokens: int  # upper bound for our rendered instructions + input + provider overhead
    search_max_tokens: int  # web_search max_tokens: search context per invocation
    max_results: int
    search_type: str = "fast"  # "fast" ($0.001) or "web" ($0.0025)
    timeout_seconds: int = 120

    def __post_init__(self):
        if min(self.max_output_tokens, self.max_steps, self.prompt_tokens, self.search_max_tokens, self.max_results) < 1:
            raise ValueError("Limits must be positive")
        if self.search_type not in ("fast", "web") or self.max_steps > 20 or self.max_results > 50:
            raise ValueError("Unsupported search type or limits beyond the research policy")


def worst_case_usd(model: str, limits: Limits, prices: dict | None = None) -> Decimal:
    """Pre-call reservation: an upper bound, not an estimate.

    Assumes at most one tool call per step (the provider documents "max steps 40 (at most 40 tool calls)"
    for its high preset), that each step can emit ``max_output_tokens``, and that each step re-reads the
    prompt plus all search context and output produced so far (quadratic in steps). fetch_url is not
    offered by default because fetched page size is not bounded by a documented parameter.
    """
    prices = MODEL_PRICES if prices is None else prices
    if model not in prices:
        raise ValueError(f"No verified price for {model}; add it with its source before use")
    p_in, p_out = prices[model]
    s = limits.max_steps
    added_per_step = limits.search_max_tokens + limits.max_output_tokens
    input_tokens = s * limits.prompt_tokens + added_per_step * s * (s + 1) // 2
    output_tokens = s * limits.max_output_tokens
    tool = TOOL_PRICES["web_search_fast" if limits.search_type == "fast" else "web_search"]
    usd = D(input_tokens) * p_in / 1_000_000 + D(output_tokens) * p_out / 1_000_000 + tool * s
    return usd.quantize(D("0.0001"), rounding=ROUND_CEILING)


@dataclass(frozen=True, slots=True)
class Policy:
    monthly_usd: Decimal = D("5.00")
    daily_usd: Decimal = D("0.50")
    per_job_usd: dict = field(default_factory=lambda: {
        "overnight_update": D("0.03"), "upcoming_event_verification": D("0.03"),
        "material_event_investigation": D("0.05"), "contradiction_resolution": D("0.05"),
        "bounded_company_research": D("0.25"), "smoke": D("0.02"), "search": D("0.005")})
    per_kind_daily_count: dict = field(default_factory=lambda: {
        "overnight_update": 20, "upcoming_event_verification": 20, "material_event_investigation": 10,
        "contradiction_resolution": 10, "bounded_company_research": 2, "smoke": 5, "search": 40})

    def __post_init__(self):
        if not (D("0") <= self.daily_usd <= self.monthly_usd <= HARD_MONTHLY_CEILING):
            raise ValueError(f"Budget must satisfy 0 <= daily <= monthly <= {HARD_MONTHLY_CEILING}")

    @classmethod
    def load(cls, path: Path | None) -> "Policy":
        """Optional owner overrides (``research_policy.json``); the hard ceiling still applies."""
        if not path or not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        base = cls()
        return cls(monthly_usd=D(str(raw.get("monthly_usd", base.monthly_usd))),
                   daily_usd=D(str(raw.get("daily_usd", base.daily_usd))),
                   per_job_usd={**base.per_job_usd, **{k: D(str(v)) for k, v in raw.get("per_job_usd", {}).items()}},
                   per_kind_daily_count={**base.per_kind_daily_count, **raw.get("per_kind_daily_count", {})})


class Ledger:
    """Append-only usage ledger. Spend = settled amounts + open reservations."""

    def __init__(self, path: Path, policy: Policy | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.policy = path, policy or Policy()
        self.db = sqlite3.connect(path, timeout=10)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS usage_events (
                event_id TEXT PRIMARY KEY, at TEXT NOT NULL, event TEXT NOT NULL, reservation_id TEXT NOT NULL,
                job_id TEXT NOT NULL, job_kind TEXT NOT NULL, amount_usd TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS usage_no_update BEFORE UPDATE ON usage_events
              BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS usage_no_delete BEFORE DELETE ON usage_events
              BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        """)

    def _add(self, event, reservation_id, job_id, job_kind, amount, at, detail=None):
        with self.db:
            self.db.execute("INSERT INTO usage_events VALUES (?,?,?,?,?,?,?,?)",
                            (uuid.uuid4().hex, timestamp(at).isoformat(timespec="microseconds"), event, reservation_id,
                             job_id, job_kind, str(amount), json.dumps(detail or {}, sort_keys=True, default=str)))

    def _rows(self):
        return [dict(zip(("at", "event", "reservation_id", "job_id", "job_kind", "amount", "detail"), r)) for r in
                self.db.execute("SELECT at, event, reservation_id, job_id, job_kind, amount_usd, detail FROM usage_events")]

    def spent(self, at: datetime | None = None) -> dict:
        at = timestamp(at) if at else now()
        rows = self._rows()
        closed = {r["reservation_id"] for r in rows if r["event"] in ("SETTLE", "RELEASE")}
        out = {"day": D("0"), "month": D("0"), "open_reservations": 0, "day_count": {}}
        for r in rows:
            t = timestamp(r["at"])
            counts = r["event"] == "SETTLE" or (r["event"] == "RESERVE" and r["reservation_id"] not in closed)
            if not counts:
                continue
            amount = D(r["amount"])
            if r["event"] == "RESERVE":
                out["open_reservations"] += 1
            if (t.year, t.month) == (at.year, at.month):
                out["month"] += amount
                if t.date() == at.date():
                    out["day"] += amount
            if r["event"] == "RESERVE" and t.date() == at.date():
                out["day_count"][r["job_kind"]] = out["day_count"].get(r["job_kind"], 0) + 1
        return out

    def suspended(self, job_kind: str) -> bool:
        state = False
        for r in sorted(self._rows(), key=lambda r: r["at"]):
            if r["job_kind"] == job_kind and r["event"] == "OVERRUN":
                state = True
            elif r["job_kind"] == job_kind and r["event"] == "RESUME":
                state = False
        return state

    def reserve(self, job_id: str, job_kind: str, amount: Decimal, at=None) -> str:
        at = timestamp(at) if at else now()
        if self.suspended(job_kind):
            raise BudgetExceeded("KIND_SUSPENDED", f"{job_kind} overran a reservation; review before resuming")
        cap = self.policy.per_job_usd.get(job_kind)
        if cap is None or amount > cap:
            raise BudgetExceeded("JOB_CAP", f"{job_kind} worst case {amount} exceeds cap {cap}")
        s = self.spent(at)
        if s["day_count"].get(job_kind, 0) >= self.policy.per_kind_daily_count.get(job_kind, 0):
            raise BudgetExceeded("DAILY_COUNT", f"{job_kind} daily job count reached")
        if s["day"] + amount > self.policy.daily_usd:
            raise BudgetExceeded("DAILY_CAP", f"{s['day']} + {amount} > {self.policy.daily_usd}")
        if s["month"] + amount > self.policy.monthly_usd:
            raise BudgetExceeded("MONTHLY_CAP", f"{s['month']} + {amount} > {self.policy.monthly_usd}")
        rid = uuid.uuid4().hex
        self._add("RESERVE", rid, job_id, job_kind, amount, at)
        return rid

    def _reservation(self, reservation_id):
        for r in self._rows():
            if r["reservation_id"] == reservation_id and r["event"] == "RESERVE":
                return r
        raise KeyError("Unknown reservation")

    def settle(self, reservation_id: str, actual_usd: Decimal | None, at=None, detail=None) -> Decimal:
        r = self._reservation(reservation_id)
        reserved = D(r["amount"])
        charged = reserved if actual_usd is None else D(str(actual_usd))
        self._add("SETTLE", reservation_id, r["job_id"], r["job_kind"], charged, at or now(),
                  {"reserved": str(reserved), "provider_reported": actual_usd is not None, **(detail or {})})
        if charged > reserved:
            self._add("OVERRUN", reservation_id, r["job_id"], r["job_kind"], charged - reserved, at or now())
        return charged

    def release(self, reservation_id: str, reason: str, at=None):
        r = self._reservation(reservation_id)
        self._add("RELEASE", reservation_id, r["job_id"], r["job_kind"], D("0"), at or now(), {"reason": reason})

    def resume(self, job_kind: str, note: str, at=None):
        self._add("RESUME", uuid.uuid4().hex, "-", job_kind, D("0"), at or now(), {"note": note})

    def close(self):
        self.db.close()
