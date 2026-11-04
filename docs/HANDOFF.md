# Handoff

Updated 5 November 2026 (late) by Claude Fable 5.1 after the design session; earlier entries by Claude Opus 5.5.
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
