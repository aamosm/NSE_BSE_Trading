# Reference projects: logic, flaws and what we take

Reviewed 4 November 2026 per Build Guide §15 ("record the exact version, license, maintained features, dependencies, known issues and the parts you will use").

The 20 projects below are cloned read-only in `../../reference_bots/`, a sibling of this kit and outside this Git repository. Commits are listed in `reference_bots/VERSIONS.txt`.

- **No reference code was run, installed or copied.** Several licences are copyleft (GPL/AGPL/LGPL). One project has no licence at all. Vectorbt carries a Commons Clause. We borrow **ideas only** and write our own code.
- File references are relative to each project's root at the commit shown.
- "Flaw" means a behaviour that would give wrong results *for our use*: Indian cash equities, Zerodha, ₹10,000, delivery and MTF. It is not a judgement on the project's own goals.

## 1. Summary table

| Project | Commit (date) | Licence | What it is | Use for us |
| --- | --- | --- | --- | --- |
| zerodha/pykiteconnect | 2f67c46 (2026-09-15) | MIT | Official Kite Connect client | Reference for Phase 7 API calls. Wrap it; never enable `debug` |
| marketcalls/openalgo | e2797fd (2026-11-03) | AGPL-3.0 | Self-hosted multi-broker platform (Flask/React), 36 brokers, sandbox | Ideas: recovery by order tag, per-symbol locks. Do not adopt its sandbox economics |
| jugaad-py/jugaad-trader | 72e735b (2025-12-19) | "YOLO" licence | Unofficial Zerodha client via web login | **Counter-example.** Violates our auth rules |
| The-Great-One/Auto_Trader | ac238b2 (2026-10-25) | none in repo (README badge says MIT) | Paper-only NSE RSI rotation on yfinance | Counter-example for costs and data |
| algobulls/pyalgotrading | 422003a (2026-02-04) | MIT | Client for the AlgoBulls platform + P&L reports | Counter-example: cost and P&L bugs |
| QuantConnect/Lean (+ Zerodha brokerage) | 9ecfed9 (2026-11-02) / 629eb0e | Apache-2.0 | C# event-driven engine with India/Zerodha models | Ideas: brokerage/fee/settlement model interfaces. Its Zerodha numbers are wrong for delivery |
| freqtrade/freqtrade | 7d9717c (2026-11-03) | GPL-3.0 | Crypto bot with dry-run, backtest, hyperopt | Ideas: startup order reconciliation, look-ahead and recursive-indicator detectors |
| hummingbot/hummingbot | 9af100d (2026-09-22) | Apache-2.0 | Market-making connectors framework | Ideas: client order IDs before submit, lost-order set, fill dedupe by trade ID |
| nautechsystems/nautilus_trader | 80b20c8 (2026-11-04) | LGPL-3.0 | Rust/Python event-driven platform | Ideas: fixed-point value types, startup and submission reconciliation, fill models |
| jesse-ai/jesse | 8665b25 (2026-11-03) | MIT | Crypto backtest/live framework | Idea: opening-gap fills for resting orders |
| microsoft/qlib | 5435523 (2026-10-08) | MIT | Quant research platform | Idea: point-in-time (PIT) storage with revision chains for Phase 2 |
| kernc/backtesting.py | ca2e261 (2026-08-05) | AGPL-3.0 | Small single-asset backtester | Next-bar fills, pessimistic SL/TP ordering |
| mementum/backtrader | b853d7c (**2023-04-19**) | GPL-3.0 | Classic event backtester, unmaintained | Avoid |
| polakowo/vectorbt | c923f74 (2026-11-03) | Apache-2.0 + Commons Clause | Vectorised backtester | Avoid its defaults. Fast parameter sweeps later, if ever |
| robcarver17/pysystemtrade | bbf5cf8 (2026-11-02) | GPL-3.0 | Production futures system (Rob Carver) | Ideas: order stacks, position-break locks, costs in Sharpe-ratio units |
| stefan-jansen/zipline-reloaded | 5dd9fef (2026-11-02) | Apache-2.0 | Maintained Zipline | Idea: volume-capped slippage. US defaults |
| gerrymanoim/exchange_calendars | bbda29f (2026-09-15) | Apache-2.0 | Exchange session calendars incl. XBOM (BSE) | Independent cross-check of holidays; not a settlement calendar |
| ranaroussi/quantstats | d1a214f (2026-11-02) | Apache-2.0 | Performance tear sheets | Cross-check of metric formulas; do not use its defaults |
| AI4Finance-Foundation/FinRL | 7e98df4 (2026-10-25) | MIT | Reinforcement-learning trading environments | Counter-example: same-close execution, yfinance universe |

## 2. Flaws that recur across projects

| # | Recurring flaw | Where seen (evidence) | Why it matters here | Our rule / where handled |
| --- | --- | --- | --- | --- |
| F1 | **Costs flattened to a percentage, or missing** | Auto_Trader `scripts/rsi_momentum_paper_ledger.py:45` (flat 10 bps). OpenAlgo sandbox has no STT, stamp, GST or DP anywhere in `sandbox/`. pyalgotrading `utils/func.py:179-205` (brokerage only). vectorbt fees default 0. zipline US per-share commission | On a ₹1,000 Zerodha delivery round trip the **₹15.34 DP charge alone is 153 bps**; total break-even is **+1.76%** (`tests/test_metrics.py`). A 10 bps assumption understates costs ~18x at that size | `rules/charges.py` itemises every component; `metrics.round_trip_breakeven` |
| F2 | **Wrong India charge rates** | Lean `Common/Orders/Fees/ZerodhaFeeModel.cs`: every order charged intraday rates (brokerage 0.03% capped ₹20, STT 0.025% sell-only, stamp 0.003%), exchange 0.00345%, no DP, GST base omits SEBI fee, .NET banker's rounding | A delivery backtest in Lean gets **no buy-side STT and a quarter of the sell-side STT** (0.1% each side in reality), pays brokerage Zerodha doesn't charge on delivery, and omits DP | Effective-dated `ChargeSchedule` per product (`TradeKind`) |
| F3 | **Leverage multiplier instead of financing** | OpenAlgo `sandbox/fund_manager.py:871-893` (MIS 5x, CNC 1x, config values). Lean `ZerodhaBrokerageModel` `_maxLeverage = 5` for every equity in a margin account, overnight, no interest | Build Guide/Phase 1: "Do not use a leverage multiplier as a substitute for financing accounting." Overnight 5x with zero interest is not a Zerodha product | Phase 1 MTF ledger: funded principal, daily interest, pledge, margin calls |
| F4 | **Settlement = midnight / weekday arithmetic** | OpenAlgo `sandbox/holdings_manager.py:150-163` moves CNC positions to holdings after midnight with no settlement-holiday check, from wall-clock `datetime.now`. exchange_calendars XBOM has no settlement calendar | 2026 has four settlement-only holidays (19 Feb, 19 Mar, 1 Apr, 26 Aug). A trade on 25 Aug settles on **27 Aug**, not 26 Aug. Wall-clock time also makes replay impossible | `MarketCalendar.settlement_date`; replay clock (Phase 3) |
| F5 | **One session timetable for every stock** | OpenAlgo `sandbox/squareoff_manager.py:53` 15:15 for all of NSE/BSE. exchange_calendars XBOM `open_times/close_times` fixed 09:15–15:30 (`exchange_calendar_xbom.py:491-492`) | Since 3 Aug 2026, F&O stocks stop continuous trading at 15:15 (closing auction); Zerodha's MIS cut-off is 15:12 for them and 15:25 for others | `sessions.timetable(date, has_derivatives)`, `broker.mis_cutoff` |
| F6 | **No India instrument rules** | No project models T2T series (BE/BZ, T/XT), GSM/ESM/ASM stages, price bands or the 2025 tick table. qlib assumes China (`qlib/backtest/exchange.py:48-50,109`: 100-share lots, 0.15%/0.25% costs, uniform limit). Lean `CanUpdateOrder` always true (no 25-modification cap) | These rules decide whether an order is even *legal*. Getting them wrong produces trades that could not happen | `rules/engine.py` (reason codes) |
| F7 | **Fill realism: same-bar close or touch-fills** | vectorbt order `price` defaults to `np.inf` = the bar's close (`portfolio/base.py:1683-1684`). FinRL trades at the close of the observation day. Auto_Trader `rsi_224466_rotation_lab.py:368-389` credits the trade day's close-to-close return to weights traded on that day. freqtrade `optimize/backtesting.py:791-793` and OpenAlgo `sandbox/execution_engine.py:535-540` fill limits when price merely touches | NSE's closing price is a VWAP (and since Aug 2026 an auction price for F&O stocks). **It is not a price you could have traded at after seeing it.** Touch-fills ignore queue position | Phase 3 fill model: next-session prices, explicit queue/touch assumptions, labelled as assumptions |
| F8 | **Annualisation and risk-free defaults** | quantstats `stats.py:938` (rf 0, 252 periods) and `stats.py:1678` (CAGR years = count/252). vectorbt `_settings.py:320` `year_freq="365 days"`. backtrader `analyzers/sharpe.py:113-119` (yearly returns, rf 1%, population sd). backtesting.py `_stats.py:126-130` (252 or 365) | NSE 2026 has **245** sessions. With 365, vectorbt inflates a daily Sharpe by √(365/245) ≈ **1.22x**. Ignoring a ~6% Indian T-bill rate inflates Sharpe further. backtrader's default computes Sharpe from a handful of annual points | `metrics.trading_sessions_in_year`; `sharpe_ratio(rf_per_period=...)` is mandatory |
| F9 | **Selection bias unmeasured** | Auto_Trader picks a "champion" from a parameter lab. vectorbt/backtesting.py optimisers report the best run. quantstats PSR tests only against SR = 0 and has no deflation | 1,000 planned trials: the best one will look good by luck | `metrics.deflated_sharpe_ratio`, `probability_of_backtest_overfitting` (CSCV) |
| F10 | **Order sent before intent is persisted** | freqtrade `freqtradebot.py` `execute_entry`: `exchange.create_order` (l.1134) runs **before** `Trade.session.add/commit` (l.1238). A crash between them leaves an exchange order the bot doesn't know about | Contract: "Persist intents before submission… a lost acknowledgement or restart cannot blindly create another order" | Phase 3: durable intent table + tag correlation + reconcile-before-retry |
| F11 | **Assume-cancelled on timeout** | freqtrade `freqtradebot.py:606-616`: an order not found after 5 days is "assumed fully cancelled". nautilus `submission_recovery_policy` defaults to `ResolveLocally` | A filled order mis-recorded as cancelled corrupts positions and cash | Unknown stays `UNCERTAIN` and blocks new entries until reconciled |
| F12 | **Credential and auth shortcuts** | jugaad-trader `jugaad_trader/zerodha.py:89-126` posts user ID + password + 2FA to Kite's web login and reuses the `enctoken` cookie; credentials loaded from a file. pykiteconnect `connect.py:951-952` logs request **headers (incl. the access token)** when `debug=True`; `disable_ssl` option exists | AGENTS.md forbids cookie-auth hacks and stored TOTP. The 2025 SEBI retail-algo framework requires API orders via the broker's registered API path and static IP | Phase 7: official login only; logging redaction tests; `debug` never enabled |
| F13 | **Float money** | Auto_Trader, pyalgotrading, FinRL, vectorbt, backtrader, quantstats all float. pykiteconnect ticker divides integer paise by `100.0` (`ticker.py:729-746`) | Paisa errors accumulate in ledgers; equality checks on prices fail | Decimal everywhere in accounting; convert broker floats via `Decimal(str(x))` at the boundary |
| F14 | **Biased data** | Auto_Trader and FinRL download from yfinance (adjusted, current tickers). FinRL's DOW-30 universe is today's constituents | Survivorship and adjustment leaks; NSE symbols change and delist | Phase 2: PIT data with publication times; historical universe |
| F15 | **Silent pandas behaviour** | pyalgotrading `utils/func.py:199` uses chained assignment `pnl_df["brokerage"].loc[...] = cap`, which pandas 3 Copy-on-Write never applies, so the ₹ cap is silently skipped. `utils/func.py:175` computes `pnl_absolute = exit_price - entry_price`: ignores quantity and short side | Typical "looks right, is wrong" P&L bug | Stdlib Decimal ledger; hand-worked fixtures |

## 3. Project notes

### Indian / Zerodha

**pykiteconnect (official).**
- **Logic:** a thin `requests` wrapper. `place_order` sends only the parameters that aren't None, with no client-side retries for POSTs (good: no blind resubmission). Default timeout is 7 s. A `session_expiry_hook` fires on 403 TokenException.
- **2026 API:** it exposes `market_protection` (`-1` = automatic, or 0 < x ≤ 100) and `algo_id`, matching our register.
- **Flaws:**
  - `debug=True` logs headers containing `token api_key:access_token`.
  - A timeout raises a generic exception even though the order may have been placed, so the caller must reconcile.
  - Ticker prices become floats.
- **Use:** in Phase 7, behind our own adapter with order methods technically disabled in read-only mode.

**OpenAlgo.**
- **Logic:**
  - A unified REST API maps one order schema onto 36 broker plugins.
  - "Smart orders" take a target `position_size` and compute the delta from the live position book (1 s cache, per-symbol lock).
  - The sandbox ("Analyzer mode") simulates fills from live quotes, keeps funds in Decimal, and runs MIS square-off and T+1 jobs on threads.
- **Good:**
  - Each order carries a random `openalgo<hex>` tag. After a transport error it searches the order book for that tag instead of resending (`broker/zerodha/api/order_api.py:220-244`).
  - Per-symbol locks.
  - Its own docstrings record race bugs it has fixed, such as two overlapping T+1 settlement runs doubling a holding (`sandbox/holdings_manager.py:136-146`), which shows these races are real.
- **Flaws:**
  - Recovery searches for only 2 s.
  - Market protection is hard-coded to `-1` automatic (`mapping/transform_data.py:47`). We require an explicit value.
  - The sandbox has flat leverage (F3), midnight settlement (F4), a single 15:15 cut-off (F5), no charges (F1), touch-fills (F7) and no T2T, surveillance or bands (F6).
  - Smart orders that target a position size can double-trade if the position book lags a fill.
  - A large attack surface: web UI, AI agent, script host and MCP in the same process as the broker session.
- **Use:**
  - Tag-based lost-ack recovery and per-symbol locks are good ideas.
  - The analyzer is not an accounting reference.
  - AGPL: no code reuse.

**jugaad-trader.** Logs in through Kite's web endpoints with a password and 2FA value, then reuses the browser `enctoken` cookie. This is exactly the "browser-cookie authentication hack" AGENTS.md prohibits. It breaks whenever the web app changes and bypasses the registered-API requirements of the 2025 retail-algo framework. **Not to be used.**

**Auto_Trader.**
- **Logic:**
  - Ranks NSE stocks by an RSI score on yfinance prices and rotates into the top N at a set rebalance frequency, with an optional market-regime filter.
  - Keeps a JSON paper ledger and compares against an equal-weight baseline.
- **Good:**
  - A baseline comparison.
  - An explicit note: "Do not promote from this report alone; run survivorship-controlled walk-forward".
  - Atomic file writes.
- **Flaws:**
  - Flat 10 bps costs (F1).
  - Fractional weights rather than integer shares.
  - Forward-fills prices up to 3 days, so it can trade on stale prices.
  - Credits the close-to-close return of the trade day (F7).
  - yfinance data (F14).
  - Picks a champion from a parameter lab (F9).
  - Float money (F13).

**pyalgotrading.** A client for the hosted AlgoBulls engine; the strategy logic runs on their servers. Its local P&L report has the F15 bugs, and costs cover brokerage only (F1).

### Event-driven engines

**QuantConnect Lean.**
- **Logic:**
  - The algorithm receives data events.
  - Pluggable models decide what is possible and what it costs: `BrokerageModel` (allowed order types, leverage), `FeeModel`, `SettlementModel`, `FillModel`, `SlippageModel` and `BuyingPowerModel`.
- **Good:** this separation is the right shape for us. Our rules engine plays the role of the brokerage model, `charges.py` the fee model, and the calendar the settlement model.
- **Flaws for India:**
  - F2 fee rates.
  - F3 5x leverage.
  - GTC time-in-force allowed, which Kite regular orders don't have.
  - Unlimited modifications.
  - No bands, T2T or surveillance (F6).

**freqtrade.**
- **Logic:**
  - A strategy class populates indicator, entry and exit columns on a candle DataFrame.
  - A bot loop places orders through ccxt and persists `Trade`/`Order` rows in SQLAlchemy.
  - On startup it re-fetches every open order from the exchange (`startup_update_open_orders`).
  - "Protections" pause trading after loss streaks.
- **Good:**
  - Startup reconciliation.
  - Dry-run with the same code path as live.
  - **`lookahead-analysis`**, which re-runs the strategy on truncated data and flags signals that change.
  - **`recursive-analysis`**, which flags indicators whose values depend on the warm-up length.
  - We should build both detectors in Phase 5.
- **Flaws:** F10 (submit before persist), F11 (assume cancelled), F7 (touch fills), float money.

**hummingbot.**
- **Logic:** connectors keep a `ClientOrderTracker` of `InFlightOrder`s. Its states are PENDING_CREATE → OPEN → PARTIALLY_FILLED → FILLED / CANCELED / FAILED.
- **Good:**
  - The client order ID exists before submission.
  - After N "not found" responses an order moves to a `lost_orders` set but still receives fills (`connector/client_order_tracker.py:59,89`).
  - Fills are deduplicated by `trade_id` (`core/data_type/in_flight_order.py:356-363`).
  - Decimal amounts.
- **Flaws:** the tracker lives in memory, so persistence depends on each connector. Kite tags are not enforced unique by the exchange, so idempotency has to be ours.

**nautilus_trader.**
- **Logic:** a deterministic event-sourced kernel used for both backtest and live. Price, Quantity and Money are fixed-point types with explicit precision. Startup reconciliation brings cached orders and positions in line with venue reports. The fill model has `prob_fill_on_limit` and `prob_slippage`.
- **Good:** the closest to our contract's order-recovery requirements. Its documentation is candid that teardown "does not establish a venue outcome or position flatness".
- **Flaws for us:**
  - The default submission recovery is `ResolveLocally` (F11).
  - It is very large: Rust toolchain, LGPL.
  - No Indian broker adapter.
  - Far beyond ₹10,000 needs.

**jesse.** Simulates resting orders against 1-minute candles. Orders that gap through at the open fill at the open (`modes/backtest_mode.py:1639-1662`), which is correct and worth copying. Crypto-only rules otherwise.

**pysystemtrade.**
- **Logic:**
  - Forecasts are combined, then sized by volatility targeting.
  - Execution goes through three stacks: instrument orders → contract orders → broker orders.
  - Reports compare strategy, instrument and broker positions.
- **Good:**
  - A position break between our books and the broker's **locks the instrument** until it is fixed (`sysexecution/stack_handler/checks.py:29-66`). This is our "no new orders on unresolved reconciliation" rule.
  - Costs are measured in Sharpe-ratio units, so expensive rules are penalised before selection.
- **Flaws:** futures/IB-specific; GPL.

### Research and backtest libraries

**qlib.**
- **Good:** the PIT store keeps (publication `date`, `period`, `value`, `_next` revision pointer) per feature (`docs/advanced/PIT.rst:34-42`). That is the shape we need for filings in Phase 2.
- **Flaws for India:**
  - Exchange defaults are China A-share: `trade_unit` 100, `open_cost` 0.0015, `close_cost` 0.0025, `min_cost` 5 (`qlib/backtest/exchange.py:48-50,109`).
  - A single `limit_threshold`.
  - The Yahoo collector is survivorship-biased.

**backtesting.py.**
- **Good:** default fills at the next bar's open, and a pessimistic order when stop and limit hit in the same bar (`backtesting.py:902`).
- **Flaws:** single asset; zero commission and spread by default; `margin` is a leverage multiplier; its Sharpe uses geometric annual return over a non-standard annualised volatility (admitted in `_stats.py:148-149`); 252/365 annualisation.

**backtrader.** Unmaintained since April 2023. Optional cheat-on-close and cheat-on-open. Its Sharpe analyzer defaults are inappropriate (F8). Float throughout.

**vectorbt.** Very fast parameter sweeps, and that speed makes overfitting easy (F9). Its defaults favour the strategy: same-bar close fills, zero fees and slippage, fractional size, 365-day year (F7, F8, F1). The Commons Clause restricts commercial use.

**zipline-reloaded.**
- **Good:** `VolumeShareSlippage` caps fills at 2.5% of bar volume, with quadratic price impact (`finance/slippage.py:40,241-270`). This is a useful liquidity guard for thin Indian small caps.
- **Flaws:** defaults are US-centric (US$0.001 per share commission).

**exchange_calendars (XBOM).** Its 2026 BSE holiday list (`exchange_calendar_xbom.py:453-472` plus 2026-01-15 at l.281) **matches our 16 NSE 2026 trading holidays exactly**. That independently corroborates our transcription (SECONDARY evidence for BSE). It has no settlement-holiday concept, fixed hours and no CAS (F4, F5), so it cannot replace `MarketCalendar`.

**quantstats.**
- **Good:** formulas mostly standard. Sortino divides by all periods, like ours. Infinities become NaN instead of being zero-filled.
- **Flaws:** see F8 and F9. Its PSR mixes pandas sample-adjusted skew and kurtosis into a formula derived with population moments. That matters only for small n.

**FinRL.** A gym environment where the agent's action is executed at the current close, and the reward is the next close's account value. The turbulence filter uses a 252-day covariance and the same day's return (`preprocessors.py:295-330`). Flaws: F7, F14, flat percentage costs (F1), and no statistical control over many RL runs (F9).

## 4. What we adopt (ideas, own implementation)

1. **Separate pluggable models**, as in Lean: legality (rules engine), cost (charges), settlement (calendar), fill (Phase 3) and financing (MTF ledger), all effective-dated.
2. **Intent before submission and tags for correlation**, as in OpenAlgo and hummingbot, done durably. Fix freqtrade's ordering: persist → submit → reconcile.
3. **Unknown outcome is a state, not a guess.** Keep a "lost" set that still accepts fills, as in hummingbot and nautilus with `RetainUnresolved`. Never assume an order was cancelled.
4. **Fill deduplication by exchange trade ID** and cumulative quantity checks.
5. **Position-break locks**, as in pysystemtrade.
6. **Look-ahead and recursive-indicator detectors**, as in freqtrade, in the Phase 5 harness.
7. **Opening-gap fills** (jesse) and **volume-capped fills** (zipline) in the Phase 3 fill model, labelled as assumptions.
8. **A PIT store with a revision chain**, as in qlib, in Phase 2.
9. **Fixed-point/Decimal value types**, as in nautilus and hummingbot.
10. **Cross-checks, not dependencies:** use exchange_calendars and quantstats to compare our numbers in tests if we ever install them. Our own definitions stay authoritative.

## 5. What we explicitly reject

- Web-login, cookie or stored-TOTP authentication (jugaad-trader).
- Leverage multipliers instead of MTF financing (OpenAlgo sandbox, Lean).
- Flat percentage cost models (most projects).
- Same-close or touch fills presented as facts.
- Any default risk-free rate of zero or any 252/365 annualisation.
- Forking a large platform wholesale (Build Guide §15).
