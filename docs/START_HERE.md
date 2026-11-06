# Start here: setup, the daily loop, and how to read the output

For the owner. Every command below is read-only with respect to the broker: this system has no order, GTT,
conversion or fund-transfer endpoint, and it never automates a login.

Two workspaces exist. **Research** (what the ranking and the dashboard use) lives in `data/research/`;
the plain workspace in `data/`. Research commands carry both directory flags, so the shorthand used here is:

```powershell
$ML = ".\.venv\Scripts\marketlab.exe --private-dir data\research\private --market-dir data\research\market"
```

Then `& $ML rank` means the research workspace. Without those flags you are in the other one, which has its own
(mostly empty) panel. Details of the install, the Kite developer app, the env file and folder permissions are in
[KITE_AND_SERVER_SETUP.md](KITE_AND_SERVER_SETUP.md); the server and phone app are in
[DEPLOYMENT.md](DEPLOYMENT.md).

## 1. First-time setup, in order

```powershell
py -3.13 -m venv .venv                                   # 1. environment
.\.venv\Scripts\python.exe -m pip install -e ".[ai]"     #    [ai] adds the optional explainer SDK
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pytest tests -q            # 2. 617 tests should pass
& $ML panel-build                                        # 3. price panel from stored bhavcopies
& $ML actions-reconcile                                  # 4. every price jump against the listed actions
& $ML rank                                               # 5. today's ranking
& $ML dashboard --port 8770                              # 6. the app, http://127.0.0.1:8770
```

The API key for the AI explainer goes in the dashboard's **Controls & AI** tab, or in
`data/research/private/.env` — never in a chat, a commit or a command line. Only allowlisted key names are
accepted, and any name containing PASSWORD, PIN, TOTP or OTP is refused.

## 2. The daily loop

```powershell
.\.venv\Scripts\python.exe scripts\daily_update.py `
  --private-dir data\research\private --market-dir data\research\market
```

That is the whole evening. It is idempotent: running it twice on the same day changes nothing. What it does, in
order: downloads the day's official NSE files (one request per file), rebuilds the panel, writes a new ranking
artifact, and scores any earlier ranking whose 20-session labels have now resolved — which is how the forward
record accumulates.

If you want the steps by hand:

```powershell
python scripts\pilot_acquire.py data\research 2026-11-06 2026-11-06
& $ML panel-build
& $ML rank                      # or: rank --capital 30000
```

Kite is only needed for the historical backfill and live quotes, not for the daily ranking. When it is needed:

```powershell
& $ML auth                      # opens Zerodha's page; you type the password there, never here
& $ML kite-backfill --dry-run --instrument-file <csv> --bhavcopy <zip>
```

The token expires at the next 06:00 IST, so this is once per collection day, by hand, by you.

## 3. Reading the output

Open the dashboard and start on **Stocks**.

- **Top 10 by expected return** — the model's own order, best first. The call beside each stock is what the gates
  make of it: a stock can top this list and still be one not to buy.
- **Capital switch** — ₹3,000 / ₹10,000 / ₹30,000 / ₹1,00,000 or your own figure. Only costs, whole-share
  quantities and the gates move; the forecast never changes, because capital cannot change what a stock will do.
- **The seven calls** — buy candidate, qualifies, hold off, high risk, avoid, not eligible, no forecast. The exact
  rule for each is in [STOCK_RANKING.md](STOCK_RANKING.md) and on the **How it works** tab.
- **Click any stock** for the full working: the forecast range against what a buy needs, what drives it, where
  the cost goes, the price against the Nifty 50, and what would change the call.
- **Ask AI** explains one stock's numbers in plain words for a few paise. It never computes anything; every
  number it states is checked against the card.

### What the numbers mean, honestly

| Field | What it is | What it is not |
|---|---|---|
| μ̂ (raw forecast) | The ridge model's expected 20-session return **against the Nifty 50** | A price target, or a return you keep |
| μ̃ (shrunk) | μ̂ cut toward zero by how much the model disagrees with itself across bootstrap refits | A conservative estimate — it is the honest one |
| q10 / q50 / q90 | A calibrated range for that excess return; 1 month in 10 is worse than q10 | A guarantee; the calibration itself is unvalidated |
| Cost | Exact Zerodha delivery charges plus the ₹15.34 DP fee plus modelled slippage | An estimate — this part is verified against the schedule |
| Call | What the gates make of the forecast at your capital | Advice |

**The status line matters more than any number: UNVALIDATED.** The model has not passed the walk-forward
evaluation, the holdout is frozen but unused, and no forward prediction has yet been scored. Until
[BACKTEST_PLAN.md](BACKTEST_PLAN.md) runs, there is no evidence that μ̃ predicts anything. The arithmetic is
verified exact; the usefulness is not measured.

## 4. Which stocks are analysed, and what the 5 Nov 2026 ranking says

Every listed EQ and BE share is analysed (owner decision 2026-11-06, erratum E21). Capital never decides whether a
stock is analysed, only whether a whole share can be bought; illiquidity is costed with wider slippage and flagged
`LOW_LIQUIDITY`, not excluded. What is still screened, and why:

| Not forecast | Count | Why |
|---|---|---|
| SME platform (SM 406, ST 75) | 481 | Trade in lots often worth ₹1 lakh or more; designed in docs/NEXT_MODELS.md |
| ETFs | 356 | An index, not a company; belongs with mutual funds (docs/NEXT_MODELS.md) |
| Not traded every session (last 20) | 87 | No continuous prices to compute features from |
| BZ and other special series | 35 | Non-compliant companies, trade-for-trade with restrictions |
| Too new or too gappy for a year of features | 298 | Mostly recent listings; the young-stock model is designed in docs/NEXT_MODELS.md |
| Exchange risk flags (ASM/GSM 324, 5% band 71, call auction 2) | 397 | Avoided on the exchange's own warning, before any model |
| **Forecast** | **1,804** | of 3,458 listed securities (801 before E21) |

**The corrected ranking of 5 Nov 2026** (errata E19–E21; independently audited, zero mismatches):

| Call | Count | What it means |
|---|---|---|
| Buy candidate | 1 | BALAMINES: the allocator's risk-adjusted pick at ₹10,000 (calmer than the higher-edge stocks) |
| Qualifies | 38 | Clear both gates; not chosen for portfolio fit (e.g. CGPOWER, GESHIP, THANGAMAYL) |
| Hold off | 633 | 581 edge below cost; 52 the model likes but one share is above the ₹5,000 cap (APARINDS, POWERINDIA, SOLARINDS rank #1, #2, #5) |
| High risk | 1,118 | A bad month would cost the account more than 8%; 737 of them are illiquid |
| Avoid | 411 | 324 under ASM/GSM surveillance, 71 on 5% bands, 2 call auction, **14 the model's own view** (e.g. NETWORK18, AWFIS, POKARNA) |

Capital changes the answer, never the forecast: the same day restated gives 0 buys at ₹3,000, 110 qualifying at
₹30,000, and APARINDS and POWERINDIA as buys at ₹1,00,000, once a share fits the cap.

**Why nothing ranked before:** the forecast's uncertainty was dominated by its market-timing part (estimated from
about 15 independent months), which crushed the stock-selection signal (E19); and the 8% loss limit was applied to
one stock's month instead of the account (E20). Both are fixed. **The model is still unvalidated**: one held-out
window (Jul–Oct 2026) shows real skill, but only four independent periods. docs/BACKTEST_PLAN.md is the test.

## 5. Commands by job

| Job | Command |
|---|---|
| Daily update | `.\.venv\Scripts\python.exe scripts\daily_update.py --private-dir data\research\private --market-dir data\research\market` |
| Rank at another capital | `& $ML rank --capital 30000` |
| Dashboard | `& $ML dashboard --port 8770` |
| Universe screen for a date | `& $ML screen --date 2026-11-05` |
| Corporate actions: import / reconcile | `& $ML actions-import-api --folder <dir>` / `& $ML actions-reconcile` |
| Freeze the holdout (**once**, after the backfill) | `& $ML freeze-holdout` |
| Registered evaluation | `& $ML evaluate --candidate A --h 20` |
| Targeted tests after a change | `.\.venv\Scripts\python.exe -m pytest tests\test_ranking.py -q` |
| Everything | `.\.venv\Scripts\python.exe -m pytest tests -q` |

## 6. Where to go next

1. **[BACKTEST_PLAN.md](BACKTEST_PLAN.md)** — the 1,000-trial randomized replay that decides whether this model
   knows anything. Specified, not built. This is the next thing worth doing.
2. **The backfill** — ~3 more years of history; the plan in section 8 of that document needs it first.
3. **[HANDOFF.md](HANDOFF.md)** — current state, what is in flight, what is left.
