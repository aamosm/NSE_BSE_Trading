# Roadmap

Status 5 November 2026. This file follows the consolidated handoff (`CLAUDE_MASTER_HANDOFF_2026-11-04.md`, kept outside the repository).
- **Scope:** server hosting and a phone app; cash-only, read-only broker access, simulated execution.
- **Order of work:** foundations, then data, then design, then implementation, then paper observation, then audit.

## 1. Done in milestone 1 (commits `2d53906`..`d7383b4`)

- **Foundations** (handoff §3), all five findings addressed (`docs/RESET_REVIEW.md`):
  - snapshot chronology;
  - coherent decision time and BSE fee group from listing data;
  - login state/path/deadlines/error labels;
  - corporate-action series separation;
  - day-level STT with explicit stamp and DP status.
- **Calendars:** Muhurat 2026 session and settlement tables; NSE 2026 holidays verified against NSE's APIs.
- **Data collection (start):** a source register and polite collector for 15 official files; security master; a daily `InstrumentSnapshot` builder with provenance.
- **Service:** calendar-driven scheduler with health states, breakers, pause, heartbeat and alerts.
- **Phone app:** private PWA with the official login callback; actual and simulated accounts kept separate.
- **Deployment preparation:** systemd units, provisioning, pinned releases, rollback, encrypted backups, `DEPLOYMENT.md`.

## 2. Next, in order

1. **Owner deploys the server** (`DEPLOYMENT.md` §3). The phone login is the end-to-end check of the redirect.
2. **Historical backfill** (resumable, throttled, catalogued):
   - NSE UDiFF bhavcopies from Jul 2024;
   - old-format bhavcopies from 2016, with a new parser;
   - sec_list from 2022 and REG1_IND from 2025;
   - index closes from 2020;
   - BSE bhavcopies from Jul 2024.
3. **Corporate actions:**
   - locate and collect the official history;
   - reconcile five representative actions between Kite history and bhavcopy (`corporate_actions.reconcile_provider`);
   - build derived total-return series.
4. **Cost reconciliation** against one real contract note and funds statement, done locally by the owner. Never committed.
5. **Earnings-event data path** for one liquid stock: announcement timestamps, filing links and the price reaction. The RSS feeds started on 5 Nov.
6. **Refresh `DATA_READINESS.md` and `FABLE_HANDOFF.md`** with real coverage. Then GPT checks the bundle.
7. **Fable session 1:** design freeze. **Brought forward by the owner on 5 Nov 2026 as design-only**, using `docs/FABLE_SESSION_1_PREP.md`. Its data-dependent parameters are re-checked after the backfill (step 2).
8. **Claude implements the frozen specification:**
   - REPLAY and FORWARD_PAPER adapters around one decision engine;
   - the paper cash ledger and reservations (R03, R06, R07);
   - an integer allocator;
   - a replay harness with failure cases;
   - preregistered comparisons.
9. **Prospective paper observation**, recorded daily.
10. **Fable session 2:** evidence audit (CONTINUE PAPER / REJECT / INSUFFICIENT EVIDENCE).

**Not planned:** live trading. It would need a separate project decision.

## 3. Using Fable twice

Fable is used only where wrong reasoning is expensive and hard to detect.

- **Session 1, design freeze**, after step 6.
  - Prompt: `prompts/02_FABLE_SESSION_1_DESIGN.txt`.
  - Bundle: `docs/FABLE_HANDOFF.md`, `docs/DATA_READINESS.md`, `docs/FABLE_MATH_SPEC.md`, `docs/RESEARCH_BRIEF.md`.
  - Output: exact labels and horizons; at most 6 first-cycle candidates including controls; dependence-aware evaluation with pass/fail rules; an integer allocation with fixed fees and shared cash; hand-worked numeric examples.
  - INSUFFICIENT DATA is allowed.
- **Session 2, evidence audit**, after steps 8–9.
  - Prompt: `prompts/05_FABLE_SESSION_2_AUDIT.txt`.
  - Bundle: the frozen design, deviations, complete trial registry, results, failures and abstentions, coverage, reproducibility hashes and review findings.

Use Fable at its highest available reasoning setting for both. Everything else goes to Claude (implementation) and GPT (review, sources, planning).

## 4. Questions for GPT (sources and review)

1. Where is NSE's official corporate-action history retrievable without bypassing controls, and in what format: ratios, record dates, payment dates?
2. The documented meaning of the REG1_IND columns, especially `Status` and `ICA`, and their effective timing.
3. Confirmation that sec_list/REG1_IND dated D describe session D+1 (our observation from three series changes).
4. Zerodha's MIS square-off time on Muhurat days.
5. The 2027 NSE calendar circular (when published); BSE's 2026/2027 trading and settlement holiday notices.
6. The final (not draft) STT rules on aggregation per client, security and day.
