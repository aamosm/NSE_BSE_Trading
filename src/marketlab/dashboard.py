from __future__ import annotations
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .common import now, timestamp


def render(state):
    esc = lambda x: html.escape(str(x))
    data = state.get("collection", {})
    last = data.get("last_success_at")
    age = int((now()-timestamp(last)).total_seconds()) if last else None
    fresh = "No broker data collected" if age is None else f"Last collection: {max(0, age)} seconds ago"
    rows = ""
    for name, run in state.get("report", {}).get("comparison", {}).items():
        rows += ("<tr><td>"+esc(name)+"</td><td>₹"+esc(run["net_pnl_after_fixed_cost"])+"</td><td>"
                 +esc(len(run["trades"]))+"</td><td>"+esc(round(run["max_drawdown_before_fixed_cost"]*100, 2))+"%</td></tr>")
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30">
<title>MarketLab — research only</title><style>
body{font:16px system-ui;background:#101820;color:#edf2f4;margin:auto;max-width:960px;padding:24px}
article{background:#1d2b35;padding:22px;border-radius:14px;margin:16px 0}
h1{font-size:30px}h2{font-size:20px}p{line-height:1.6}.tag{color:#85e0b4}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px 4px;border-bottom:1px solid #415160}
small{color:#afbdc8}code{overflow-wrap:anywhere}</style>
<h1>MarketLab</h1><p class="tag">Research and observation • Live orders disabled • No borrowing</p>
<article><h2>What the system is doing</h2><p>""" + esc(state.get("message", "Waiting for data. No trading decision has been made.")) + """</p>
<p>""" + esc(fresh) + """</p><small>""" + esc(data.get("status", "NOT_CONNECTED")) + """</small></article>
<article><h2>Forecasting readiness</h2><p>No validated forecasting model is installed. News is recorded as evidence;
headlines do not trigger trades. Price extremes are uncertain.</p></article>
<article><h2>Diagnostic results</h2><p>These baselines test the research machinery. They are not proof of a profitable strategy.</p>
<table><tr><th>Baseline</th><th>Net P&amp;L</th><th>Fills</th><th>Drawdown</th></tr>""" + rows + """</table></article>
<article><h2>Next required work</h2><p>Verify data and corporate actions, implement and calibrate candidate models,
run untouched-period comparisons, then observe paper decisions prospectively.</p></article>
<small>Read-only page. Never share this service publicly; use a private tunnel.</small></html>"""


def serve(state_path: Path, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path not in {"/", "/health"}:
                self.send_error(404)
                return
            if self.path == "/health":
                body, content = b'{"service":"up","live_orders":false}', "application/json"
            else:
                try:
                    state = json.loads(state_path.read_text()) if state_path.exists() else {}
                except (ValueError, OSError):
                    state = {"message": "Status file unavailable. No trading is enabled."}
                body, content = render(state).encode(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
