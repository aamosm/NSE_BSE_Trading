"""Snapshot chronology (review of 3513d33, finding 1): latest receipt, batches, unknown is not zero."""
import sqlite3
from datetime import datetime
from decimal import Decimal

from marketlab import account
from marketlab.common import IST
from marketlab.store import Store

SUBJ = account.SUBJECT


def at(d, h, m=0):
    return datetime(2026, 11, d, h, m, tzinfo=IST)


def batch(db, when, batch_id, unavailable=None, **kinds):
    for kind, payload in kinds.items():
        db.append(kind, "kite:test", SUBJ, payload, received_at=when, batch_id=batch_id)
    db.append("collection_batch", "marketlab", SUBJ,
              {"batch_id": batch_id, "status": "COLLECTED_PARTIAL" if unavailable else "COLLECTED",
               "unavailable": unavailable or {}}, received_at=when, batch_id=batch_id)


HOLD_A = [{"tradingsymbol": "AAA", "exchange": "NSE", "quantity": 1, "t1_quantity": 0,
           "average_price": 10, "last_price": 11}]
HOLD_B = [{"tradingsymbol": "BBB", "exchange": "NSE", "quantity": 2, "t1_quantity": 0,
           "average_price": 20, "last_price": 19}]
FUNDS = {"net": 100, "available": {"cash": 100}, "utilised": {"debits": 0}}


def test_a_b_a_the_second_a_is_current_even_though_its_bytes_were_stored_first(tmp_path):
    db = Store(tmp_path / "e.sqlite3")
    batch(db, at(4, 10), "b1", holdings=HOLD_A)
    batch(db, at(4, 11), "b2", holdings=HOLD_B)
    batch(db, at(4, 12), "b3", holdings=HOLD_A)
    cur = db.latest("holdings", SUBJ, at(4, 13))
    assert cur["payload"] == HOLD_A and cur["batch_id"] == "b3"
    assert cur["received_at"].startswith("2026-11-04T12:00") and cur["first_received_at"].startswith("2026-11-04T10:00")
    # Before the third receipt, B was current.
    assert db.latest("holdings", SUBJ, at(4, 11, 30))["payload"] == HOLD_B
    # Point-in-time research view keeps first-known times: A (10:00) then B (11:00), stored once each.
    assert [r["payload"] for r in db.as_of("holdings", SUBJ, at(4, 13))] == [HOLD_A, HOLD_B]
    assert len(db.receipts(cur["id"])) == 2
    view = account.account_view(db, at(4, 13))
    assert view["sections"]["holdings"]["rows"][0]["symbol"] == "AAA"
    db.close()


def test_a_kind_missing_from_the_newest_batch_is_unavailable_not_the_older_snapshot(tmp_path):
    db = Store(tmp_path / "e.sqlite3")
    batch(db, at(4, 10), "b1", holdings=HOLD_A, funds=FUNDS)
    batch(db, at(4, 11), "b2", unavailable={"funds": "PERMISSION_DENIED"}, holdings=HOLD_B)
    view = account.account_view(db, at(4, 12))
    assert view["sections"]["funds"] == {"state": "UNAVAILABLE"}
    assert view["sections"]["holdings"]["rows"][0]["symbol"] == "BBB"
    assert "unavailable in the latest batch" in account.summary_text(view)
    db.close()


def test_an_incomplete_batch_is_ignored(tmp_path):
    db = Store(tmp_path / "e.sqlite3")
    batch(db, at(4, 10), "b1", holdings=HOLD_A)
    db.append("holdings", "kite:test", SUBJ, HOLD_B, received_at=at(4, 11), batch_id="crashed")  # no batch record
    assert account.account_view(db, at(4, 12))["sections"]["holdings"]["rows"][0]["symbol"] == "AAA"
    db.close()


def test_a_new_no_trade_day_does_not_show_yesterdays_trades_as_today(tmp_path):
    db = Store(tmp_path / "e.sqlite3")
    trades = [{"tradingsymbol": "AAA", "transaction_type": "BUY", "product": "CNC", "quantity": 1, "average_price": 10}]
    batch(db, at(4, 10), "wed", trades=trades, holdings=HOLD_A)
    thursday_morning = account.account_view(db, at(5, 10))
    t = thursday_morning["sections"]["trades"]
    assert t["state"] == "STALE" and t["session_date"] == "2026-11-04"
    assert thursday_morning["sections"]["holdings"]["state"] == "STALE"
    text = account.summary_text(thursday_morning)
    assert "No trade snapshot for today yet" in text and "Today's executed trades" not in text
    batch(db, at(5, 10, 5), "thu", trades=[], holdings=HOLD_A)
    t = account.account_view(db, at(5, 10, 10))["sections"]["trades"]
    assert t["state"] == "OK" and t["fills"] == 0 and t["session_date"] == "2026-11-05"
    db.close()


def test_identical_empty_trade_books_on_two_days_use_the_latest_receipt(tmp_path):
    db = Store(tmp_path / "e.sqlite3")
    batch(db, at(4, 10), "wed", trades=[])
    batch(db, at(5, 10), "thu", trades=[])  # same bytes; stored once, received twice
    t = account.account_view(db, at(5, 11))["sections"]["trades"]
    assert t["state"] == "OK" and t["session_date"] == "2026-11-05"
    db.close()


def test_trade_book_received_before_the_session_opens_has_no_known_day(tmp_path):
    db = Store(tmp_path / "e.sqlite3")
    batch(db, at(5, 0, 30), "night", trades=[{"tradingsymbol": "AAA", "quantity": 1, "average_price": 1}])
    t = account.account_view(db, at(5, 0, 40))["sections"]["trades"]
    assert t["state"] == "SESSION_UNKNOWN" and t["session_date"] is None
    db.close()


def test_missing_or_unparseable_numbers_are_unknown_not_zero(tmp_path):
    db = Store(tmp_path / "e.sqlite3")
    rows = [{"tradingsymbol": "AAA", "quantity": 3, "t1_quantity": 0, "average_price": 10, "last_price": None},
            {"tradingsymbol": "BBB", "quantity": "x", "t1_quantity": 0, "average_price": 5, "last_price": 6}]
    batch(db, at(4, 10), "b1", holdings=rows, funds={"net": "NaN", "available": {}, "utilised": {}})
    view = account.account_view(db, at(4, 11))
    h = view["sections"]["holdings"]
    assert h["rows"][0]["invested"] == Decimal("30.00") and h["rows"][0]["value"] is None
    assert h["rows"][1]["quantity"] is None
    assert h["totals"] == {"invested": None, "value": None, "pnl": None}
    assert view["sections"]["funds"]["net"] is None and view["sections"]["funds"]["cash"] is None
    text = account.summary_text(view)
    assert "current unknown" in text and "net unknown, cash unknown" in text
    db.close()


def test_malformed_payload_is_reported_not_parsed(tmp_path):
    db = Store(tmp_path / "e.sqlite3")
    batch(db, at(4, 10), "b1", holdings={"unexpected": "shape"}, positions=[1, 2])
    s = account.account_view(db, at(4, 11))["sections"]
    assert s["holdings"]["state"] == "MALFORMED" and s["positions"]["state"] == "MALFORMED"
    assert s["funds"] == {"state": "MISSING"}
    db.close()


def test_no_batch_means_every_section_is_missing():
    class Empty:
        def latest(self, *a, **k):
            return None
    view = account.account_view(Empty(), at(4, 11))
    assert all(v == {"state": "MISSING"} for v in view["sections"].values())
    assert "No completed broker collection" in account.summary_text(view)


def test_legacy_database_is_migrated_and_old_receipts_stay_readable(tmp_path):
    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE observations (id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,
            subject TEXT NOT NULL, published_at TEXT, received_at TEXT NOT NULL, available_at TEXT NOT NULL,
            payload TEXT NOT NULL);
        CREATE TABLE receipts (observation_id TEXT NOT NULL, received_at TEXT NOT NULL,
            PRIMARY KEY(observation_id, received_at));
        INSERT INTO observations VALUES ('x','holdings','kite','BROKER_ACCOUNT',NULL,
            '2026-11-04T10:00:00+05:30','2026-11-04T10:00:00+05:30','[]');
        INSERT INTO receipts VALUES ('x','2026-11-04T10:00:00+05:30');
    """)
    con.commit()
    con.close()
    db = Store(path)
    rec = db.latest("holdings", SUBJ, at(4, 11))
    assert rec["payload"] == [] and rec["batch_id"] is None
    # Legacy receipts have no batch, so the account view does not present them as a completed batch.
    assert account.account_view(db, at(4, 11))["batch"] is None
    db.close()
