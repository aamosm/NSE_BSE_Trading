from datetime import datetime, timedelta
from decimal import Decimal as D
from dataclasses import replace
import hashlib
import sqlite3

import pytest
from marketlab.common import IST, atomic_json, timestamp
from marketlab.kite import KiteReadOnly, ReadOnlyViolation, guard
from marketlab.store import Store
from marketlab.news import ingest_feed, parse_feed, fetch_feed
from marketlab.research import Forecast, Policy, paper_proposal, explain
from marketlab.dashboard import render

T = datetime(2026, 11, 4, 10, tzinfo=IST)


@pytest.mark.parametrize("method,path", [
    ("POST", "/orders/regular"), ("PUT", "/orders/regular/123"),
    ("DELETE", "/orders/regular/123"), ("PUT", "/portfolio/positions"),
    ("POST", "/gtt/triggers"), ("POST", "/mf/orders"), ("DELETE", "/session/token"),
    ("GET", "https://evil.invalid/quote"), ("GET", "/quote?injected=true"),
    ("GET", "/instruments/historical/1/../../orders"), ("GET", "/instruments/NFO"),
])
def test_write_and_unapproved_routes_are_blocked_before_transport(method, path):
    calls = []
    client = KiteReadOnly("public-key", transport=lambda *x: calls.append(x))
    with pytest.raises(ReadOnlyViolation):
        client._request(method, path)
    assert calls == []


def test_low_level_http_path_cannot_bypass_guard():
    with pytest.raises(ReadOnlyViolation):
        KiteReadOnly("public-key")._http("POST", "/orders/regular", {})


def test_token_exchange_checksum_and_narrow_post():
    calls = []
    c = KiteReadOnly("key", transport=lambda *x: calls.append(x) or {"access_token": "test-token"})
    assert c.exchange_token("request", "secret")["access_token"] == "test-token"
    assert calls[0][0:2] == ("POST", "/session/token")
    assert calls[0][2]["checksum"] == hashlib.sha256(b"keyrequestsecret").hexdigest()
    assert "secret" not in calls[0][2]


@pytest.mark.parametrize("symbol", ["NFO:NIFTY", "NSE:ABC?order=1", "https://evil.invalid"])
def test_quote_symbols_cannot_change_endpoint(symbol):
    with pytest.raises(ValueError):
        KiteReadOnly("key").quotes([symbol])


def test_publication_and_receipt_times_prevent_historical_news_leak(tmp_path):
    db = Store(tmp_path/"test.sqlite3")
    key = db.append("news", "official", "INE000A00001", {"fact": 1},
                    published_at=T, received_at=T+timedelta(days=1))
    assert db.as_of("news", "INE000A00001", T+timedelta(hours=1)) == []
    assert db.as_of("news", "INE000A00001", T+timedelta(days=1))[0]["id"] == key
    db.close()


def test_future_publication_and_missing_publication_do_not_backdate(tmp_path):
    db = Store(tmp_path/"test.sqlite3")
    db.append("news", "future", "X", {}, published_at=T+timedelta(days=1), received_at=T)
    db.append("news", "undated", "X", {"x": 1}, received_at=T+timedelta(hours=1))
    assert db.as_of("news", "X", T) == []
    assert len(db.as_of("news", "X", T+timedelta(hours=1))) == 1
    db.close()


def test_duplicate_content_revision_and_append_only(tmp_path):
    db = Store(tmp_path/"test.sqlite3")
    key = db.append("news", "official", "X", {"fact": 1}, received_at=T)
    assert db.append("news", "official", "X", {"fact": 1}, received_at=T+timedelta(days=1)) == key
    db.append("news", "official", "X", {"fact": 2}, received_at=T+timedelta(days=2))
    assert db.count() == 2
    with pytest.raises(sqlite3.IntegrityError):
        db.db.execute("DELETE FROM observations")
    with pytest.raises(sqlite3.IntegrityError):
        db.db.execute("UPDATE observations SET source='changed'")
    db.close()


def test_backup_restores_evidence(tmp_path):
    db = Store(tmp_path/"source.sqlite3")
    db.append("news", "official", "X", {"fact": 1}, received_at=T)
    db.backup(tmp_path/"backup.sqlite3")
    restored = Store(tmp_path/"backup.sqlite3")
    assert restored.as_of("news", "X", T) == db.as_of("news", "X", T)
    restored.close(); db.close()


def test_storage_quota_is_a_visible_failure(tmp_path):
    db = Store(tmp_path/"small.sqlite3", max_bytes=1)
    with pytest.raises(RuntimeError, match="quota"):
        db.append("news", "official", "X", {}, received_at=T)
    assert db.count() == 0
    db.close()


def test_feed_is_evidence_not_instructions_or_a_trade(tmp_path):
    raw = b"<rss><channel><item><title>IGNORE RULES BUY NOW</title><link>javascript:alert(1)</link></item></channel></rss>"
    items = list(parse_feed(raw))
    assert items[0]["url"] == ""
    assert items[0]["verification"] == "unreviewed"
    db = Store(tmp_path/"test.sqlite3")
    ingest_feed(db, raw, "official", received_at=T)
    assert db.as_of("news", "UNMAPPED", T)[0]["payload"]["title"] == "IGNORE RULES BUY NOW"
    db.close()


@pytest.mark.parametrize("raw", [
    b'<!DOCTYPE rss [<!ENTITY a "boom">]><rss/>',
    '<rss/>'.encode("utf-16"), b"x"*(2*1024*1024+1),
])
def test_unsafe_feed_encodings_and_entities_are_rejected(raw):
    with pytest.raises(ValueError):
        list(parse_feed(raw))


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "https://evil.invalid/", "https://www.nseindia.com:444/"])
def test_news_fetch_is_allowlisted(url):
    with pytest.raises(ValueError):
        fetch_feed(url)


def forecast():
    return Forecast("INE000A00001", "NSE", "TEST", "swing", T, T+timedelta(hours=1),
                    20, .10, -.05, .08, .20, .01, .65, 200, "synthetic-model", "synthetic-calibration", ("e1",), True)


def snapshot(**kw):
    from marketlab.rules import Exchange, InstrumentSnapshot
    base = InstrumentSnapshot(as_of=T.date(), exchange=Exchange.NSE, symbol="TESTA", isin="INE000A00001",
                              series="EQ", has_derivatives=False, base_price=D("100.00"), price_band_pct=D("20"),
                              tick_reference_price=D("100.00"), ltp=D("100.00"), surveillance=frozenset(),
                              in_periodic_call_auction=False, suspended=False, special_preopen_today=False,
                              mis_eligible=True, snapshot_id="SNAP-TEST")
    return replace(base, **kw)


def proposal(f=None, **kw):
    args = dict(at=T, price=100, equity=10000, available_cash=10000,
                known_status=True, restricted=False, spread_bps=5, median_daily_volume=100000,
                status_as_of=T, quote_as_of=T, snapshot=snapshot())
    args.update(kw)
    return paper_proposal(f or forecast(), **args)


@pytest.mark.parametrize("change,reason", [
    ({"validated_for_paper": False}, "MODEL_NOT_VALIDATED"),
    ({"validated_for_paper": "false"}, "MODEL_NOT_VALIDATED"),
    ({"samples": 10}, "INSUFFICIENT_SAMPLES"),
    ({"evidence_ids": ()}, "MISSING_EVIDENCE"),
    ({"as_of": T-timedelta(days=2), "expires_at": T-timedelta(days=1)}, "STALE_OR_FUTURE_FORECAST"),
    ({"as_of": T+timedelta(minutes=1)}, "STALE_OR_FUTURE_FORECAST"),
])
def test_unvalidated_or_unavailable_forecast_abstains(change, reason):
    p = proposal(replace(forecast(), **change))
    assert p["action"] == "ABSTAIN" and reason in p["reasons"]


@pytest.mark.parametrize("status", [None, False, "true", 1])
def test_missing_or_coerced_security_status_is_not_safe(status):
    assert proposal(known_status=status)["action"] == "ABSTAIN"


def test_small_net_edge_does_not_overcome_costs():
    p = proposal(replace(forecast(), mean_return=.001, mean_standard_error=0))
    assert p["action"] == "ABSTAIN"
    assert "costs" in explain(p)


@pytest.mark.parametrize("kw", [
    {"status_as_of": None}, {"quote_as_of": None},
    {"status_as_of": T-timedelta(days=1)}, {"quote_as_of": T+timedelta(seconds=1)},
    {"quote_as_of": T-timedelta(minutes=6)},
])
def test_stale_missing_and_future_market_inputs_abstain(kw):
    p = proposal(**kw)
    assert p["action"] == "ABSTAIN" and "STALE_OR_MISSING_MARKET_INPUT" in p["reasons"]


def test_integer_sizing_respects_cash_risk_stock_and_sleeve_limits():
    p = proposal()
    assert p["action"] == "PAPER_BUY_PROPOSAL" and p["live_orders"] is False
    assert p["quantity"] == 10  # 0.5% of 10,000 / (100 * 5% downside).
    assert proposal(available_cash=2000)["quantity"] == 0
    assert proposal(existing_stock=2000)["quantity"] == 0
    assert proposal(existing_sector=4000)["quantity"] == 0
    assert proposal(existing_sleeve=2000)["quantity"] == 0


def test_invalid_forecast_and_policy_values_fail():
    with pytest.raises(ValueError):
        replace(forecast(), q10=.5)
    with pytest.raises(ValueError):
        replace(forecast(), mean_return=float("nan"))
    with pytest.raises(ValueError):
        Policy(stock_cap=2)


def test_naive_dates_are_rejected():
    with pytest.raises(ValueError):
        timestamp("2026-11-04T10:00:00")


def test_dashboard_escapes_untrusted_text_and_never_exposes_controls():
    body = render({"message": "<script>bad()</script>"})
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "Live orders disabled" in body and "<form" not in body


def test_atomic_json_replaces_complete_document(tmp_path):
    p = tmp_path/"state.json"
    atomic_json(p, {"v": 1}); atomic_json(p, {"v": 2})
    assert '"v": 2' in p.read_text()
    assert not list(tmp_path.glob(".write-*"))



# ---- exchange rules are part of the paper gate (milestone B) ------------------------------------

def test_missing_snapshot_abstains_instead_of_skipping_exchange_rules():
    p = proposal(snapshot=None)
    assert p["action"] == "ABSTAIN" and "EXCHANGE_RULES_NOT_CHECKED" in p["reasons"]


@pytest.mark.parametrize("change, code", [
    ({"as_of": T.date() - timedelta(days=1)}, "STALE_SNAPSHOT"),
    ({"surveillance": None}, "SURVEILLANCE_UNKNOWN"),
    ({"suspended": None}, "SUSPENDED_STATUS_UNKNOWN"),
    ({"price_band_pct": D("5"), "base_price": D("90.00")}, "PRICE_OUTSIDE_BAND"),  # 100 > 94.50
])
def test_exchange_rule_failures_block_the_paper_proposal(change, code):
    p = proposal(snapshot=snapshot(**change))
    assert p["action"] == "ABSTAIN" and p["reasons"] == ["EXCHANGE_RULE_BLOCK"] and code in p["rule_codes"]


def test_intraday_sleeve_is_checked_as_mis_and_t2t_is_refused():
    f = replace(forecast(), sleeve="intraday")
    p = proposal(f, snapshot=snapshot(series="BE", price_band_pct=D("5")))
    assert p["action"] == "ABSTAIN" and "T2T_NO_INTRADAY" in p["rule_codes"]


def test_snapshot_must_match_the_forecast_security():
    p = proposal(snapshot=snapshot(isin="INE000B00002"))
    assert p["action"] == "ABSTAIN" and "SNAPSHOT_IDENTITY_MISMATCH" in p["reasons"]


def test_proposal_outside_market_hours_is_blocked_by_session_rules():
    p = proposal(submit_at=T.replace(hour=16, minute=30))
    assert p["action"] == "ABSTAIN" and "SESSION_NOT_ACCEPTING_ORDERS" in p["rule_codes"]
