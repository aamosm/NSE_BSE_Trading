# Handoff

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
