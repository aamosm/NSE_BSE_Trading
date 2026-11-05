"""The dashboard's JavaScript executed in Node against real API responses (a synthetic panel and ranking served by
the actual handler): every renderer runs without a runtime error, opening a stock renders its full card, and no raw
undefined/NaN/[object Object] reaches the page. Skipped when Node is not installed."""
import json
import shutil
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from marketlab import webapp, webassets
from marketlab.quant import allocate, evaluate, ranking
from marketlab.quant.universe import ScreenPolicy
from synthetic import WeekdayCalendar, make_panel

NODE = shutil.which("node")
STUB = Path(__file__).parent / "js" / "dom_stub.js"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_every_view_renders_against_real_api_responses(tmp_path, monkeypatch):
    market, root = tmp_path / "market", tmp_path / "private"
    market.mkdir()
    root.mkdir()
    p = make_panel(market / "panel.sqlite3", n=420, n_stocks=20, bonus_at=10_000)
    cfg = evaluate.Config(h=20, train_sessions=200, screen=ScreenPolicy(v_min=1, W=10_000), policy=allocate.Policy.for_capital(10_000))
    ranking.build(p, cfg, root=root, calendar=WeekdayCalendar(), bootstrap=10)
    p.close()
    monkeypatch.setattr(webapp, "RUNS", None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.make_handler(webapp.App(root, market)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=60) as r:
            return json.loads(r.read())
    try:
        stocks = get("/api/stocks")
        s = next(x for x in stocks["stocks"] if x["mu_shrunk"] is not None)
        fixtures = {path: get(path) for path in ("/api/stocks", "/api/how", "/api/status", "/api/config", "/api/requests",
                                                 "/api/ai/status", "/api/decision", "/api/evaluation", "/api/data")}
        fixtures["/api/stock"] = get("/api/stock?isin=" + s["isin"])
        fixtures["/api/ai/estimate"] = get("/api/ai/estimate?isin=" + s["isin"])
        fixtures["__isin_symbol"] = s["symbol"]
        restated = get("/api/stocks?capital=30000")  # the restated branch: other capital, no refit
        assert restated["ranking"]["restated"]["capital"] == 30000.0
    finally:
        srv.shutdown()
        srv.server_close()
    (tmp_path / "app.js").write_text(webassets.APP_JS, encoding="utf-8")
    for name, fx in (("fx.json", fixtures), ("fx_restated.json", fixtures | {"/api/stocks": restated})):
        (tmp_path / name).write_text(json.dumps(fx), encoding="utf-8")
        out = subprocess.run([NODE, str(STUB), str(tmp_path / "app.js"), str(tmp_path / name)], capture_output=True, text=True,
                             timeout=120, encoding="utf-8")
        report = out.stdout + out.stderr
        assert out.returncode == 0, report
        for view in ("stocks", "stock_sheet", "how", "overview", "controls", "decision", "evaluation", "data"):
            assert f"RENDER_OK {view} " in report, report
