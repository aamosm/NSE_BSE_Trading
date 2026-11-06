# External audit: the brief, its status, and who finishes each part

The owner's brief for the Indian trading-systems audit (started by a GPT agent in `C:\Users\d_hru\try\tradebot-india-audit`,
interrupted on 7 Nov 2026 at 00:19 IST) is kept verbatim at the end of this file. **Any agent working on the audit,
or on anything the audit touches, reads this file first.** CLAUDE.md points here.

## Read this before continuing (state as of 7 Nov 2026, 02:00 IST)

- **The frozen snapshot is out of date.** The audit tested commit `4555d368`. Since then `main` (= `research-ranking`)
  fixed every calculation and governance finding (commits `7891f99`, `521c77b`, `87ce283`) and changed the model (errata
  E19–E23 in docs/SPEC_ERRATA.md). Re-test against the newest `main`; record which commit each result is from.
- **One branch.** All first-party branches were contained in `research-ranking`; it is now `main`. No other branch
  carries unique work.
- The main project is no longer "read-only for the auditor because another agent edits it": the auditor still
  works in its own folder and proposes changes as patches or issues; a strong model applies them on `main`.

## Status of every item in the brief

| Brief item | Status | Where |
|---|---|---|
| NSE/BSE repos, courses and sites checked; useful ones kept | **Mostly done** (16 repos with dates, licences and traps; Unofficed lesson errors; shortlist drafted in "Inferences"). Final shortlist not written | docs/audit/repositories_data.md, courses_platforms.md |
| Real NSE/BSE data downloaded; useful tools implemented | **Done for NSE** in the app itself: official daily files, legacy bhavcopies 2016–2024 and index closes downloading, Kite history for every NSE equity. The audit's own 1-session intake sample is a second parser (cross-check job below). **BSE: not started** | docs/ROADMAP_NEXT.md jobs 1, 4, 5 |
| Does the project already use anything similar? | **Answered:** it implements the same data architecture itself (registered official sources, a narrow read-only Kite adapter on stdlib); none of the third-party libraries is imported | repositories_data.md, "Does marketlab-integrity already use these approaches?" |
| Comparison with the Zerodha API; is Zerodha better? | **Answered in draft:** Kite Connect (₹500/month, historical 3 req/s) vs Upstox, Dhan, Fyers, NSEPython. Different layers; no single winner; Zerodha is the right broker layer for this project | courses_platforms.md |
| Websites that already do the calculations | **Answered in draft:** Chartink, Streak / Kite CTB, StockEdge, Trendlyne, Screener.in, TradingView, with documented limits | courses_platforms.md |
| Are the project's calculations correct? | **Done and fixed.** The audit found 5 defects (median of an even count; `net_edge or -9` sorting; a crash on unaffordable stocks; restate reading a missing allocation; plus the governance items below). All fixed with regression tests (tests/test_audit_findings.py). An independent re-check of the arithmetic found zero mismatches on 1,804 forecasts | SPEC_ERRATA E19–E23, commit 87ce283 |
| Is BACKTEST_PLAN a sound test design? | **Open: needs an independent reviewer.** The plan's author (Claude) must not grade it | job A6 below |
| "No stock ever comes into priority" | **Done.** Three logic faults (E19 shrinkage, E20 tail limit on one position, E21 universe), plus two found by a second external review (E22 money vs excess return, E23 overconfident stock shrink). Result on 6 Nov: 0 buy candidates, 2 qualify, model avoids present. "Nothing qualifies" is now a measured outcome, not a bias | docs/START_HERE.md section 4 |
| "Loss" = real loss or underperformance vs Nifty? | **Answered: it was underperformance, used as if it were money lost.** Fixed by E22: the tail gate and exits use the stock's own return | SPEC_ERRATA E22 |
| Branch inventory | **Done.** `research-ranking` (now `main`) contains every first-party branch | this file |
| Promotion accepts an incomplete development report; horizon mismatch | **Fixed** (commit 87ce283), plus a third governance defect the brief did not name: trial ids ignored seed, bootstrap, step, holdout length and benchmark index | tests/test_audit_findings.py |
| Saved run vs testing doc describe different bootstrap settings | **Open, small:** reconcile BACKTEST_PLAN's stated bootstrap with `Config.bootstrap` (50) and the ranking's | job A7 |
| Unnamed GitHub traps (old BSE URL; silent empty data on NSE failure) | **Open:** recover the names from the audit's evidence/repos manifest | job A3 |
| Final report | **Open** | job A1 |

## Who should do each remaining audit job

Models named are those available to the owner; "strong" = Claude Fable 5 or Claude Opus 5.5. The rule that decides it:
a job whose error would silently bias results goes to a strong model or an independent reviewer; a job whose output is
checkable by a test or a citation goes to the cheapest model that can do it.

| # | Job | Entrust to | Why |
|---|---|---|---|
| A1 | Write the final audit report from the two notes plus this status table | **GPT** (the agent that started it; continuity, and a second vendor's view) | Synthesis of its own research; a strong Claude reviews the conclusions about the app |
| A2 | Final shortlist: verify maintenance, working URLs and failure handling for nsepython, jugaad-data, nsetools, bsedata, yfinance, kiteconnect, vectorbt, backtesting.py, quantstats, NseIndiaApi | **Claude Sonnet 5.5** (or GPT) with web research | Citable facts; checkable; no effect on results |
| A3 | Recover the two unnamed traps (old BSE URL; silent empty data on NSE failure) from `evidence/repos` | **Claude Haiku 5.5** or **Gemini 3.8 Flash** (free tier) | Reading saved files and extracting names |
| A4 | BSE: official bhavcopy backfill and a BSE-only universe check | Script written by **Sonnet 5.5**; a strong model reviews the universe rule | Mechanical download; the universe rule can bias results |
| A5 | Cross-check: the audit's independent parser (`src/data_pipeline.py`) against the app's parser on the same 5 Nov file | **Sonnet 5.5** | Pure comparison with a pass/fail count |
| A6 | Judge BACKTEST_PLAN as a test design | **GPT** or **Claude Fable 5** as an independent reviewer, not the plan's author | Self-review is not review |
| A7 | Reconcile bootstrap settings across docs, saved runs and code | **Haiku 5.5** | Text and config alignment |
| A8 | Re-verify the bias fixes (E19–E23) on the newest `main` | **GPT** (independent) | The second review already changed an answer once |
| A9 | Zerodha vs alternatives and competing sites: finish and date-stamp the tables | **GPT** or **Sonnet 5.5** | Already drafted with sources |
| A10 | Apply any code change the audit proposes | **Claude Opus 5.5 / Fable 5** on `main`, with a regression test per finding | Changes to labels, gates and the registry are where bias hides |

---

## The owner's brief (verbatim, 7 Nov 2026)

Handoff brief: Indian stock-trading audit (continue from GPT's interrupted run)

**Your task**

Continue and finish the audit started by a previous agent. Don't touch the main project folders, because another agent is
actively editing them.

The user wants:

- NSE and BSE repos on GitHub, courses and sites checked properly, and only the useful ones kept, with output that is easy to use.
- Real NSE/BSE data downloaded and the useful tools implemented.
- A statement of whether the project already uses anything similar.
- A comparison of those tools with the Zerodha API, and whether Zerodha is better.
- A list of websites that already do what the project does, calculation-wise.
- A check that the project's calculations are correct.
- A review of whether the testing doc (BACKTEST_PLAN) is a sound test design.
- An investigation of the apparent bias: "no stock ever comes into priority".
- A whole-repo check of which branches have the most and latest commits, and which folder they are in. Work on that branch and report any issues or bias.

Reference sources the user named:

- https://unofficed.com/blackbox/
- https://unofficed.com/courses/mastering-algotrading-beginners-guide-nsepython/
- https://github.com/maanavshah/stock-market-india
- "and many more", so find the best ones.

**Locations**

- Main project (read-only for you): C:\Users\d_hru\try\tradebot. It also contains reference_bots/ and several research folders.
- Audit sibling folder (work here): C:\Users\d_hru\try\tradebot-india-audit
  - Subfolders: research_notes/Indian trading systems audit, research_notes/Indian trading audit completion, reports, data, src, tests, evidence.
  - Notes that exist: courses_platforms.md and repositories_data.md.
  - Code that exists: src/data_pipeline.py (has a validate command), src/audit_ranking.py, and tests/test_data_pipeline.py.
  - Previous agent used a "deep-research" skill. Tests run with python -B -m unittest discover -s tests -v.

**System under audit**

- The user confirmed: audit marketlab-integrity, using its BACKTEST_PLAN and STOCK_RANKING docs.
- Most complete local version: branch research-ranking, with 48 commits. It includes the other first-party branches and is five commits ahead of GitHub.
- Frozen snapshot used for testing: commit 4555d368. The other agent keeps editing ranking and history files, so test against the snapshot and log live changes separately.

**Confirmed findings**

Ranking and bias

- The saved ranking reproduces independently. All 801 forecasts fail the net-return threshold, and 791 of them also fail the loss-risk threshold.
- Removing only the loss-risk check still selects nothing.
- A synthetic strong candidate does pass, so a stock reaching priority is possible. The empty list comes from the thresholds, estimated costs and conservative probability adjustments, not from a broken pipeline.
- The 801 forecasts are one day's cross-section of stocks, not 801 independent backtest trades. Don't read them as a sample of trade outcomes.

Defects and inconsistencies

- Two code defects were found, but the log doesn't say what they are. Check the evidence and reports folders.
- The saved run and the testing documentation describe different bootstrap settings.
- The latest code and the saved ranking files are out of sync. The ranking logic changed, but the saved outputs come from the earlier version.
- Validation (confirmed on the frozen commit): the promotion checks can accept an incomplete development report. A candidate can also claim a forecast horizon different from what its evidence supports. Regression checks were being added for both.

Reference material

- Unofficed lessons contain errors. One enters a "10%" risk-free rate as 10 instead of 0.10 in decimal-return calculations. Another calculates returns before sorting by date. Treat the lessons as teaching material, not formulas safe to reuse.
- maanavshah/stock-market-india is useful as historical reference only. Its default branch last changed in 2021, even though GitHub shows newer-looking activity dates.
- Other GitHub traps were found but not named. One library uses an old BSE download URL. Another returns empty data when an NSE download fails, with no error.
- NSE data was downloaded into the audit folder with source URLs and hashes. The log doesn't say which datasets. Check data/.

**Not finished or never stated in the log**

- No final report was written, and no final shortlist of repos or tools.
- No Zerodha comparison, and no list of competing websites.
- No answer on whether the project already uses similar tools.
- No verdict yet on the testing doc as a test design.
- Whether the "loss" measure means real portfolio loss or underperformance against Nifty was being checked, with no conclusion.
- The branch inventory, calculation review and NSE/BSE review sub-tasks had started but no results were shown.
- Repo and library names were mostly never stated. Only maanavshah/stock-market-india appears. The two traps above and the repo and data folders were all described without names. Recover them from research_notes/*.md first, then fill gaps.

**Unverified starting points (my suggestions, not from the log)**

These are common in this space, so check them against the notes before adding them: nsepython (named by the Unofficed course),
jugaad-data, nsetools, bsedata, yfinance, Zerodha's kiteconnect, vectorbt, backtesting.py, and the official NSE and BSE bhavcopy
archives. Verify each for maintenance status, working download URLs, and failure handling.
