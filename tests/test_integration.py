from datetime import datetime, timedelta
import csv
import io
import json
import gzip
import pytest

from marketlab import cli, kite
from marketlab.common import IST, atomic_json, now
from marketlab.kite import KiteReadOnly, KiteError, AuthenticationRequired
from marketlab.store import Store


class FakeKite:
    def get(self, path):
        if path.startswith("/instruments/"):
            return "instrument_token,tradingsymbol,exchange,instrument_type\n123,TEST,NSE,EQ\n"
        if path == "/portfolio/holdings":
            return [{"isin": "INE000A00001", "quantity": 2}]
        return [] if path == "/trades" else {"snapshot": "synthetic"}

    def quotes(self, symbols):
        return {s: {"last_price": 100} for s in symbols}

    def history(self, token, interval, start, end):
        return {"candles": [[f"2025-01-0{i}T00:00:00+0530", 100, 101, 99, 100, 100000] for i in range(1,5)]}


def test_mock_collection_records_reads_without_exposing_account_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "client", lambda root: FakeKite())
    cli.collect_once(tmp_path, ["NSE:TEST"], instruments=True)
    db = Store(tmp_path/"evidence.sqlite3")
    assert db.count() == 7
    status = json.loads((tmp_path/"status.json").read_text())
    assert status["live_orders"] is False
    assert "INE000A00001" not in (tmp_path/"status.json").read_text()
    assert status["collection"]["last_success_at"]
    db.close()


def test_failed_collection_does_not_refresh_last_success(tmp_path):
    old = now()-timedelta(hours=1)
    cli.state_write(tmp_path, collection={"status":"COLLECTED", "last_success_at": old})
    cli.state_write(tmp_path, collection={"status":"AuthenticationRequired", "attempt_at": now()})
    assert json.loads((tmp_path/"status.json").read_text())["collection"]["last_success_at"] == str(old)


def test_history_exports_hash_and_explicit_unverified_data_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "client", lambda root: FakeKite())
    output = tmp_path/"prices.csv"
    cli.historical(tmp_path,123,"day","2025-01-01T00:00:00+05:30","2025-01-05T00:00:00+05:30",
                   output,"NSE","TEST","INE000A00001")
    rows = list(csv.DictReader(output.open()))
    assert len(rows) == 4 and "23:59:59" in rows[0]["available_at"]
    meta = json.loads(output.with_suffix(".metadata.json").read_text())
    assert meta["corporate_actions_verified"] is False and meta["sha256"]
    with pytest.raises(ValueError, match="Output exists"):
        cli.historical(tmp_path,123,"day","2025-01-01T00:00:00+05:30","2025-01-05T00:00:00+05:30",
                       output,"NSE","TEST","INE000A00001")


def test_wrong_instrument_identity_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "client", lambda root: FakeKite())
    with pytest.raises(ValueError, match="unique"):
        cli.historical(tmp_path,999,"day","2025-01-01T00:00:00+05:30","2025-01-05T00:00:00+05:30",
                       tmp_path/"prices.csv","NSE","TEST","INE000A00001")
    assert not (tmp_path/"prices.csv").exists()


def test_expired_session_does_not_make_network_request(tmp_path):
    atomic_json(tmp_path/"kite_session.json", {"api_key":"test","access_token":"test",
                "expires_at": now()-timedelta(seconds=1)})
    with pytest.raises(AuthenticationRequired):
        cli.client(tmp_path)


def test_gzipped_instrument_response_is_supported(monkeypatch):
    class Response(io.BytesIO):
        headers = {"Content-Encoding":"gzip"}
    class Opener:
        def open(self, *a, **kw):
            return Response(gzip.compress(b"instrument_token,tradingsymbol\n1,TEST\n"))
    monkeypatch.setattr(kite, "build_opener", lambda *a: Opener())
    monkeypatch.setattr(kite.time, "sleep", lambda _: None)
    raw = KiteReadOnly("test-key","test-token").get("/instruments/NSE")
    assert raw.startswith("instrument_token")


def test_identical_content_preserves_each_receipt(tmp_path):
    db = Store(tmp_path/"test.sqlite3")
    t = now()
    a = db.append("quotes","kite","TEST",{"price":100},received_at=t)
    b = db.append("quotes","kite","TEST",{"price":100},received_at=t+timedelta(minutes=5))
    assert a == b and db.count() == 1
    assert db.db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 2
    db.close()
