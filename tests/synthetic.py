"""Synthetic panels for mechanics tests (not market evidence). Deterministic for a given seed, so a panel of
n sessions is a prefix of the same panel with more sessions."""
from __future__ import annotations

import math
import random
from datetime import date, time, timedelta

from marketlab.quant.panel import Panel

START = date(2020, 1, 1)


class WeekdayCalendar:
    """Every weekday is a session, except ``holidays`` (synthetic data only)."""

    def __init__(self, holidays=()):
        self.holidays = set(holidays)

    def covers(self, exchange, d):
        return True

    def is_trading_day(self, exchange, d):
        return d.weekday() < 5 and d not in self.holidays

    def is_special_session(self, exchange, d):
        return False

    def session_open(self, exchange, d):
        return time(9, 0) if self.is_trading_day(exchange, d) else None

    def previous_trading_day(self, exchange, d):
        d -= timedelta(days=1)
        while not self.is_trading_day(exchange, d):
            d -= timedelta(days=1)
        return d

    def next_trading_day(self, exchange, d):
        d += timedelta(days=1)
        while not self.is_trading_day(exchange, d):
            d += timedelta(days=1)
        return d


def sessions(n, start=START, holidays=()):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def row(isin, sym, o, h, l, c, pc, vol, val, series="EQ", name="X LIMITED"):
    return {"ISIN": isin, "TckrSymb": sym, "SctySrs": series, "FinInstrmNm": name, "OpnPric": o, "HghPric": h, "LwPric": l,
            "ClsPric": c, "PrvsClsgPric": pc, "TtlTradgVol": vol, "TtlTrfVal": val, "TtlNbOfTxsExctd": 10}


def index_csv(d, level, open_level=None):
    o = level if open_level is None else open_level
    return ("Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,"
            "Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
            f"Nifty 50,{d:%d-%m-%Y},{o:.2f},{max(o, level):.2f},{min(o, level):.2f},{level:.2f},0,0,1,1,20,3,1.2\n").encode()


def isin(i):
    return f"INE{i:03d}A01001"


def make_panel(path, n=900, n_stocks=30, seed=7, bonus_at=600, drop=None, mutate=None, skip_days=()):
    """Geometric random walks with a slowly varying drift (momentum is informative) and a 1:1 bonus for stock 0
    on session ``bonus_at``. ``drop(t, i)`` -> True omits stock i on session t (suspension); ``mutate(t, i, r)``
    may edit a row dict; sessions whose index is in ``skip_days`` are not stored (a data gap)."""
    p = Panel(path)
    days = sessions(n)
    rng = random.Random(seed)
    price = [100.0 * (1 + i / 10) for i in range(n_stocks)]
    drift = [0.0] * n_stocks
    idx_level = 10000.0
    for t, d in enumerate(days):
        rows = []
        mkt = rng.gauss(0, 0.008)
        idx_open = idx_level * math.exp(rng.gauss(0, 0.001))
        for i in range(n_stocks):
            drift[i] = 0.9 * drift[i] + rng.gauss(0, 0.0005)
            r = mkt + drift[i] + rng.gauss(0, 0.015)
            pc = price[i]
            if t == bonus_at and i == 0:
                pc = price[i] / 2
                price[i] = price[i] / 2
            c = price[i] * math.exp(r)
            o = pc * math.exp(rng.gauss(0, 0.003))
            h, l = max(o, c) * math.exp(abs(rng.gauss(0, 0.004))), min(o, c) * math.exp(-abs(rng.gauss(0, 0.004)))
            vol = 200000 + (i % 3) * 100000
            rec = row(isin(i), f"S{i}", o, h, l, c, pc, vol, vol * c)
            if mutate:
                mutate(t, i, rec)
            price[i] = c
            if drop and drop(t, i):
                continue
            rows.append(rec)
        idx_level *= math.exp(mkt)
        if t in skip_days:
            continue
        p.add_session(d, rows)
        p.add_index_file(d, index_csv(d, idx_level, idx_open))
    p.compute_implied_factors(WeekdayCalendar())
    return p
