# The 1,000-trial randomized replay: does this model know anything?

**Status: specified, not built.** This document is the design another model implements. It answers one question
with evidence instead of argument: *when the model is shown only what was knowable on a past date, do the
predictions it makes about random stocks match what those stocks actually did?*

Nothing in this plan is a strategy change. It measures the model that exists (ridge over 14 features, separate shrinkage of the market and
stock parts (E19), split-conformal intervals, exact costs, two gates with the tail gate on capital (E20)). Section 9 says what happens if the answer is "no".

---

## 1. Where the evidence stands (6 Nov 2026)

**The arithmetic is exact.** All 801 forecast stocks of the 5 Nov ranking reproduce from the stored model with zero
mismatches (β·x, shrinkage, contributions, Zerodha charges, both gates). The suite passes.

**A first, thin out-of-sample measurement exists.** The model's own calibration window (8 Jul–6 Oct 2026, purged
from training, 50,324 stock-days) gives:

| Measure | Value | Why it is not yet proof |
|---|---|---|
| Daily IC, stock-specific forecast vs realized 20-session excess return | +0.13 mean, positive on 63 of 63 dates | 63 dates overlap: only **4** independent 20-session periods |
| Mean realized excess return by predicted decile (worst → best) | −2.31, −1.79, −1.34, −1.37, −0.67, −0.91, +0.12, +0.44, +1.27, +0.75 % | One regime, three months; λ was chosen on this window |
| Top-minus-bottom decile | +3.06% per 20 sessions | Against a 0.56–0.76% round trip, but before shrinkage and on gross returns |

The same diagnosis found two logic faults, now fixed (errata E19, E20): one bootstrap se for the whole forecast let
the market-timing uncertainty crush the stock signal (shrink 0.12 instead of 0.53), and the tail limit was applied
to a single position instead of the account (18 of 801 stocks could pass). Both changed what the model *says*;
neither changed what it *knows*. This plan measures what it knows.

**Target figures this plan must beat or refute** (registered now, before any trial runs):

| Hypothesis | Pass if (over all block-A trials, bootstrap CI over trials) | If it fails |
|---|---|---|
| H1 signal exists | mean IC of μ̃ > 0.02 and its 95% CI excludes 0 | The model has no edge at h = 20; stop tuning it |
| H2 signal pays | top-minus-bottom decile, net of each stock's own costs at ₹30,000, > 0 with CI excluding 0 | Real but untradeable at retail size |
| H3 monotone | Spearman of decile means vs decile number ≥ 0.8 in ≥ 70% of trials | Two lucky ends, not a ranking |
| H4 calibrated range | outcomes below q10 in 7–13% of stock-days, above q90 in 7–13% | Tail gate and ranges are wrong: fix calibration before anything else |
| H5 shrinkage honest | slope of realized excess on μ̃ in [0.5, 1.5] | μ̃ is too timid (> 1.5) or too bold (< 0.5) |
| H6 classes mean something | mean realized excess: buy/qualifies > hold off > high risk > avoid, after costs | The labels are decoration |
| H7 market timing is noise | IC of the common part (time series of μ_common vs universe excess) ≈ 0 | If it has skill, shrink it less |
| H8 history helps | IC with 1,000+ sessions of training ≥ IC with 300 | The backfill was not the constraint |
| H9 entry gap does not eat the edge | realized excess of buy candidates bucketed by next-open gap (< 0%, 0–2%, 2–5%): no bucket below 0 after costs | Condition the entry on the gap (a tighter limit), or the forecast on it |
| H10 money range calibrated (E22) | the stock's own return below q10_abs in 7–13% of stock-days | The tail gate measures the wrong risk |
| H11 slope cap is honest (E23) | the realized slope on μ̃'s stock part in later trials ≥ 0.5 × the calibration slope used | The cap is still too generous; shrink more |

## 2. What one trial is

A trial is a point-in-time replay:

1. Pick an **as-of instant** `T` (after a session close, before the next open).
2. Build the model using **only rows whose labels resolved by `T`** — training, calibration, screen inputs and
   corporate-action knowledge all cut at `T`.
3. Ask it for predictions on a **sample of stocks** `S` eligible at `T`.
4. Record every prediction *before* looking at any later data: μ̂, se, μ̃, σ̂, q10/q50/q90, class, both gates,
   costs at the trial's capital, and the rank.
5. Later-in-the-data: compute what actually happened to each stock in `S` over the next `h = 20` sessions —
   realized excess log return over the Nifty 50, net of the same cost model.
6. Score the prediction against the outcome.

One trial yields ~100 (prediction, outcome) pairs. 1,000 trials yield ~100,000 — enough to measure a signal of
the size this model could plausibly have, and enough to say "it is zero" with authority if it is.

**Purging and embargo.** A 20-session label overlaps the next 20 sessions of data. Training rows whose label
window crosses `T` must be dropped (purged), and a 20-session embargo applied before `T`, or the model is
scored partly on data it trained on. This is the single most common way a backtest lies. `evaluate.walk_forward`
already implements purge + embargo; the trial runner must reuse it, not reimplement it.

## 3. The 1,000 trials

Five blocks. The split exists so that a result can be attributed: a bad score in block A could be the dates, the
stocks or the model, and blocks B and C separate those.

| Block | n | What varies | What it isolates | What it answers |
|---|---|---|---|---|
| A — baseline | 400 | random `T` × random 100 stocks | — | Does the model have an edge on average? |
| B — fixed cohort | 150 | random `T`, **same** 100 stocks throughout | date and regime effects | Is the edge there in all markets, or only some? |
| C — fixed date | 150 | **same** `T` (10 dates × 15 samples), random stocks | sampling noise | How much of a single day's result is luck? |
| D — ablations | 200 | information removed on purpose | each input's value | Which data is actually earning its keep? |
| E — adversarial | 100 | deliberately hard cases | failure modes | Where does it break, and does it know it? |

**Sampling rules.** `T` is drawn from the panel's sessions, stratified into three equal buckets by the Nifty 50's
trailing 20-session volatility at `T`, so calm, normal and turbulent markets are equally represented rather than
whatever the sample happens to give. Stock samples are drawn from the stocks *eligible at `T`* (not today's
universe — that is survivorship bias), stratified by liquidity tercile. Every draw comes from one seed per trial,
recorded in the trial file, so any trial can be re-run exactly.

**Block D ablations** (40 trials each, matched `T` and `S` against block A so the difference is the ablation):

| Ablation | Hypothesis being tested |
|---|---|
| History length: 250 / 500 / 1,000 / all sessions | The backfill's actual value. If 1,000 sessions does not beat 500, three years of download was not the constraint. |
| Feature-group dropout (momentum, reversal, volatility, liquidity, market) | Which of the 14 features carry the signal, and whether any is pure noise. |
| Corporate-action registry off | Whether the split/bonus correction improves predictions or merely changes them. |
| **Corporate-action registry as-of vs full** | Lookahead check: the registry we imported in Nov 2026 contains actions announced *after* most as-of dates. Restating a 2025 price with a 2026 announcement is mild lookahead. If "as-of registry" scores materially worse than "full registry", every result built on the full registry is optimistic and must be re-stated. |
| Shrinkage off (raw μ̂) | Whether shrinkage helps or is just timidity. |
| Cost model off | How much of the "no buys" verdict is costs rather than weak forecasts. |

**Block E cases** (~20 each): dates within 5 sessions of a listed split or bonus; stocks newly listed (<120
sessions); stocks entering or leaving surveillance within the window; the most volatile 5% of weeks in the panel;
the thinnest-liquidity quartile that still passes the screen.

## 3b. Cohorts that share one factor (the owner's batch idea)

Random samples answer "on average"; cohorts answer "for which kind of stock". Block B's fixed cohort is extended to
**six cohorts of 100 stocks, each sharing one factor**, drawn at the first `T` and then held fixed across 25 random
`T` each (150 trials, replacing block B's single cohort):

| Cohort | Shared factor | Question |
|---|---|---|
| B1 | Top liquidity tercile (≥ ₹10 cr median value) | Does it work where costs are lowest? |
| B2 | Below the old ₹5 cr floor (now analysed, E21) | Is the illiquid tail predictable, or noise and manipulation? |
| B3 | One sector (largest by count at `T`) | Is the signal sector rotation in disguise? |
| B4 | Listed < 2 years before `T` | Do young stocks behave differently (see docs/NEXT_MODELS.md)? |
| B5 | Highest volatility tercile | Do the tail gate and q10 hold where risk is largest? |
| B6 | Nifty 50 members at `T` | The benchmark's own stocks: any edge where the market is most efficient? |

Each cohort's IC, decile spread and coverage are reported against block A's, with the difference's CI.

## 3c. Knowing exactly what the model was told

Every trial file carries an **information ledger**: the as-of instant `T`; the last session whose bar was used;
the last label resolution date used in training (must be ≤ `T` minus the 20-session embargo); the corporate-action
registry cut (`as-of` or `full`); the universe screen used; and a SHA-256 of the training row set. The scorer refuses
a trial whose ledger shows any input dated after `T`. The point is the owner's request, made mechanical: *know when
you took it away*.

## 3d. What the results may tune, and what they may not

| May be tuned from these trials | Must not be |
|---|---|
| τ for each part (H5), via a pre-declared grid {0.25, 0.5, 1.0}% — declared as new registered trials | The tail limit L, the minimum edge, the cost model |
| Slippage tiers (E21) from realized spreads, if a measured estimator is built | Anything using the sealed holdout |
| Whether to drop the common part (H7) | Feature definitions chosen by looking at decile tables |

Every change chosen from these results is a new registered candidate and must pass the walk-forward evaluation and
the promotion rule on its own; these 1,000 trials are not that evaluation.

## 4. What is computed from the results

Per block, with bootstrap confidence intervals over trials (not over stock-days — stock-days within a date are
correlated, and treating them as independent is how a worthless model gets a t-stat of 6):

- **Information coefficient (the headline).** Spearman rank correlation between μ̃ and realized excess return,
  computed within each trial, then averaged. A retail-scale equity model with a real edge sits around 0.02–0.05.
  Report mean IC, its standard error across trials, and the share of trials with IC > 0.
- **Decile spread.** Mean realized excess return of the top-ranked decile minus the bottom decile, in basis
  points and in rupees at ₹10,000, ₹30,000 and ₹1,00,000. **The decisive number:** if the spread does not exceed
  the round-trip cost (~0.5–0.8%), the model cannot pay for itself at any of those capitals.
- **Monotonicity.** Mean realized return by predicted decile, 1 through 10. A real signal rises across deciles;
  a spurious one is a scatter with two lucky ends.
- **Interval coverage.** The share of outcomes below q10, between q10 and q90, and above q90. Should be
  10 / 80 / 10. If q10 is breached 25% of the time, the tail gate — the rule currently classifying 791 stocks as
  high risk — is calibrated wrongly and every one of those calls is suspect.
- **Class-conditional outcomes.** Mean and distribution of realized returns per predicted class. The test the
  classes must pass: BUY_CANDIDATE > QUALIFIES > HOLD_OFF > HIGH_RISK > AVOID, after costs. If HIGH_RISK stocks
  do not actually do worse than HOLD_OFF, the classes are decoration.
- **The counterfactual portfolio.** For each trial, the realized net rupee outcome of actually buying what the
  allocator chose, including charges, slippage and the DP fee, versus (a) the Nifty 50 and (b) cash. Aggregated,
  this is the only number that answers "would this have made money".
- **Shrinkage diagnostics.** Realized optimal shrinkage per trial versus the τ = 0.5% the model assumes — is
  the model too timid or too bold?

## 5. Automation

One command, deterministic, resumable:

```
marketlab trials --n 1000 --seed <int> --out data/research/runs/trials/<plan_id>/ [--resume] [--block A]
```

- **Build the dataset once.** Features are trailing windows and the screen is dated, so one
  `evaluate.build_dataset` over the full panel can serve every trial by slicing rows at `T`. This is the
  difference between ~50 hours (rebuild per trial) and ~2 hours (slice per trial). The runner must assert, per
  trial, that no row used carries a date after `T` and no label resolved after `T` — a cheap assertion that
  catches the whole class of lookahead bugs.
- **One file per trial**, write-once, `trials/<plan_id>/<block>/<trial_id>.json`: the seed, `T`, the stock list,
  the model digest, every prediction, and (filled in a second pass) the realized outcomes. Plus one
  `summary.json` with the section 4 statistics and one `plan.json` fixing the seeds before any trial runs, so the
  plan cannot be quietly reshaped after seeing results.
- **Scoring is a separate pass** (`marketlab trials-score`) that reads prediction files and realized bars. Keeping
  prediction and scoring apart means a bug in scoring can never contaminate a prediction.
- Progress to stdout, nothing secret in any log, and the whole output tree git-ignored like the rest of
  `data/research/`.

## 6. Honesty rules that bind this plan

1. **These 1,000 trials are measurement, not model selection.** Choosing a candidate, a feature set or a
   threshold because it scored well here is the registered walk-forward evaluation's job, under spec 8.6, and
   doing it here burns the evidence. Any change made because of these results must be declared as a new
   registered trial.
2. **The sealed holdout stays sealed.** No trial may draw `T` inside the frozen holdout window.
3. **The plan is fixed before the first trial runs** (`plan.json`, committed). Adding blocks after seeing results
   is how a null result turns into a published one.
4. **Report the null result as loudly as a positive one.** "IC = 0.001 ± 0.004 over 1,000 trials" is a complete,
   valuable answer that saves the owner from funding a strategy.
5. No LLM anywhere in this pipeline. Arithmetic only.

## 7. Cost

Compute only — no API spend, no paid data, no broker calls. Roughly one dataset build plus 1,000 ridge fits with
50 bootstrap refits each; hours on the laptop, not days, once the prebuilt-dataset design is used. It can run
overnight and be resumed.

## 8. What has to exist first

The plan needs enough history for `T` to be drawn from a meaningful range: with 582 sessions, after the 251-session
feature window and a 20-session label, the drawable range is ~300 dates, and training inside each trial is
thinner still. **The backfill (to ~1,376 sessions) comes first**; otherwise block D's "history length" row has
nothing to compare and every trial trains on a short sample. Specifically: legacy bhavcopies and holiday
circulars loaded, panel rebuilt, corporate actions reconciled over the extended window, holdout frozen.

## 9. The decision this produces

| Outcome | What it means | What to do |
|---|---|---|
| Mean IC > 0.02, t > 2, decile spread > costs, coverage near 10/80/10 | There is a measurable, cost-surviving edge | Proceed to the registered walk-forward evaluation and the promotion rule; then 12 weeks of forward paper |
| IC > 0 but decile spread < costs | Real but too small to trade at this capital | Keep as a screener; revisit at larger capital or longer horizon; do not trade |
| IC ≈ 0 | The features carry no predictive information at this horizon | Stop tuning this model. Keep the parts that are independently valuable: the verified panel, the corporate-action registry, the exact cost model, the surveillance flags and the risk numbers. Say so plainly in the dashboard. |
| Coverage badly wrong | The intervals and the tail gate are miscalibrated | Fix calibration before any other conclusion is drawn from a q10 |

The third row is a real possibility and the plan is designed to detect it cheaply. Finding out that a model has
no edge, before any money follows it, is the most valuable output this system can produce.
