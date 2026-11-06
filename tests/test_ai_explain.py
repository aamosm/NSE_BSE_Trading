"""AI commentary: worst-case reservation before every call, settlement from reported tokens at verified prices,
caps that refuse, the key never leaving the process except to the provider, a context without account data, numbers
that are not on the card flagged, and the HTTP flow (key, settings, caps, ask, poll). A stand-in client replaces the
SDK; no network call is made."""
import json
import threading
import time
import urllib.request
from decimal import Decimal
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from marketlab import ai_explain, login, webapp
from marketlab.quant import allocate, evaluate, ranking
from marketlab.quant.universe import ScreenPolicy
from marketlab.researcher import budget
from synthetic import WeekdayCalendar, make_panel

KEY = "sk-ant-api03-" + "x" * 40


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeClient:
    def __init__(self, msg=None, error=None):
        self.calls, self.msg, self.error = [], msg, error
        outer = self

        class M:
            def stream(self, **kw):
                outer.calls.append(kw)
                if outer.error:
                    raise outer.error
                return FakeStream(outer.msg)
        self.messages = M()
        self.beta = SimpleNamespace(messages=M())


def message(text, *, model="claude-opus-5-5", out=900, inp=1200, cw=8000, cr=0, stop="end_turn", iterations=None):
    usage = {"input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}
    if iterations is not None:
        usage["iterations"] = iterations
    return {"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}], "stop_reason": stop,
            "model": model, "usage": usage}


@pytest.fixture(scope="module")
def ranked(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ai")
    market = tmp / "market"
    market.mkdir()
    p = make_panel(market / "panel.sqlite3", n=420, n_stocks=20, bonus_at=10_000)
    root = tmp / "private"
    root.mkdir()
    cfg = evaluate.Config(h=20, train_sessions=200, screen=ScreenPolicy(v_min=1, W=10_000), policy=allocate.Policy.for_capital(10_000))
    r = ranking.build(p, cfg, root=root, calendar=WeekdayCalendar(), bootstrap=10)
    p.close()
    return root, market, ranking.load(root)


def fresh(tmp_path, ranked):
    root, market, r = ranked
    new_root = tmp_path / "private"
    new_root.mkdir()
    (new_root / ".env").write_text("KITE_API_KEY=pub\nKITE_USER_ID=AB1234\n", encoding="utf-8")
    return new_root, tmp_path / "market", r


def stock(r):
    return next(s for s in r["stocks"] if "forecast" in s)


def test_prices_are_verified_and_the_worst_case_covers_any_outcome(ranked):
    assert set(ai_explain.MODELS) <= set(budget.CLAUDE_PRICES) and budget.PRICE_SOURCE["verified_on"] == "2026-11-05"
    usd, known = budget.token_cost_usd("claude-opus-5-5", input_tokens=1_000_000, output_tokens=1_000_000,
                                       cache_write_tokens=1_000_000, cache_read_tokens=1_000_000)
    assert known and usd == Decimal("4") + Decimal("20") + Decimal("5") + Decimal("0.20")
    assert budget.token_cost_usd("someone/unknown", input_tokens=1_000_000, output_tokens=0)[0] == Decimal("10")  # ceiling
    _, _, r = ranked
    from marketlab import explain
    s = stock(r)
    system, user = ai_explain.system_prompt(), ai_explain.build_context(explain.stock_view(s, r), r)
    worst = ai_explain.reservation_usd("claude-opus-5-5", system, user, 6000, True)
    sys_t, usr_t = len(system) / 3.0, len(user) / 3.0
    actual_max, _ = budget.token_cost_usd("claude-opus-5-5", input_tokens=int(usr_t), output_tokens=6000, cache_write_tokens=int(sys_t))
    assert worst > actual_max * 2 * Decimal("0.99")  # a full fallback attempt is reserved too
    assert ai_explain.reservation_usd("claude-haiku-5-5", system, user, 6000, True) < Decimal("0.02")  # no fallback on Haiku
    # Gemini: the dearest model in the fallback chain, verified list prices, a second attempt when fallback is on
    g1 = ai_explain.reservation_usd("gemini-3.8-flash", system, user, 6000, False, ai_explain.GEMINI_PROVIDER)
    g2 = ai_explain.reservation_usd("gemini-3.8-flash", system, user, 6000, True, ai_explain.GEMINI_PROVIDER)
    top, _ = budget.token_cost_usd("gemini-3.8-flash", input_tokens=int(sys_t + usr_t), output_tokens=6000)
    assert g1 >= top * Decimal("0.99") and g2 >= 2 * top * Decimal("0.99") and g2 < Decimal("0.10")
    assert budget.GEMINI_PRICE_SOURCE["verified_on"] == "2026-11-06" and "aistudio.google.com" in budget.GEMINI_PRICE_SOURCE["url"]


def test_gemini_ask_falls_back_when_busy_and_settles_at_the_answering_models_price(tmp_path, ranked):
    from marketlab import gemini
    root, market, r = fresh(tmp_path, ranked)
    ai_explain.save_key(root, "AQ.Ab8RN6-test-auth-key-format-0123456789abcdef", ai_explain.GEMINI_PROVIDER)
    ai_explain.save_caps(root, {"daily_usd": "2", "monthly_usd": "8", "per_ask_usd": "1"})
    seen = []

    def transport(method, url, headers, body):
        model = url.split("/models/")[1].split(":")[0]
        seen.append((model, headers.get("x-goog-api-key", "")[:3]))
        if model == "gemini-3.8-flash":
            return 503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "high demand"}}
        return 200, {"candidates": [{"content": {"parts": [{"text": "## Summary\nGemini explanation",
                                                             "thoughtSignature": "abc"},
                                                            {"text": "hidden reasoning", "thought": True}]},
                                     "finishReason": "STOP"}],
                     "usageMetadata": {"promptTokenCount": 9000, "candidatesTokenCount": 1500, "thoughtsTokenCount": 500},
                     "modelVersion": model}

    rec = ai_explain.ask(root, market, r, stock(r)["isin"], session_key=None,
                         client_factory=lambda key: gemini.Client(key, transport=transport, sleep=lambda s: None))
    assert [m for m, _ in seen] == ["gemini-3.8-flash", "gemini-3.5-flash-lite"] and seen[0][1] == "AQ."
    assert rec["state"] == "DONE" and rec["answer"] == "## Summary\nGemini explanation"  # thought parts excluded
    assert rec["model_requested"] == "gemini-3.8-flash" and rec["model_served"] == "gemini-3.5-flash-lite"
    assert rec["provider"] == "gemini" and rec["usage"][0]["output_tokens"] == 2000  # thinking billed as output
    want, known = budget.token_cost_usd("gemini-3.5-flash-lite", input_tokens=9000, output_tokens=2000)
    assert known and Decimal(rec["cost_usd"]) == want and "free tier" in rec["cost_basis"]
    assert "AQ." not in json.dumps(rec)  # the key is never stored with an answer
    led = budget.Ledger(ai_explain._ledger_path(market), budget.Policy.load(root / ai_explain.POLICY_FILE))
    assert led.spent()["open_reservations"] == 0
    led.close()


def test_gemini_failure_releases_or_charges_and_explains(tmp_path, ranked):
    from marketlab import gemini
    root, market, r = fresh(tmp_path, ranked)
    ai_explain.save_key(root, "AQ.Ab8RN6-test-auth-key-format-0123456789abcdef", ai_explain.GEMINI_PROVIDER)
    ai_explain.save_caps(root, {"daily_usd": "2", "monthly_usd": "8", "per_ask_usd": "1"})
    busy = lambda m, u, h, b: (503, {"error": {"status": "UNAVAILABLE", "message": "high demand"}})  # noqa: E731
    with pytest.raises(ai_explain.AIError) as e:
        ai_explain.ask(root, market, r, stock(r)["isin"],
                       client_factory=lambda k: gemini.Client(k, transport=busy, sleep=lambda s: None))
    assert e.value.label == "UNAVAILABLE" and "Lite" in e.value.detail
    led = budget.Ledger(ai_explain._ledger_path(market), budget.Policy.load(root / ai_explain.POLICY_FILE))
    assert led.spent()["day"] == 0 and led.spent()["open_reservations"] == 0  # every model busy: nothing billed
    led.close()
    bad_key = lambda m, u, h, b: (400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid",  # noqa: E731
                                                  "details": [{"reason": "API_KEY_INVALID"}]}})
    with pytest.raises(ai_explain.AIError) as e:
        ai_explain.ask(root, market, r, stock(r)["isin"],
                       client_factory=lambda k: gemini.Client(k, transport=bad_key, sleep=lambda s: None))
    assert e.value.label == "AUTH"
    hist = ai_explain.history(root)
    assert {h["error"] for h in hist} == {"UNAVAILABLE", "AUTH"} and all(h["cost_usd"] == "0" for h in hist)
    assert len(next(h for h in hist if h["error"] == "UNAVAILABLE")["attempts"]) == 3  # 3.8 -> 3.5 lite -> 3.1 lite


def test_context_is_the_card_and_never_account_data_or_secrets(tmp_path, ranked):
    root, market, r = fresh(tmp_path, ranked)
    (root / ".env").write_text("KITE_API_KEY=zz-kite-public-key-77\nKITE_USER_ID=AB1234\n", encoding="utf-8")
    ai_explain.save_key(root, KEY)
    from marketlab import explain
    s = stock(r)
    ctx = ai_explain.build_context(explain.stock_view(s, r), r) + ai_explain.system_prompt()
    assert s["symbol"] in ctx and explain.pct(s["forecast"]["mu_shrunk"], 3) in ctx
    for value in login.load_env(root).values():  # nothing from the private env file reaches the model
        assert value not in ctx
    assert "Every number you state must be copied from the card" in ctx


def test_ask_reserves_then_settles_actual_tokens_and_stores_labelled_commentary(tmp_path, ranked):
    root, market, r = fresh(tmp_path, ranked)
    ai_explain.save_caps(root, {"daily_usd": "2", "monthly_usd": "8", "per_ask_usd": "1"})
    s = stock(r)
    fc = s["forecast"]["mu_shrunk"]
    text = f"## Summary\nThe shrunk forecast is {100 * fc:+.2f}% and the model says 37.5% something."
    fake = FakeClient(message(text))
    rec = ai_explain.ask(root, market, r, s["isin"], preset="explain", session_key=KEY, client_factory=lambda k: fake)
    assert rec["state"] == "DONE" and rec["answer"] == text and rec["kind"] == "AI_COMMENTARY"
    assert "37.5%" in rec["unsourced_numbers"] and f"{100 * fc:+.2f}%" not in rec["unsourced_numbers"]
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["thinking"] == {"type": "adaptive"} and call["fallbacks"] == "default"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"} and "betas" in call
    expected, _ = budget.token_cost_usd("claude-opus-5-5", input_tokens=1200, output_tokens=900, cache_write_tokens=8000)
    assert Decimal(rec["cost_usd"]) == expected
    stored = (root.parent / "runs" / "ai" / f"{rec['id']}.json").read_text(encoding="utf-8")
    assert KEY not in stored and json.loads(stored)["key_source"] == "SESSION"
    st = ai_explain.status(root, market, KEY)
    assert Decimal(st["spent"]["day_usd"]) == expected and st["spent"]["open_reservations"] == 0
    assert KEY not in json.dumps(st)


def test_fallback_attempts_are_each_priced_by_their_own_model(tmp_path, ranked):
    root, market, r = fresh(tmp_path, ranked)
    ai_explain.save_caps(root, {"daily_usd": "2", "monthly_usd": "8", "per_ask_usd": "1"})
    its = [{"type": "message", "model": "claude-opus-5-5", "input_tokens": 9000, "output_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
           {"type": "fallback_message", "model": "claude-opus-5", "input_tokens": 9000, "output_tokens": 800, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}]
    msg = message("ok", model="claude-opus-5", iterations=its)
    msg["content"].insert(0, {"type": "fallback", "from_": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-5"}})
    rec = ai_explain.ask(root, market, r, stock(r)["isin"], session_key=KEY, client_factory=lambda k: FakeClient(msg))
    a = budget.token_cost_usd("claude-opus-5-5", input_tokens=9000, output_tokens=10)[0]
    b = budget.token_cost_usd("claude-opus-5", input_tokens=9000, output_tokens=800)[0]
    assert Decimal(rec["cost_usd"]) == a + b and rec["fallback_switches"] == [{"from": "claude-opus-5-5", "to": "claude-opus-5"}]


def test_caps_refuse_before_any_call_and_errors_release_or_charge(tmp_path, ranked):
    root, market, r = fresh(tmp_path, ranked)
    fake = FakeClient(message("x"))
    ai_explain.save_caps(root, {"daily_usd": "0.05", "monthly_usd": "5"})
    with pytest.raises(ai_explain.AIError) as e:
        ai_explain.ask(root, market, r, stock(r)["isin"], session_key=KEY, client_factory=lambda k: fake)
    assert e.value.label.startswith("BUDGET_") and fake.calls == []  # nothing was sent
    with pytest.raises(ValueError):
        ai_explain.save_caps(root, {"monthly_usd": "50"})  # above the hard ceiling
    ai_explain.save_caps(root, {"daily_usd": "2", "monthly_usd": "8", "per_ask_usd": "1"})

    class AuthenticationError(Exception):
        status_code = 401

    class APIConnectionError(Exception):
        pass
    with pytest.raises(ai_explain.AIError, match="AUTH"):
        ai_explain.ask(root, market, r, stock(r)["isin"], session_key=KEY, client_factory=lambda k: FakeClient(error=AuthenticationError()))
    assert Decimal(ai_explain.status(root, market, KEY)["spent"]["day_usd"]) == 0  # a 401 is not billed: released
    with pytest.raises(ai_explain.AIError, match="CONNECTION"):
        ai_explain.ask(root, market, r, stock(r)["isin"], session_key=KEY, client_factory=lambda k: FakeClient(error=APIConnectionError()))
    assert Decimal(ai_explain.status(root, market, KEY)["spent"]["day_usd"]) > 0  # may have been processed: charged in full
    with pytest.raises(ai_explain.AIError, match="NO_KEY"):
        ai_explain.ask(root, market, r, stock(r)["isin"], session_key=None, client_factory=lambda k: fake)


def test_settings_are_bounded_and_a_saved_key_lives_only_in_the_env_file(tmp_path, ranked):
    root, market, r = fresh(tmp_path, ranked)
    for bad in ({"model": "gpt-x"}, {"effort": "max"}, {"max_tokens": 100}, {"fallback": "yes"}, {"temperature": 1}):
        with pytest.raises(ValueError):
            ai_explain.save_settings(root, bad)
    assert ai_explain.save_settings(root, {"model": "claude-haiku-5-5", "max_tokens": 4000})["model"] == "claude-haiku-5-5"
    with pytest.raises(ValueError):
        ai_explain.save_key(root, "not a key")
    ai_explain.save_key(root, KEY)
    env = login.load_env(root)  # still passes the allow-list; Kite lines kept
    assert env["RESEARCH_PROVIDER"] == "anthropic" and env["RESEARCH_PROVIDER_KEY"] == KEY and env["KITE_USER_ID"] == "AB1234"
    assert ai_explain.resolve_key(root, None) == (KEY, "ENV_FILE")
    ai_explain.clear_saved_key(root)
    assert "RESEARCH_PROVIDER_KEY" not in login.load_env(root) and ai_explain.resolve_key(root, None) == (None, None)


def test_number_check_ignores_counts_years_and_rounding():
    ctx = "forecast +1.234% cost 1.03% close ₹4,993.20 beta +0.0181"
    assert ai_explain.unsourced_numbers("about +1.23% and 1.0%; ₹4,993.2; 3 steps in 2026; β 0.0181", ctx) == []
    assert ai_explain.unsourced_numbers("a target of ₹6,500 and 12.7%", ctx) == ["₹6,500", "12.7%"]


def test_http_flow_never_echoes_the_key(tmp_path, ranked, monkeypatch):
    root0, market0, r = ranked
    root, market = tmp_path / "private", market0
    root.mkdir()
    import shutil
    shutil.copytree(root0.parent / "runs", tmp_path / "runs")
    monkeypatch.setattr(webapp, "RUNS", None)
    app = webapp.App(root, market)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    fake = FakeClient(message("## Summary\nfine"))
    monkeypatch.setattr(ai_explain, "_default_client", lambda key: fake)

    def call(path, body=None):
        req = urllib.request.Request(base + path, method="POST" if body is not None else "GET",
                                     headers={"X-MarketLab-Action": "1", "Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, resp.read().decode()
        except HTTPError as e:
            return e.code, e.read().decode()
    try:
        code, body = call("/api/stocks")
        rows = json.loads(body)["stocks"]
        isin = next(x["isin"] for x in rows if x["mu_shrunk"] is not None)
        assert code == 200 and json.loads(call("/api/stock?isin=" + isin)[1])["card"]["isin"] == isin
        assert json.loads(call("/api/ai/ask", {"isin": isin})[1])["error"] == "NO_KEY"
        code, body = call("/api/ai/key", {"key": KEY})
        assert code == 200 and KEY not in body and json.loads(body)["key"] == {"set": True, "source": "SESSION"}
        assert not (root / ".env").exists()  # session key: memory only
        call("/api/ai/caps", {"daily_usd": "2", "monthly_usd": "8", "per_ask_usd": "1"})
        est = json.loads(call("/api/ai/estimate?isin=" + isin)[1])
        assert Decimal(est["reserve_usd"]) > Decimal(est["typical_usd_first"]) > 0
        jid = json.loads(call("/api/ai/ask", {"isin": isin, "preset": "maths"})[1])["id"]
        app.ai_jobs.wait(jid, 20)
        job = json.loads(call("/api/ai/job?id=" + jid)[1])
        assert job["state"] == "DONE" and job["record"]["answer"].startswith("## Summary") and KEY not in json.dumps(job)
        hist = json.loads(call("/api/stock?isin=" + isin)[1])["ai_history"]
        assert hist and hist[0]["id"] == jid
        for path in ("/api/ai/status", "/api/status", "/api/how", "/api/stocks"):
            assert KEY not in call(path)[1]
        assert call("/api/ai/key", {"clear": True})[0] == 200 and app.ai_key is None
    finally:
        srv.shutdown()
        srv.server_close()
