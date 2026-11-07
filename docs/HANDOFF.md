# Handoff

## State on 7 Nov 2026 (Claude Opus 5.5, branch `main`) — read this section first

**Data.** Panel 1 Jan 2016 → 6 Nov 2026: 2,688 sessions, 4,795 securities (delisted included), zero calendar gaps;
legacy bhavcopies parsed with field-for-field parity to UDiFF on the overlap days (`scripts/legacy_parity.py`); 8
special weekend sessions found by probing; Nifty 50 levels on every session but 20 Jun 2016 (archive refused it).
Kite: every NSE equity's daily candles (5.8M) — used to verify the corporate-action registry, 613/614 split/bonus
factors agree (`scripts/kite_factor_check.py`; the one miss is Kite's). Panel backup before the load:
`data/research/market/panel.before-legacy.sqlite3`.

**Model and decisions.** Errata E19–E23 (two-part shrinkage with an out-of-sample cap; tail gate on capital using the
stock's own return; every EQ/BE share analysed); the second external review (docs/audit/REVIEW_2026-11-07.md): the
allocation pool uses the gates at the real quantity, every qualifying card shows its allocator utility against cash,
one portfolio bad-month budget, limits (min edge, tail) are owner filters. Open owner decision: objective
benchmark-relative (current) vs absolute-return (adds expected market drift; it turns the two 6 Nov qualifiers into buys).

**Testing.** Stages 1–4 built (BACKTEST_PLAN §0): `scripts/independent_check.py` (1,807 cards × 11 checks, 0
disagreements), walk-forward with baselines (model vs momentum vs 200 random vs Nifty, block-bootstrap CIs) and
strategy metrics, write-once forward outcomes. Extra criteria C1–C9 registered before any result (§0b). **Holdout
frozen** 4 Nov 2025 → 6 Nov 2026 (contamination stated in §0). The first registered walk-forward (A, h=20) is running:
`data/research/evaluate-A-h20.log`; its report lands in `data/research/runs/eval/`.

**Next.** docs/PROMPTS_NEXT.md (five ready prompts with models) and docs/ROADMAP_NEXT.md. Owner-only: register the
nightly task (`scripts/daily_update.cmd`), Kite logins, the objective decision, cleanup commands in
docs/audit/AUDIT_BRIEF.md's predecessor message (remote branches, two redundant folders).

## Research ranking, explanations and AI commentary (Claude Opus 5.5, 5 Nov 2026, branch `research-ranking` on `2909474`)

Worktree `C:\Users\d_hru\try\tradebot\marketlab-integrity`. Research data lives in `data/research/` (git-ignored):
- `market/`: official NSE files from 3 Jul 2024 to 5 Nov 2026, the 582-session panel and `actions.sqlite3`;
- `documents/`: holiday circular and Infosys filings;
- `corporate-actions-2026/`: one 2026 API response with its manifest;
- `private/` and `runs/`.

**Delivered**
- **Corporate actions.**
  - `action_registry` imports NSE corporate-actions API files with their hashes verified against the manifest. Your 2016–2025 folder gave 22,499 rows after removing 12 exact duplicates. One request with MarketLab's own user agent fetched 1,929 rows for 2026.
  - The parser now leaves 16 of 21,281 EQ subjects unparsed, down from 8,999. It handles the `/-` and `Re` forms, "Plus Special", "INCLUDING" (not double counted), `FV SPLT FRM`, preference-share bonuses (no equity factor), AGM/EGM typos and "Purposed Revised".
  - Dividends are deduplicated, and a revised purpose supersedes the original.
  - `reconcile` checks panel jumps against the registry. All 200 listed splits and bonuses in the window match their jumps. 194 of 898 price discontinuities and 110 of 156 ISIN changes are explained; the rest stay excluded.
  - NSE's API `isin` is often the pre-split ISIN (1,189 cases), so it is kept for comparison only.
- **Features (E17):** listed factors correct the ex-date return and earlier price levels. A new ISIN created by a listed split inherits its predecessor's history. Nothing changes without the registry.
- **Ranking (E18):** `quant/ranking.py` (RANK.v1), `marketlab rank`, the `rank` request kind, write-once `runs/rankings/<day>/<digest>.json` files and forward-evidence status. `decide.fit_today` is now shared by the decision and the ranking.
- **Explanations:** `explain.py` holds the glossary (41 terms), feature meanings, class rules, the per-stock narrative, the "what the numbers mean together" rules, the 15-stage How-it-works pipeline with live status, and today's summary. All of it is fixed templates over computed numbers.
- **AI commentary:** `ai_explain.py`, owner decision recorded in CLAUDE.md, details in `docs/AI_EXPLAINER.md`.
  - Prices were verified on 5 Nov 2026 and recorded in `researcher/budget.py`.
  - Each call reserves its worst case, is refused if that breaks a cap, and is then settled per attempt.
  - The key is kept in memory or in the private env file and is never echoed.
  - The context is the card only. Numbers in an answer that are not on the card are flagged.
  - Answers are stored as labelled commentary in `runs/ai/`.
- **UI:**
  - new Stocks tab (summary, class tiles, filter, sort and search table, per-stock sheet with range, contribution, cost and price charts, insights, step-by-step explanation, feature table, eligibility checks and Ask AI);
  - How it works tab; AI settings and the Rank job under Controls & AI;
  - light/dark theme toggle; SW `marketlab-shell-v4`.
- **Calendar:** `sources.load_calendar_for` reads an optional `calendar_sources.json`. Stored circulars become verified years and the rest is reconstructed from publication. The research folder uses it: 2025 from NSE/CMTR/65587, 2026 built in, 2024 observed.

**First real ranking (close of 5 Nov 2026, forward-eligible):**
- 0 buy candidates, 10 hold off, 791 high risk, 60 avoid (all exchange flags), 110 no forecast, 2,487 not eligible.
- Why: the median typical 20-session move is ±11.5% against an 8% tail limit. After shrinkage the forecasts lie within ±0.16% (the model keeps 12% of each forecast with 311 training dates), while a round trip costs about 0.76%.

**Verify:** `PYTHONPATH="src;tests" .venv/Scripts/python.exe -m pytest -q tests/test_ranking.py tests/test_action_registry_api.py tests/test_ai_explain.py tests/test_dashboard_render.py tests/test_corporate_action_registry.py`. The Node render test is skipped without Node. Then view the research folder with `marketlab --private-dir data/research/private --market-dir data/research/market dashboard --port 8770`.

**Known:** `tests/test_researcher.py::test_rate_limit_is_released_and_retried_auth_is_final` also fails on the unmodified `2909474`, so it predates this branch and was left untouched.

**Left (in order):**
1. Backfill about 3 more years: legacy-format bhavcopies before 8 Jul 2024 and the 2020–2024 holiday circulars, needed for the registered evaluation's 1,376 sessions.
2. Freeze the holdout, run walk-forward trials and apply the promotion rule.
3. Twelve weeks of forward paper observation; rankings recorded before each open are scored by `ranking.forward_record`.
4. Dividend-adjusted bases (H-CA1): 15,778 labels are still excluded as UNEXPLAINED_PRICE_ADJUSTMENT.
5. The 46 unexplained ISIN changes.
6. A daily scheduled ranking job.
7. Reconcile charges with a real contract note.

## Historical pilot (Claude Opus 5.5, 5 Nov 2026, branch `historical-pilot` on `integrity-replay`)

Bounded NSE pilot for January–July 2025 from official archives, plus the format-transition check (3–5 Jul 2024) and the reconstructed Infosys Q4 FY25 case. Results are in `docs/pilot/PILOT_2025.md`, the immutable manifest in `docs/pilot/nse_2025_manifest.json` (SHA-256 `93501484…`), and the questions for GPT in `docs/pilot/GPT_SOURCE_QUESTIONS.md`. The data stays in `data/pilot/nse_2025` (git-ignored). The holdout was not frozen.

**Headline:** exchange base prices are not adjusted on 2025 ex-dates, and splits change ISINs. The implied-factor method therefore misses actions. Detection and exclusion are implemented (`docs/SPEC_ERRATA.md` E16), and an official action history is now the critical source.

**Verify:** `pytest tests/test_history_pilot.py tests/test_replay_correctness.py tests/test_quant_pipeline.py -q` from the worktree, then `python scripts/pilot_report.py data/pilot/nse_2025 2025-01-01 2025-07-31`. The second command verifies the manifest and writes the next report version.

---


## Integrity and replay repair (Claude Opus 5.5, 5 Nov 2026)

Branch `integrity-replay` (worktree `C:\Users\d_hru\try\tradebot\marketlab-integrity`), made from `114589a`, the commit GPT reviewed (`MarketLab_Quant_Guild_Review.md`). `cash-research-reset` has not been touched. Nothing has been pushed.

| Commit | Checkpoint |
| --- | --- |
| `4bde0d5` | A: dashboard and decision integrity |
| `574226d` | B: replay correctness |
| (docs commit) | this section, `docs/SPEC_ERRATA.md`, validation record, setup commands |

**A. Decisions and the dashboard (what changed)**
- Every decision attempt is recorded through `decisions.record`, under one `decision_id`. This covers the scheduler's daily check, `marketlab decide` and Controls → Decide, and includes early WAITs. The full record is `runs/decisions/<id>.json`, written once. The evidence timeline and the dashboard's "latest decision" carry the same id and the record's SHA-256. Diagnostics computed without a promotion go to `runs/diagnostics/<id>.json`.
- Candidates dispatch through `quant/candidates.py`. B and C are refused as UNIMPLEMENTED everywhere. Horizons (A: 20, 60) and ablations are limited to the spec 8.5 registry. Reports name the feature builder, its columns and the event records used (0).
- The effective policy (`Policy.from_owner`) reaches the allocator in decisions and evaluations. K and the cap follow the spec 5.4 tier unless the owner sets them, and the risk multiplier sets γ. The policy is persisted with every decision and included in the trial id. A 25% cap makes every position ≤ ₹2,500.
- `--promoted` is gone. Only a verified record in `runs/promotions` can produce PAPER_PLAN: it must re-hash its development and holdout reports and match the policy digest. None exists, so every decision is WAIT.
- Health is derived from timestamps. The dashboard shows the scheduler's last tick against its interval, any current silence, the market session, whether broker reads are due, cash usability and paper eligibility. An unchecked calendar cross-check is shown as unchecked. STALE and SESSION_UNKNOWN account sections are never shown as "none today", and each section has its own receipt time. The paper card has no constant figures, blockers are derived, and listings are split into recent and upcoming with their route.
- A request left RUNNING by a dead scheduler becomes INTERRUPTED. File and panel jobs are retried once under the same id; decide and evaluate are not.

**B. Replay (what changed)**
- Sessions come from the calendar. A missing stored session is a data gap: the label is DATA_GAP (never stretched), a fill on it is cancelled and an exit on it is blocked. Years without a calendar are PANEL_ONLY.
- The screen builds the opportunity set first, from the entry session's rule files and that day's names. Labels attached afterwards never remove an opportunity.
- Labels are gross. Unlisted implied factors and unchecked days exclude a window. Costs are counted once, at the whole-share quantity, with exact charges.
- Ledger and EXEC.v1 (`quant/ledger.py`, `quant/replay.py`):
  - intents are frozen after the close; funds are blocked at a limit of C_D × 1.05;
  - outcomes are a fill, REJECTED_GAP, FILL_DEFERRED then ENTRY_FAILED after 3 deferrals, or CANCELLED_DATA_GAP;
  - EXIT.v1 reviews with re-forecasts; a blocked exit carries outcome bounds;
  - T+1 unsettled proceeds, corporate actions on units held, daily NAV, and liquidation value at the fold end.
- The live decision uses the replay dataset's own rows. A NaN feature stays missing, so the decision abstains.
- The holdout is frozen once (`freeze-holdout`). Development runs see the panel only up to the day before it. Every run writes a new immutable report, and the holdout can be evaluated once per trial.
- Every spec 8.6 criterion is computed: PBO, DSR on N_eff, MinTRL, concentration, stresses, calibration, attribution and holdout. Missing evidence gives INSUFFICIENT EVIDENCE.
- Spec inconsistencies resolved here, listed in `docs/SPEC_ERRATA.md`: slippage was double-counted, and the market order became a limit order.

**Verify (targeted; synthetic fixtures, no network, no account)**

    .\.venv\Scripts\python.exe -m pytest tests/test_decision_integrity.py tests/test_replay_correctness.py tests/test_quant_pipeline.py tests/test_quant_core.py tests/test_service.py tests/test_webapp.py tests/test_webapp_ui.py -q

Run it from the worktree. The venv's editable install points at the main checkout, so run pytest from the worktree root, where `pythonpath = src` takes precedence. Results are in `docs/validation/2026-11-05_integrity_replay.txt`.

**Hand-traceable cases (all in `tests/test_replay_correctness.py`)**

| Case | Expected result |
| --- | --- |
| Flat market, 20 × ₹250 → ₹260 | buy ₹5,005.00, sell ₹5,194.80, gross ₹200.00, slippage ₹10.20, charges ₹26.48 (DP ₹15.34). Net ₹163.32 = 200 − 10.20 − 26.48 |
| Same move, 2 shares | net ₹1.52 (0.30%) |
| Falling market (stock −1%, index −5%) | active log return +4.12%, net −₹86.41 |
| Whole-share check, ₹2,100 a share at μ̃ 0.86% | the gate at ₹5,000 passes; 2 shares have a net edge of 0.0821% < 0.10%, so no trade |

**Remaining blockers**
1. **Backfill not done.** A first development fold needs 750 + 125 + 250 sessions plus 251 sessions of feature history. Then run `freeze-holdout`, once.
2. **Rule files and calendar years before 2025/2022/2026 do not exist locally.** Historical folds are therefore eligibility-unverified or PANEL_ONLY, and cannot support promotion until REG1_IND and sec_list archives and per-year NSE holiday lists are loaded.
3. **No corporate-action history.** Every window with an implied factor is excluded until listed actions exist (H-CA1 is still open).
4. **No forward paper ledger.** A promoted plan would still be WAIT (FORWARD_PAPER_LEDGER_NOT_BUILT). The replay ledger is the smallest complete version, and the forward one should reuse it.
5. Not addressed on this branch:
   - the collector still writes schema-failing HTTP 200 payloads to the canonical path (review: quarantine and atomic promote);
   - the research validator does not prove that amount, unit and period match the cited passage;
   - sale-proceeds timing (E4) and the 5% limit (E3) are defaults that need the owner's or GPT's confirmation.
6. Real-data check, run on a copy of `data/market` only:
   - `panel-build`, `screen` and `decide` work: `decide` gives a persisted WAIT with an id;
   - `freeze-holdout` refuses (HOLDOUT_TOO_EARLY): the calendar shows 4 sessions between the 2 stored days, so 2 days are missing;
   - `evaluate` refuses (HOLDOUT_NOT_FROZEN); candidate B refuses (UNIMPLEMENTED).

---

Earlier entries follow. They were updated on 5 November 2026 (late) by Claude Fable 5.1 after the design session, with entries before that by Claude Opus 5.5.
- **Branch:** `cash-research-reset`, on top of `3513d33`. Pushing to GitHub is the owner's call.
- **Privacy:** no account identifiers, tokens or balances appear in this file. The research-provider key that was pasted into chat has been **removed** from the env file; the provider itself was removed by owner decision.

## Scope

- Cash-only NSE/BSE research and paper decisions. Read-only Kite; simulated execution only.
- Laptop first; private server plus phone PWA later.
- No MTF, borrowing, shorting, derivatives, orders or live switch.

## What this session delivered (Fable 5.1)

1. **`docs/FABLE_SESSION_1_SPEC.md`**: the frozen design (forecasting and allocation mathematics, evaluation plan, reliability rule, function contracts with every worked number recomputed by script). Key findings: at ₹10,000 the fixed DP charge makes the optimal number of simultaneous positions about one; the minimum detectable 20-session net edge after the backfill is about 0.66%; a forecast must be both strong and precise to pass the gate (e.g. 3% ± 0.5%, not 1.5% ± 0.6%).
2. **`src/marketlab/quant/`**: the implementation of those contracts, tested against the spec's numbers (panel, universe screen, labels with exchange-implied factors, feature set A, ridge + split-conformal forecasts, shrinkage, integer fixed-cost allocator, EXIT.v1, purged walk-forward with locked holdout, promotion rule, CUSUM, reliability).
3. **Calendar from NSE's holiday APIs** with circular-sourced overrides and a cross-check; no year is hard-coded any more.
4. **Perplexity removed**; provider contract, budget ledger, evidence schema, templates and queue kept for a future adapter.
5. **Dashboard** at `http://127.0.0.1:8765` with Data, Universe, Forecasts, Evaluation, Research and Controls tabs; bounded policy editing; job requests executed by the scheduler.

## Commits (this branch, newest first)

| Commit | What |
| --- | --- |
| dashboard commit | Tabbed localhost UI, new read/write endpoints, scheduler request execution, policy file |
| `45a956f` | Calendar years from the NSE holiday APIs; Perplexity adapters removed |
| `83bb124` | Quant core: panel, universe, labels, features, ridge-conformal forecast, allocator, evaluation |
| `15e6956` | Fable session 1: frozen design specification v1 |
| `198906c` | Fable session 1 bundle: prep document, reading list, owner's prompt |
| `660770f` | Laptop operation: measured EOD timing, catch-up, late start, gaps, freshness |
| `62e31e5` | Research service: budgeted adapters (since removed), evidence schema, queue, replay |
| `5eec923` | Band-change files dated by the session they take effect in |
| `19db166` … `2d53906` | Milestone 1 (see git log): chronology, login, costs, Muhurat, corporate actions, public data, scheduler, phone app, deployment kit, calendar cross-check |

## Verified on this laptop (Windows 11, Python 3.13.7)

Targeted tests, run after each change (final runs all passed): `test_quant_core` (26 hand-worked checks), `test_quant_pipeline` (synthetic panel: factors, labels, features, screen, purge, walk-forward report, holdout separation), `test_calendar_sessions` (API-built years, discrepancies, fallback), `test_researcher`, `test_service`, `test_login_flow`, `test_public_data`, `test_muhurat_2026`, `test_engine`, `test_webapp`, `test_webapp_ui`, `test_boundaries`.

Real data (read-only): `panel-build` loaded the two stored sessions (3,493 ISINs, 167 index rows, **0** implied factors with both days correctly marked unchecked because their previous sessions are not stored); `screen`/`decide` report INSUFFICIENT_HISTORY as they should; every dashboard endpoint returned 200 on the real folders and the Data tab lists the 19 missing bhavcopy sessions of the last 30 days from the loaded calendar.

Not run: the historical backfill, any evaluation on real data (none is possible yet), the server, the phone login.

## Remaining blockers

1. **Historical backfill not done** (bhavcopy 2016→, sec_list 2022→, REG1_IND 2025→, index closes 2020→). Without it no forecast can be fitted and no trial evaluated. The old-format bhavcopy parser (pre-July 2024) is not written.
2. **Hypothesis H-CA1** (does NSE adjust the base price for cash dividends?) unverified: labels omit dividends until then.
3. **No promoted candidate**, so every decision is WAIT. That is correct until spec §8 has been run.
4. **Family B/C** have no history; event collection runs prospectively from 5 Nov 2026.
5. Unchanged from milestone 1: contract-note reconciliation; BSE calendar; 2027 calendar (will load automatically once NSE publishes it); MIS list; paper ledger with reservations; server not provisioned.

## Next work (for the lower-cost implementation models), in order

1. **Backfill** (`sources.collect` per trading date, 1.5 s apart, resumable through the catalog): NSE UDiFF bhavcopy from 5 Jul 2024, then the old format from 2016 with a new parser mapped to the same columns; `nse_indices_close` from 2 Jan 2020; `sec_list` from 2022; `REG1_IND` from Jan 2025. Then `panel-build`.
2. **H-CA1 check**: for 10 known splits/bonuses/dividends, compare `implied_factors` with the official ratios (spec §2.4). Record the result in `DATA_READINESS.md`.
3. **Run the registered trials** (spec §8.5): `marketlab evaluate --candidate A --h 20`, `--h 60`, and the three ablations with `--ablate`. Do **not** pass `--holdout` until everything else is final. Write one model card per trial; apply `evaluate.promotion` with the registered trial count and the stress runs.
4. **Event registry** for family B from the NSE RSS feeds (reaction session R, features of spec §3.4).
5. **Paper ledger** with cash reservations and deferred fills; wire `decide` output into it only after a promotion.

## Owner actions

1. Change the Zerodha password (typed into an earlier chat). The Perplexity key was also exposed; it is no longer used anywhere here, but revoke it in the Perplexity console.
2. Start the dashboard and scheduler (`deploy\windows\register_tasks.ps1` or by hand, below) and log in each trading morning before about 08:30.
3. Push when you want a review: `git push origin cash-research-reset`.
4. Decide the capital figure for research (the spec's economics are much better at ₹1 lakh); set it in Controls → Policy. It changes only simulations.

## Commands (laptop)

```powershell
.\.venv\Scripts\python.exe -m marketlab auth
.\.venv\Scripts\python.exe -m marketlab run --symbols NSE:INFY NSE:TCS      # scheduler; executes dashboard requests
.\.venv\Scripts\python.exe -m marketlab dashboard                          # http://127.0.0.1:8765
.\.venv\Scripts\python.exe -m marketlab fetch-public --date 2026-11-04
.\.venv\Scripts\python.exe -m marketlab panel-build
.\.venv\Scripts\python.exe -m marketlab screen --date 2026-11-04
.\.venv\Scripts\python.exe -m marketlab evaluate --candidate A --h 20       # after the backfill
.\.venv\Scripts\python.exe -m marketlab decide --candidate A --h 20         # WAIT until promoted
.\.venv\Scripts\python.exe -m marketlab verify-calendar --year 2026
```
