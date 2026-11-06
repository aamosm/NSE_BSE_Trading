"""Bulk Kite candle download: newest-first chunks that stop at the listing date, write-once hashed files, resume
from the manifest, a clean stop on an expired session, and 429 back-off. Offline: a fake client stands in."""
import json
from datetime import date

from marketlab import kite_history as kh
from marketlab.kite import AuthenticationRequired, KiteError

DUMP = ("instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,"
        "instrument_type,segment,exchange\n"
        "256265,1001,NIFTY 50,,0,,0,0,0,EQ,INDICES,NSE\n"
        "1,1,OLDCO,Old Co,0,,0,0.05,1,EQ,NSE,NSE\n"
        "2,2,NEWCO,New Co,0,,0,0.05,1,EQ,NSE,NSE\n"
        "3,3,NIFTY24DECFUT,,0,2024-12-26,0,0.05,25,FUT,NFO-FUT,NFO\n"
        "4,4,SMECO-SM,Sme Co,0,,0,0.05,1200,EQ,NSE,NSE\n"
        "5,5,MAHSDL29-SG,,0,,0,0.01,1,EQ,NSE,NSE\n"
        "6,6,ABCFIN-N1,,0,,0,0.01,1,EQ,NSE,NSE\n"
        "7,7,BAJAJ-AUTO,Bajaj Auto,0,,0,0.5,1,EQ,NSE,NSE\n"
        "8,8,EMBASSY-RR,Embassy Reit,0,,0,0.01,1,EQ,NSE,NSE\n")


class Fake:
    def __init__(self, listed: dict, fail_after=None, rate_limit_once=False):
        self.listed, self.calls, self.fail_after, self.rl = listed, [], fail_after, rate_limit_once

    def get(self, path, params=None):
        return DUMP

    def history(self, token, interval, start, end):
        self.calls.append((token, start[:10], end[:10]))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise AuthenticationRequired("expired")
        if self.rl:
            self.rl = False
            raise KiteError("Kite HTTP 429; no automatic retry")
        lo, hi = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
        first = self.listed.get(token, date(1990, 1, 1))
        if hi < first:
            return {"candles": []}
        return {"candles": [[f"{max(lo, first).isoformat()}T00:00:00+0530", 1, 1, 1, 1, 10]]}


def test_selects_cash_equities_and_indices_only():
    chosen = kh.select(kh.parse_instruments(DUMP))
    # indices first, then EQ (a hyphen in a company symbol is not a series), then SME; no futures, debt or REITs
    assert [i.symbol for i in chosen] == ["NIFTY 50", "BAJAJ-AUTO", "NEWCO", "OLDCO", "SMECO-SM"]
    assert next(i for i in chosen if i.symbol == "SMECO-SM").lot_size == 1200  # SME lots are kept for affordability


def test_chunks_are_newest_first_contiguous_and_bounded():
    cs = kh.chunks(date(2026, 11, 6), date(2015, 1, 1))
    assert cs[0][1] == date(2026, 11, 6) and cs[-1][0] == date(2015, 1, 1)
    for (lo, hi), (lo2, hi2) in zip(cs, cs[1:]):
        assert hi2 == lo.replace() - __import__("datetime").timedelta(days=1)
    assert all((hi - lo).days + 1 <= kh.CHUNK_DAYS for lo, hi in cs)


def test_young_stock_costs_one_request_and_resume_repeats_nothing(tmp_path):
    fake = Fake({2: date(2026, 3, 1), 1: date(2001, 1, 1), 256265: date(1995, 1, 1), 4: date(2025, 9, 1)})
    out = kh.download(fake, tmp_path, today=date(2026, 11, 6), sleep=lambda s: None)
    assert out["stopped"] == "COMPLETE" and out["instruments"] == 5
    per = {}
    for t, _, _ in fake.calls:
        per[t] = per.get(t, 0) + 1
    assert per[2] == 2 and per[4] == 2  # newest chunk has candles, the next is empty -> stop
    assert per[1] == len(kh.chunks(date(2026, 11, 6)))  # an old stock walks back to the earliest date
    man = [json.loads(x) for x in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert all(len(r["sha256"]) == 64 for r in man)
    again = Fake(fake.listed)
    out2 = kh.download(again, tmp_path, today=date(2026, 11, 6), sleep=lambda s: None)
    assert again.calls == [] and out2["requests"] == 0 and out2["chunks_skipped"] == len(man)
    body = json.loads(next((tmp_path / "day" / "2").glob("*.json")).read_text())
    assert body["adjustment_basis"] == "PROVIDER_AS_OF_RETRIEVAL" and "not traded prices" in body["warning"]


def test_expired_session_stops_cleanly_and_resume_continues(tmp_path):
    fake = Fake({}, fail_after=3)
    out = kh.download(fake, tmp_path, today=date(2026, 11, 6), sleep=lambda s: None)
    assert out["stopped"] == "SESSION_EXPIRED" and out["requests"] == 3
    rest = Fake({})
    out2 = kh.download(rest, tmp_path, today=date(2026, 11, 6), sleep=lambda s: None)
    assert out2["stopped"] == "COMPLETE" and out2["chunks_skipped"] == 3
    assert (rest.calls[0][0], rest.calls[0][2]) != (fake.calls[0][0], fake.calls[0][2])  # no chunk fetched twice


def test_rate_limit_backs_off_and_retries(tmp_path):
    waits = []
    fake = Fake({1: date(2026, 10, 1), 2: date(2026, 10, 1), 4: date(2026, 10, 1), 7: date(2026, 10, 1),
                 256265: date(2026, 10, 1)},
                rate_limit_once=True)
    out = kh.download(fake, tmp_path, today=date(2026, 11, 6), sleep=waits.append)
    assert waits == [30] and out["stopped"] == "COMPLETE" and not out["errors"]
