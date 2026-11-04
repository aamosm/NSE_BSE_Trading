# Roadmap

Status 5 November 2026 (after Fable session 1). Scope: laptop first, then a private server and phone app; cash-only, read-only broker access, simulated execution. The design is frozen in `docs/FABLE_SESSION_1_SPEC.md`; this file orders the work.

## 1. Done

- **Milestone 1** (commits `2d53906`..`19db166`): foundation corrections, official-file collection, security master and daily rule inputs, scheduler, phone app, deployment kit.
- **Research service plumbing** (`62e31e5`): evidence schema, budget ledger, queue, templates, replay. Provider: none (Perplexity removed by owner decision, `45a956f`).
- **Fable session 1** (`15e6956`): forecasting/allocation mathematics, evaluation plan, reliability rule, contracts with worked numbers.
- **Quant core** (`83bb124`): the spec's contracts implemented and tested; CLI `panel-build`, `screen`, `evaluate`, `decide`.
- **Calendar from APIs** (`45a956f`): years built from NSE's holiday masters; circular facts as cited overrides.
- **Dashboard** (latest commit): Data, Universe, Forecasts, Evaluation, Research, Controls.

## 2. Next, in order

1. **Historical backfill** (lower-cost models): UDiFF bhavcopies from Jul 2024; old-format bhavcopies from 2016 with a new parser; index closes from 2020; sec_list from 2022; REG1_IND from 2025. Resumable, 1.5 s between requests, every attempt catalogued. Then `panel-build`.
2. **H-CA1 verification** (spec §2.4) and the official corporate-action history route (search request).
3. **Registered trials** (spec §8.5) on the backfilled panel: T0–T4 plus three ablations; model cards; promotion rule with the registered trial count and stresses; the holdout opened once, last.
4. **Prospective event registry** for family B from the NSE feeds.
5. **Paper ledger** with cash reservations, deferred fills and reconciliation; FORWARD_PAPER adapter; monitoring (spec §7).
6. **Server and phone** (`docs/DEPLOYMENT.md`) when the owner provisions it.
7. **Fable session 2**: evidence audit after ≥ 12 weeks and ≥ 30 resolved paper trades.

**Not planned:** live trading. It would need a separate project decision.

## 3. Fable

Session 1 is spent (design-only). Session 2 is the audit: the frozen spec, deviations, the complete trial registry, results, failures and abstentions, coverage, reproducibility hashes and review findings; verdict CONTINUE PAPER / REJECT / INSUFFICIENT EVIDENCE by spec §8.6.

## 4. Questions for GPT (sources)

1. NSE's base-price adjustment rule on ex-dates (cash dividends included?) — decides H-CA1.
2. An official NSE corporate-action history route with ratios, record and payment dates.
3. An NSE corporate-announcement archive route (historical results timestamps) for family B.
4. The archive of `ind_nifty500list.csv` (dated industry membership) for sector caps.
5. REG1_IND field definitions (`Status`, `ICA`).
