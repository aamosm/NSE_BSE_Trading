# Ready-to-paste prompts for the next jobs

Each prompt is self-contained. Paste it into the named model, working in `C:\Users\d_hru\try\tradebot\marketlab-integrity`
on branch `main`. Every one of them starts by reading CLAUDE.md, docs/audit/AUDIT_BRIEF.md and docs/ROADMAP_NEXT.md,
which carry the rules (read-only broker, no orders, no secrets, official hosts, sealed holdout, no LLM in decisions).

---

## 1. ~~Verify every split/bonus factor with Kite's adjusted candles~~ — DONE 7 Nov (`scripts/kite_factor_check.py`, 613/614 agree; the one miss is Kite's). Kept for re-running after new imports.

```
Read CLAUDE.md, docs/audit/AUDIT_BRIEF.md and docs/ROADMAP_NEXT.md (job 7) first.
Kite's daily candles under data/research/market/kite/day/<token>/*.json are adjusted by Zerodha for splits and
bonuses; the panel (data/research/market/panel.sqlite3, table bars) holds the exchange's actual prices. For every
corporate action with status RATIO_CONSISTENT in the registry (marketlab.action_registry.load_index(market, panel)),
map the stock to its Kite token via data/research/market/kite/instruments/selected-2026-11-06.json (by symbol, and
for renamed stocks by ISIN through the panel), then compute
    step = (bhav_close[t-1] / kite_close[t-1]) / (bhav_close[t] / kite_close[t])
across the ex-date t. It must equal the registry's price_factor (or its inverse; establish the convention on 5
known splits first and state it). Write scripts/kite_factor_check.py printing: actions checked, agree within 1%,
disagree (list them), not checkable (no token / no candles) with reasons. Exit 1 on any disagreement. Also report
any day where step departs from 1 by more than 2% with NO listed action (an unlisted adjustment). Do not change the
registry or any file under src/marketlab/quant/; propose fixes in a note. Commit the script with a test on a
synthetic fixture. End git commit messages with the attribution line the harness gives you.
```

## 2. Verified holiday calendars 2016–2024 — Claude Haiku 5.5 or Gemini 3.8 Flash (Opus 5.5 reviews)

```
Read CLAUDE.md and docs/ROADMAP_NEXT.md (job 6). The research calendar for 2016–2024 is reconstructed from what NSE
published (both bhavcopy formats; 8 special weekend sessions found). Upgrade each year to VERIFIED: find the NSE
holiday circular for trading holidays of each year 2016–2024 on nsearchives.nseindia.com (official host only, one
request per file; record a refusal instead of guessing a URL), add each to data/research/market/calendar_sources.json
as {"year", "source_id", "url"} in the existing format, and run
    marketlab --private-dir data/research/private --market-dir data/research/market panel-build
The pass condition is that the calendar report's cross_check shows no disagreement between the circular and the
observed publication for any year; list every disagreement you find instead of resolving it yourself.
```

## 3. The 1,000-trial randomized replay — Claude Fable 5 or Opus 5.5 (GPT reviews)

```
Read CLAUDE.md, docs/audit/AUDIT_BRIEF.md, docs/ROADMAP_NEXT.md and docs/BACKTEST_PLAN.md (all of it; section 0
says what already runs). Build `marketlab trials` and `marketlab trials-score` exactly as BACKTEST_PLAN sections
2-6 specify: build the dataset once and slice it per trial at the as-of instant T; reuse evaluate's purge/embargo
and the dated universe; per trial write a write-once file with its seed, T, stock list, information ledger (3c) and
every prediction; score in a separate pass; plan.json fixed before the first trial. The holdout window
(runs/registry holdout manifest, from 2025-11-04) is off limits: no T inside it. Add a planted-lookahead test (a
trial given one future row must be refused). Run blocks A-E overnight; report H1-H11 with CIs. Do not tune anything
from the results.
```

## 4. Independent review of the test design and of the bias fixes — GPT

```
You are reviewing, not editing. Read docs/BACKTEST_PLAN.md (section 0 first), docs/SPEC_ERRATA.md E19-E23,
src/marketlab/quant/baselines.py, src/marketlab/quant/evaluate.py (run_fold, summarize, strategy_metrics) and
src/marketlab/quant/ranking.py (forward_record, outcome_card). Questions: (1) Is there any path by which
information after a decision day reaches a decision, a quantity, or a baseline pick? (2) Do the baselines compare
like with like (universe, entry/exit prices, costs, invested fraction)? (3) Is the moving-block bootstrap
appropriate for the period dependence? (4) Is anything in E19-E23 overconfident or mis-specified? Report findings
with file:line and a concrete counterexample for each; the owner's rule is that a finding is closed only by a fix
with a regression test (tests/test_audit_findings.py), applied by a Claude strong model.
```

## 5. Dividends in the labels (H-CA1) — Claude Opus 5.5 / Fable 5

```
Read CLAUDE.md, docs/SPEC_ERRATA.md (E16, E17), docs/DATA_READINESS.md. Labels are price returns against the price
index; dividends are excluded on both sides, and labels around implied adjustments without a listed action are
EXCLUDED. The legacy (pre-Jul-2024) bhavcopies adjust PREVCLOSE on ex-dates (2,672 implied factors). Determine, from
the registry's 13,088 dividend actions and the implied factors, which dividend ex-dates NSE adjusted the base for,
and whether excluded labels are concentrated in dividend payers (a bias). Then propose, as a registered new candidate
version, total-return labels with a total-return benchmark (Nifty 50 TRI from NSE's index archive), with tests.
```
