"""Optional AI commentary on one stock's research card, through the Anthropic Messages API with the owner's own key.

What it may do: explain, in plain language and in detail, what MarketLab's numbers for one stock mean, how they
combine into the class, what would change it, and add general context the owner can check. What it may not do:
compute new numbers, see account data, or influence a decision. The answer is stored as labelled commentary
(runs/ai/<id>.json) and nothing in marketlab.quant ever reads it.

Guardrails (owner rules: no paid runtime LLM calls without a spending cap and a usage ledger; never an LLM for
arithmetic or dashboard wording; never send secrets or account identifiers to a model):
* every call first RESERVES its worst-case cost in the research usage ledger (researcher.budget): the system and
  card text at the cache-write price plus ``max_tokens`` of output, plus the same again at the fallback model's
  rates when server-side fallback is on; the call is refused if that would break the per-ask, daily or monthly cap
  (the monthly cap can never exceed the hard ceiling). After the call the reservation is settled with the cost
  computed from the reported tokens of every attempt (``usage.iterations``), at the verified prices;
* the key is held in this process's memory for the session, or saved to the private env file
  (RESEARCH_PROVIDER=anthropic, RESEARCH_PROVIDER_KEY); it is never returned by an endpoint, logged or stored with an
  answer;
* the context is the stock card, MarketLab's deterministic narrative and glossary: market data and model outputs
  only. The policy's capital is the owner's configured paper capital, not an account figure;
* numbers in the answer that do not appear in the card are listed next to it ("not from MarketLab").
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import uuid
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from . import decisions, explain, login
from .common import now
from .researcher import budget

SETTINGS_FILE = "ai_settings.json"
POLICY_FILE = "research_policy.json"
FOLDER = "ai"
JOB_KIND = "stock_explainer"
PROVIDER = "anthropic"
MODELS = {  # label, whether server-side fallback exists, the model assumed for a fallback's reservation
    "claude-opus-5-5": {"label": "Claude Opus 5.5 (default, most capable)", "fallback": True, "fallback_price": "claude-opus-5"},
    "claude-sonnet-5-5": {"label": "Claude Sonnet 5.5 (faster, cheaper)", "fallback": True, "fallback_price": "claude-sonnet-5"},
    "claude-haiku-5-5": {"label": "Claude Haiku 5.5 (cheapest)", "fallback": False, "fallback_price": None},
}
DEFAULTS = {"model": "claude-opus-5-5", "effort": "medium", "max_tokens": 6000, "fallback": True}
EFFORTS = ("low", "medium", "high")
MAX_TOKENS_RANGE = (2000, 16000)
CHARS_PER_TOKEN = 3.0  # conservative for English mixed with numbers (reservation only; billing uses reported tokens)
MAX_QUESTION = 1500
KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,300}$")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
PRESETS = {
    "explain": "Explain this stock's card in full: the call, the maths step by step with this stock's numbers, what the "
               "numbers mean together, what would change the call, general context, and what I should check myself.",
    "maths": "Walk me through the maths for this stock in detail, one step at a time: features and ranks, coefficients and "
             "contributions, the raw forecast, the bootstrap and shrinkage, the calibrated range, the costs, and the gates. "
             "Use this stock's numbers at every step and say what each number means.",
    "together": "What do these numbers mean together? Which ones support the call, which contradict it, and how strong is "
                "the evidence overall?",
    "risks": "What could go wrong with this call? Cover model risk, data caveats, costs, volatility and anything about this "
             "kind of company I should know.",
    "change": "What would have to change for the call to change? Be specific about which numbers and by how much (using "
              "the figures on the card).",
}
_LOCK = threading.Lock()


class AIError(RuntimeError):
    def __init__(self, label: str, detail: str = ""):
        super().__init__(label + (f": {detail}" if detail else ""))
        self.label, self.detail = label, detail


# ---- settings, caps and key ---------------------------------------------------------------------------------

def settings(root: Path) -> dict:
    p = root / SETTINGS_FILE
    saved = {}
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            saved = {}
    return DEFAULTS | {k: v for k, v in saved.items() if k in DEFAULTS}


def save_settings(root: Path, body: dict) -> dict:
    cur = settings(root)
    unknown = set(body) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown setting {sorted(unknown)[0]}")
    if "model" in body and body["model"] not in MODELS:
        raise ValueError(f"model must be one of {', '.join(MODELS)} (models with a verified price)")
    if "effort" in body and body["effort"] not in EFFORTS:
        raise ValueError(f"effort must be one of {', '.join(EFFORTS)}")
    if "max_tokens" in body:
        try:
            mt = int(body["max_tokens"])
        except (TypeError, ValueError):
            raise ValueError("max_tokens must be an integer") from None
        if not MAX_TOKENS_RANGE[0] <= mt <= MAX_TOKENS_RANGE[1]:
            raise ValueError(f"max_tokens must be in {MAX_TOKENS_RANGE[0]}-{MAX_TOKENS_RANGE[1]}")
        body = dict(body, max_tokens=mt)
    if "fallback" in body and not isinstance(body["fallback"], bool):
        raise ValueError("fallback must be true or false")
    new = cur | body
    (root / SETTINGS_FILE).write_text(json.dumps(new, indent=1, sort_keys=True), encoding="utf-8")
    return new


def caps(root: Path) -> dict:
    pol = budget.Policy.load(root / POLICY_FILE)
    return {"monthly_usd": str(pol.monthly_usd), "daily_usd": str(pol.daily_usd),
            "per_ask_usd": str(pol.per_job_usd.get(JOB_KIND)), "asks_per_day": pol.per_kind_daily_count.get(JOB_KIND),
            "hard_monthly_ceiling_usd": str(budget.HARD_MONTHLY_CEILING)}


def save_caps(root: Path, body: dict) -> dict:
    """monthly_usd, daily_usd, per_ask_usd, asks_per_day: validated by budget.Policy (daily <= monthly <= ceiling)."""
    p = root / POLICY_FILE
    raw = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    try:
        if "monthly_usd" in body:
            raw["monthly_usd"] = str(Decimal(str(body["monthly_usd"])))
        if "daily_usd" in body:
            raw["daily_usd"] = str(Decimal(str(body["daily_usd"])))
        if "per_ask_usd" in body:
            v = Decimal(str(body["per_ask_usd"]))
            if v <= 0:
                raise ValueError("per-ask cap must be positive")
            raw.setdefault("per_job_usd", {})[JOB_KIND] = str(v)
        if "asks_per_day" in body:
            n = int(body["asks_per_day"])
            if not 1 <= n <= 200:
                raise ValueError("asks per day must be 1-200")
            raw.setdefault("per_kind_daily_count", {})[JOB_KIND] = n
    except ArithmeticError:
        raise ValueError("caps must be numbers") from None
    tmp = root / (POLICY_FILE + ".check")
    tmp.write_text(json.dumps(raw), encoding="utf-8")
    try:
        budget.Policy.load(tmp)  # raises ValueError beyond the hard ceiling or with daily > monthly
    finally:
        tmp.unlink()
    p.write_text(json.dumps(raw, indent=1, sort_keys=True), encoding="utf-8")
    return caps(root)


def _env_lines(root: Path) -> list[str]:
    p = root / login.ENV_FILE
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def _write_env(root: Path, updates: dict[str, str | None]):
    """Set or remove allow-listed keys in the private env file, keeping every other line as it is."""
    for k in updates:
        if k not in login.ALLOWED_ENV:
            raise ValueError(f"{k} is not an allowed key")
    out, seen = [], set()
    for line in _env_lines(root):
        key = line.split("=", 1)[0].strip().upper() if "=" in line and not line.strip().startswith("#") else None
        if key in updates:
            seen.add(key)
            if updates[key] is not None:
                out.append(f"{key}={updates[key]}")
            continue
        out.append(line)
    for k, v in updates.items():
        if k not in seen and v is not None:
            out.append(f"{k}={v}")
    root.mkdir(parents=True, exist_ok=True)
    (root / login.ENV_FILE).write_text("\n".join(out) + "\n", encoding="utf-8")
    login.load_env(root)  # the file must still load (allow-list and forbidden-name checks)


def check_key_format(key: str) -> str:
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise ValueError("that does not look like an Anthropic API key (sk-ant-...)")
    return key


def save_key(root: Path, key: str):
    _write_env(root, {"RESEARCH_PROVIDER": PROVIDER, "RESEARCH_PROVIDER_KEY": check_key_format(key)})


def clear_saved_key(root: Path):
    env = login.load_env(root)
    if env.get("RESEARCH_PROVIDER", "").lower() == PROVIDER:
        _write_env(root, {"RESEARCH_PROVIDER": None, "RESEARCH_PROVIDER_KEY": None})


def resolve_key(root: Path, session_key: str | None) -> tuple[str | None, str | None]:
    """(key, source) with source SESSION (memory only) or ENV_FILE. Never returned to a client."""
    if session_key:
        return session_key, "SESSION"
    env = login.load_env(root)
    if env.get("RESEARCH_PROVIDER", "").lower() == PROVIDER and env.get("RESEARCH_PROVIDER_KEY"):
        return env["RESEARCH_PROVIDER_KEY"], "ENV_FILE"
    return None, None


def status(root: Path, market: Path, session_key: str | None) -> dict:
    _, source = resolve_key(root, session_key)
    import importlib.util
    sdk = importlib.util.find_spec("anthropic") is not None  # without importing it (slow on first import)
    led = budget.Ledger(_ledger_path(market), budget.Policy.load(root / POLICY_FILE))
    try:
        s = led.spent()
    finally:
        led.close()
    return {"key": {"set": source is not None, "source": source}, "sdk_installed": sdk, "settings": settings(root),
            "caps": caps(root), "spent": {"day_usd": str(s["day"]), "month_usd": str(s["month"]),
                                          "asks_today": s["day_count"].get(JOB_KIND, 0), "open_reservations": s["open_reservations"]},
            "models": {m: dict(v, price_per_mtok={"input": str(budget.CLAUDE_PRICES[m].input),
                                                   "output": str(budget.CLAUDE_PRICES[m].output),
                                                   "cache_read": str(budget.CLAUDE_PRICES[m].cache_read)})
                       for m, v in MODELS.items()},
            "price_source": budget.PRICE_SOURCE, "presets": PRESETS}


def _ledger_path(market: Path) -> Path:
    from .researcher import commands
    return commands.paths(market)["ledger"]


# ---- prompt and context -------------------------------------------------------------------------------------

RULES = """You are the explainer inside MarketLab, a private research and paper-investing system for NSE stocks used by
one individual investor in India (configured paper capital is on the card; there is no real-money or order
capability). You receive one stock's research card. Everything on the card was computed by MarketLab's own
deterministic code from official NSE files.

Rules:
1. Every number you state must be copied from the card (you may round it to fewer decimals). Do not compute new
   numbers: no sums, differences, ratios, annualisations, price targets or probabilities of your own. If a figure you
   would like is not on the card, say it is not available.
2. Explain the maths step by step in plain words, using this stock's numbers: what was measured (features and their
   ranks), how the model turns them into a raw forecast (coefficients times ranks, plus the common part), how
   uncertainty is handled (bootstrap standard error, shrinkage, calibrated 10/50/90% range), the costs at the
   whole-share quantity, the two gates, and how that produces the class.
3. Explain what the numbers mean together: which support the call, which contradict it, and how strong the overall
   evidence is. Use the card's INSIGHTS and add your own reasoning about the combination.
4. Bring value beyond restating: what kind of company this is and what usually drives such stocks, what the owner
   should check before acting (results dates, announcements, corporate actions, sector news), what would make the call
   stronger or weaker, and common mistakes for small accounts. Anything not on the card is general knowledge: label
   it "General knowledge (not from MarketLab's data; may be out of date)" and never present it as a fact about today.
5. Be honest about limits. Unless the card says the validation status is PROMOTED, the model is unvalidated and may
   have no real skill. Past patterns may not repeat. Costs are large for small positions.
6. Do not tell the owner to buy or sell, and give no guarantees or price targets. Describe what the research system
   concluded, why, and how confident it can be.
7. Write for someone new to quantitative finance. Define each technical term the first time you use it (use the
   glossary below). Short sentences. Use headings and bullet points.
8. If the owner asks a specific question, answer it first, then add only the sections that help.

Default structure (when the owner asks for a full explanation):
## Summary  (the call and the main reason, 3-5 sentences)
## The maths, step by step
## What the numbers mean together
## What would change the call
## General context (general knowledge)
## What to check yourself
## Caveats
"""


def system_prompt() -> str:
    """Stable across stocks and rankings (so the provider can cache it): rules, glossary, features, classes and the
    pipeline description. Live statuses and every stock-specific number go in the user message."""
    g = explain.glossary()
    lines = [RULES, "GLOSSARY (MarketLab's definitions):"]
    for k in sorted(g):
        e = g[k]
        lines.append(f"- {e['term']}: {e['plain']}" + (f" Formula: {e['formula']}." if e.get("formula") else ""))
    lines.append("\nFEATURES (inputs of the model; stock features are ranked across the day's stocks, market features z-scored):")
    for f, i in explain.FEATURE_INFO.items():
        lines.append(f"- {f} = {i['name']} [{i['units']}]: {i['what']} Formula: {i['formula']}. High: {i['high']}. Low: {i['low']}.")
    lines.append("\nCLASSES (checked in this order: buy candidate, qualifies, avoid, high risk, hold off):")
    for c, i in explain.CLASS_INFO.items():
        lines.append(f"- {c} ({i['title']}): {i['means']} Rule: {i['rule']}.")
    lines.append("\nPIPELINE:")
    for st in explain.how_it_works(None)["stages"]:
        lines.append(f"- {st['title']}: {st['what']}" + (f" Maths: {st['maths']}" if st.get("maths") else ""))
    return "\n".join(lines)


def _fmt_checks(card) -> list[str]:
    return [f"  - {c['rule']}: {c['value']} (needs {c['need']}) -> {'pass' if c['pass'] else 'unknown' if c['pass'] is None else 'FAIL'}"
            for c in card.get("checks", [])]


def build_context(view: dict, ranking: dict) -> str:
    """The user message: the stock card as labelled lines, MarketLab's narrative and insights, model and data status."""
    card = view["card"]
    pol, v, d, m = ranking.get("policy", {}), ranking.get("validation", {}), ranking.get("data", {}), ranking.get("model") or {}
    pct, rup = explain.pct, explain.rupees
    L = [f"STOCK: {card['symbol']} ({card.get('name') or 'name unknown'}), ISIN {card['isin']}, series {card.get('series')}",
         f"SESSION: close of {ranking.get('day')} (next session {ranking.get('entry_session')}); horizon h = {ranking.get('h')} sessions",
         f"CLASS: {card['class']} = {view['class_info']['title']}. Rule: {view['class_info']['rule']}",
         "REASONS: " + " | ".join(f"{r['code']}: {r['text']}" for r in view["reasons"]),
         f"VALIDATION STATUS: {v.get('status')} ({v.get('note', '')})",
         f"PRICE: close {rup(card['close'])}, previous close {rup(card.get('prev_close'))}, day change {pct(card.get('day_change'))}, "
         f"median traded value (20 sessions) {explain.crore(card.get('median_value_20'))}"]
    fc = card.get("forecast")
    if fc:
        c = card["costs"]
        L += [f"FORECAST (excess return vs Nifty 50 over {ranking.get('h')} sessions, before costs): raw mu_hat {pct(fc['mu_hat'], 3)}; "
              f"bootstrap se {pct(fc['se'], 3, sign=False)}; shrink factor {fc['shrink_factor']:.3f} (tau {pct(fc['tau'], 2, sign=False)}); "
              f"shrunk mu {pct(fc['mu_shrunk'], 3)}; sigma_hat {pct(fc['sigma_hat'], 2, sign=False)}; q10 {pct(fc['q10'])}; "
              f"q50 {pct(fc['q50'])}; q90 {pct(fc['q90'])}; P(excess>0) {fc['p_positive']:.3f}; calibration residuals {fc['calibration_n']}",
              f"RANK: {card.get('rank')} of {card.get('rank_of')} forecast stocks by net edge",
              "CONTRIBUTIONS (beta x rank = contribution to mu_hat): intercept " + pct(card["contributions"]["intercept"], 3)
              + f"; common part {pct(card['contributions']['common_total'], 3)}; stock part {pct(card['contributions']['stock_total'], 3)}"]
        for it in card["contributions"]["items"]:
            raw = (card.get("features") or {}).get(it["feature"])
            L.append(f"  - {it['feature']} ({explain.FEATURE_INFO[it['feature']]['name']}): raw value {raw if raw is not None else 'n/a'}; "
                     f"x {it['x']:+.4f}; beta {it['beta']:+.5f}; contribution {pct(it['contribution'], 3)}")
        L += [f"COSTS at {c['q']} shares = {rup(c['value'])}: charges {rup(c['charges'])} (buy {rup(c['buy_charges'])}, sell incl. DP "
              f"{rup(c['sell_charges_incl_dp'])}, DP charge {rup(c['dp_charge'])}); slippage {rup(c['slippage_rupees'])} "
              f"({pct(c['slippage_fraction'], 2, sign=False)} both ways); round trip {pct(c['cost_fraction'], 3, sign=False)} of the position; "
              f"limit price {rup(c['limit_price'])}; cash blocked {rup(float(c['cash_blocked']))}",
              "COST AT OTHER ACCOUNT SIZES: " + "; ".join(f"capital {rup(b['capital'], 0)} -> position {rup(b['position'], 0)}: "
                                                          f"{pct(b['cost_fraction'], 3, sign=False)}" for b in c.get("bigger_accounts", [])),
              f"GATES at quantity: failed {card['gates']['at_quantity'] or 'none'}; net edge (shrunk mu - cost) {pct(card['gates']['net_edge'], 3)}; "
              f"edge threshold (cost + minimum edge) {pct(card['flip'].get('edge_threshold'), 3)}; P(excess > cost) "
              f"{card.get('p_beats_costs') if card.get('p_beats_costs') is not None else 'n/a'}",
              "FLIP ANALYSIS: " + explain.flip_text(card, pol)]
    elif card.get("features"):
        L.append("FEATURES (raw): " + "; ".join(f"{k} {v}" for k, v in card["features"].items()))
    L.append("ELIGIBILITY CHECKS:")
    L += _fmt_checks(card)
    if card.get("actions"):
        L.append("LISTED CORPORATE ACTIONS: " + "; ".join(f"{a['ex_date']} {'/'.join(a['kinds'])} factor {a.get('price_factor')} "
                                                         f"({a['status']})" for a in card["actions"]))
    L.append("\nTODAY ACROSS ALL STOCKS (deterministic summary of the whole ranking):")
    L += [f"- {x}" for x in explain.day_summary(ranking)]
    L.append("\nMARKETLAB NARRATIVE (deterministic):")
    for s in view["narrative"]:
        L.append(f"### {s['title']}\n{s['text']}")
    L.append("\nINSIGHTS (rules about what the numbers mean together):")
    for i in view["insights"]:
        L.append(f"- {i['title']}: {i['text']}")
    L += ["\nMODEL: " + (f"ridge, lambda {m.get('lam')}, trained on {m.get('train_rows')} rows over {m.get('train_days')} dates "
                         f"{' to '.join(m.get('train', []))}; calibration {m.get('calibration_n')} residuals "
                         f"{' to '.join(m.get('calibration', []))}; {m.get('bootstraps')} bootstrap refits" if m else "none"),
          f"POLICY: capital {rup(pol.get('W'), 0)}, K {pol.get('K')}, per-stock cap {rup(pol.get('cap_rupees'), 0)}, cash reserve "
          f"{rup(pol.get('reserve_rupees'), 0)}, minimum edge {pct(pol.get('min_edge'), 2, sign=False)}, tail limit "
          f"{pct(pol.get('tail_limit'), 2, sign=False)}",
          f"DATA: {d.get('stored_sessions')} sessions {d.get('panel_first')} to {d.get('panel_last')}; calendar basis "
          f"{d.get('session_basis')}; surveillance file admissible: {d.get('rule_inputs', {}).get('have_surveillance_file')}; "
          f"corporate-action registry: {'loaded' if d.get('actions') else 'not loaded'}"]
    return "\n".join(L)


def reservation_usd(model: str, system_text: str, user_text: str, max_tokens: int, fallback: bool) -> Decimal:
    """Upper bound: system text at the cache-write price, the card at the input price, max_tokens of output; plus a
    full second attempt at the fallback model's rates when fallback is on."""
    p = budget.CLAUDE_PRICES[model]
    sys_t = math.ceil(len(system_text) / CHARS_PER_TOKEN) + 50
    usr_t = math.ceil(len(user_text) / CHARS_PER_TOKEN) + 50
    if p.long is not None and sys_t + usr_t > (p.long_threshold or 0):
        p = p.long

    def one(pr):
        return (Decimal(sys_t) * pr.cache_write_5m + Decimal(usr_t) * pr.input + Decimal(max_tokens) * pr.output) / 1_000_000
    total = one(p)
    fb = MODELS[model].get("fallback_price")
    if fallback and MODELS[model]["fallback"] and fb:
        total += one(budget.CLAUDE_PRICES[fb])
    return total.quantize(Decimal("0.0001"), rounding=ROUND_CEILING)


_NUM = re.compile(r"(?<![\w.])[-+−]?₹?\s?\d[\d,]*(?:\.\d+)?\s?%?")


def _numbers(text: str) -> list[tuple[str, float, int, bool]]:
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0).strip()
        s = raw.replace("₹", "").replace(",", "").replace("−", "-").replace(" ", "")
        is_pct = s.endswith("%")
        s = s.rstrip("%")
        try:
            v = float(s)
        except ValueError:
            continue
        dec = len(s.split(".")[1]) if "." in s else 0
        out.append((raw, v, dec, is_pct))
    return out


def unsourced_numbers(answer: str, context: str, question: str = "") -> list[str]:
    """Numbers in the answer that do not appear (to the answer's own precision, ignoring sign) in the card or the
    question. Small counts and years are ignored."""
    known = [(abs(v), p) for _, v, _, p in _numbers(context) + _numbers(question)]
    bad = []
    for raw, v, dec, is_pct in _numbers(answer):
        if not is_pct and dec == 0 and (abs(v) <= 12 or 1900 <= abs(v) <= 2100):
            continue
        tol = 0.5 * 10 ** (-dec) + 1e-9
        if not any(abs(abs(v) - k) <= tol for k, kp in known if kp == is_pct or not is_pct):
            bad.append(raw)
    return sorted(set(bad), key=bad.index)


# ---- the call -------------------------------------------------------------------------------------------------

def _default_client(key: str):
    try:
        import anthropic
    except ImportError:
        raise AIError("SDK_NOT_INSTALLED", "pip install anthropic (optional extra: marketlab[ai])") from None
    return anthropic.Anthropic(api_key=key, max_retries=1, timeout=300.0)


def _call(client, *, model: str, system: str, user: str, max_tokens: int, effort: str, fallback: bool):
    kwargs = dict(model=model, max_tokens=max_tokens,
                  system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                  messages=[{"role": "user", "content": user}],
                  thinking={"type": "adaptive"}, output_config={"effort": effort})
    if fallback and MODELS[model]["fallback"]:
        with client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **kwargs) as stream:
            return stream.get_final_message()
    with client.messages.stream(**kwargs) as stream:
        return stream.get_final_message()


def _get(o, k, default=None):
    if isinstance(o, dict):
        return o.get(k, default)
    return getattr(o, k, default)


def cost_of(msg, requested_model: str) -> dict:
    """Cost from the reported tokens of every attempt (``usage.iterations`` when present, else the top-level usage)."""
    usage = _get(msg, "usage")
    its = _get(usage, "iterations") or []
    attempts = []
    for it in its or [usage]:
        model = _get(it, "model") or _get(msg, "model") or requested_model
        toks = {k: int(_get(it, k) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                                                    "cache_read_input_tokens")}
        usd, known = budget.token_cost_usd(model, input_tokens=toks["input_tokens"], output_tokens=toks["output_tokens"],
                                           cache_write_tokens=toks["cache_creation_input_tokens"],
                                           cache_read_tokens=toks["cache_read_input_tokens"])
        attempts.append({"model": model, "type": _get(it, "type") or "message", **toks, "usd": str(usd), "price_known": known})
    total = sum((Decimal(a["usd"]) for a in attempts), Decimal("0"))
    return {"attempts": attempts, "usd": total}


def _error_label(e: Exception) -> tuple[str, bool]:
    """(label, billed?) from the SDK's typed errors (by class name, so the SDK stays optional)."""
    name, code = type(e).__name__, getattr(e, "status_code", None)
    if name == "AuthenticationError":
        return "AUTH", False
    if name == "PermissionDeniedError":
        return "PERMISSION_DENIED", False
    if name == "NotFoundError":
        return "MODEL_NOT_FOUND", False
    if name == "RateLimitError":
        return "RATE_LIMITED", False
    if name in ("BadRequestError", "UnprocessableEntityError"):
        return "BAD_REQUEST", False
    if name in ("APITimeoutError", "APIConnectionError"):
        return "CONNECTION", True  # the request may have been processed: settle at the reservation
    if code is not None:
        return (f"SERVER_{code}", True) if code >= 500 else (f"HTTP_{code}", False)
    return "UNEXPECTED_" + name, True


def ask(root: Path, market: Path, ranking: dict, isin: str, *, question: str = "", preset: str = "explain",
        session_key: str | None = None, client_factory=None, ask_id: str | None = None) -> dict:
    """One explanation. Returns the stored record (never containing the key)."""
    card = next((s for s in ranking.get("stocks", []) if s["isin"] == isin), None)
    if card is None:
        raise AIError("UNKNOWN_STOCK")
    question = (question or "").strip()[:MAX_QUESTION]
    if not question:
        if preset not in PRESETS:
            raise AIError("BAD_PRESET")
        question = PRESETS[preset]
    key, source = resolve_key(root, session_key)
    if not key:
        raise AIError("NO_KEY", "enter an Anthropic API key in the AI settings")
    st = settings(root)
    model, effort, max_tokens = st["model"], st["effort"], int(st["max_tokens"])
    fallback = bool(st["fallback"]) and MODELS[model]["fallback"]
    view = explain.stock_view(card, ranking)
    system = system_prompt()
    context = build_context(view, ranking)
    user = f"<stock_card>\n{context}\n</stock_card>\n\n<question>\n{question}\n</question>"
    reserve = reservation_usd(model, system, user, max_tokens, fallback)
    ask_id = ask_id or f"{now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    ledger = budget.Ledger(_ledger_path(market), budget.Policy.load(root / POLICY_FILE))
    try:
        with _LOCK:
            try:
                rid = ledger.reserve(ask_id, JOB_KIND, reserve)
            except budget.BudgetExceeded as e:
                raise AIError("BUDGET_" + e.label, f"this ask reserves up to ${reserve}; {e}") from None
        record = {"id": ask_id, "kind": "AI_COMMENTARY", "label": "AI commentary: not a MarketLab calculation and never a "
                  "decision input", "created_at": now().isoformat(), "isin": isin, "symbol": card["symbol"],
                  "class": card["class"], "ranking_day": ranking.get("day"), "ranking_digest": ranking.get("digest"),
                  "question": question, "preset": preset if not question or question == PRESETS.get(preset) else "custom",
                  "model_requested": model, "effort": effort, "max_tokens": max_tokens, "fallback_enabled": fallback,
                  "key_source": source, "reserved_usd": str(reserve),
                  "context_sha256": hashlib.sha256(user.encode()).hexdigest(),
                  "system_sha256": hashlib.sha256(system.encode()).hexdigest(), "price_source": budget.PRICE_SOURCE}
        try:
            client = (client_factory or _default_client)(key)
            msg = _call(client, model=model, system=system, user=user, max_tokens=max_tokens, effort=effort, fallback=fallback)
        except AIError:
            ledger.release(rid, "SDK_NOT_INSTALLED")
            raise
        except Exception as e:  # noqa: BLE001 - mapped to a fixed label; provider text is not echoed
            label, billed = _error_label(e)
            if billed:
                ledger.settle(rid, None, detail={"error": label})
            else:
                ledger.release(rid, label)
            record.update(state="FAILED", error=label, cost_usd=str(reserve) if billed else "0")
            _store(root, record)
            raise AIError(label) from None
        cost = cost_of(msg, model)
        charged = ledger.settle(rid, cost["usd"], detail={"attempts": len(cost["attempts"]),
                                                         "prices_known": all(a["price_known"] for a in cost["attempts"])})
        text = "".join(_get(b, "text") or "" for b in (_get(msg, "content") or []) if _get(b, "type") == "text")
        switches = [{"from": _get(_get(b, "from_") or _get(b, "from"), "model"), "to": _get(_get(b, "to"), "model")}
                    for b in (_get(msg, "content") or []) if _get(b, "type") == "fallback"]
        stop = _get(msg, "stop_reason")
        sd = _get(msg, "stop_details")
        record.update(state="REFUSED" if stop == "refusal" else "TRUNCATED" if stop == "max_tokens" else "DONE",
                      answer=text, stop_reason=stop, stop_category=_get(sd, "category") if sd else None,
                      model_served=_get(msg, "model"), fallback_switches=switches, usage=cost["attempts"],
                      cost_usd=str(charged), unsourced_numbers=unsourced_numbers(text, user, question))
        _store(root, record)
        return record
    finally:
        ledger.close()


def _store(root: Path, record: dict):
    path = decisions.runs_dir(root) / FOLDER / f"{record['id']}.json"
    decisions._write_once(path, record)


def history(root: Path, isin: str | None = None, limit: int = 20) -> list[dict]:
    base = decisions.runs_dir(root) / FOLDER
    out = []
    for p in sorted(base.glob("*.json"), reverse=True) if base.exists() else []:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isin and r.get("isin") != isin:
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


class Jobs:
    """Asks run in a background thread; the browser polls by id. Memory only (answers are on disk)."""

    def __init__(self):
        self.lock, self.items = threading.Lock(), {}

    def start(self, fn, **kw) -> str:
        jid = f"{now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        with self.lock:
            self.items[jid] = {"id": jid, "state": "RUNNING", "started_at": now().isoformat()}

        def run():
            try:
                rec = fn(ask_id=jid, **kw)
                upd = {"state": rec["state"], "record": rec}
            except AIError as e:
                upd = {"state": "FAILED", "error": e.label, "detail": e.detail}
            except Exception as e:  # noqa: BLE001
                upd = {"state": "FAILED", "error": "UNEXPECTED_" + type(e).__name__}
            with self.lock:
                self.items[jid].update(upd)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        with self.lock:
            self.items[jid]["_thread"] = t
        return jid

    def get(self, jid: str) -> dict | None:
        with self.lock:
            it = self.items.get(jid)
            return {k: v for k, v in it.items() if not k.startswith("_")} if it else None

    def wait(self, jid: str, timeout: float = 30.0):
        t = self.items.get(jid, {}).get("_thread")
        if t:
            t.join(timeout)
