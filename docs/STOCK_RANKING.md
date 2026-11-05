# Stock ranking (RANK.v1): what to buy, hold off and avoid, and why

`marketlab rank` (or Controls → Run a job → Rank stocks) classifies every stock in the latest stored NSE session. It
gives the reasons and the numbers behind each call, and records the result once in
`runs/rankings/<day>/<digest>.json`. The Stocks tab shows that file; How it works explains each step. The ranking
uses the same code as the paper decision (`evaluate.build_dataset` → `decide.fit_today`), so the two always agree.

**Status: research view, unvalidated.** The model has not passed the registered walk-forward evaluation and the
frozen promotion rule. That needs about 1,376 sessions of history; the research folder holds 582. A call is a
structured, fully explained screen, not a recommendation. Paper orders stay off until a model is promoted.

`--capital` is a run parameter, not a fixed ₹10,000 assumption. `marketlab rank
--capital 30000` refits/ranks the same registered model at ₹30,000 and records
that capital in the immutable artifact. The Stocks tab can also restate a saved
ranking at another capital for an indicative, greedy view; newly eligible
stocks require a fresh rank run because the saved artifact has no forecasts for
them.

## The calls

The classes are checked in this order:

| Class | Rule (at the whole-share quantity the per-stock cap allows) |
|---|---|
| Buy candidate | shrunk forecast − round-trip cost ≥ minimum edge (0.10%) **and** 10% outcome − cost ≥ −tail limit (8%) **and** chosen by the allocator (K positions, cap, cash reserve, correlation) |
| Qualifies | both gates pass; the allocator preferred other stocks |
| Avoid | shrunk forecast ≤ −(cost + minimum edge), the mirror of a buy; or an exchange risk flag (ASM/GSM surveillance, suspension, periodic call auction, unreadable status, price band < 10%) |
| High risk | 10% outcome − cost < −tail limit: a bad month (1 in 10) would lose more than the policy accepts |
| Hold off | everything between: the edge does not cover a round trip in either direction |
| Not eligible | outside the universe: not EQ series, an ETF, median traded value < ₹5 crore, not traded every session, or one share > half the capital |
| No forecast | in the universe, but fewer than 251 clean sessions or an unexplained price jump inside a feature window |

## What each card contains

All fields are computed in `quant/ranking.py`; `explain.py` only formats them.

- **Eligibility:** every universe rule with the value compared, pass, fail or unknown.
- **Forecast:**
  - raw μ̂ (ridge: intercept + Σ β·rank);
  - bootstrap standard error from 50 block-bootstrap refits;
  - shrink factor τ²/(τ²+se²) with τ = 0.5%, and the shrunk μ̃;
  - σ̂ = vol₂₀·√h;
  - the conformal 10/50/90% outcomes and P(beat the index).
- **Contributions:** β_j × x_j for every feature. They sum exactly to μ̂ (tested). The common part (intercept plus
  market features) is the same for every stock.
- **Costs:**
  - whole shares q = ⌊per-stock cap / close⌋, where the per-stock cap is derived from the selected capital and policy tier;
  - exact buy and sell charges from the Zerodha schedule (STT rounded to the rupee) plus the ₹15.34 DP charge;
  - slippage both ways (0.10% at ≥ ₹10 crore median traded value, 0.25% below);
  - the limit price and the cash that would be blocked;
  - the same stock's cost at ₹50,000 and ₹2,00,000 capital.
- **Gates and allocation:** both gates at q, the net edge, P(excess > cost), and the allocator's choice.
- **What would change the call:**
  - the margin to each threshold;
  - the rise the forecast needs;
  - the single feature that could move it most, and whether that is enough.
- **Listed corporate actions** in the feature window, with the ISIN lineage when a split moved the stock.

## Corporate actions in features (erratum E17)

NSE does not adjust its base price on split or bonus ex-dates, and a split often issues a new ISIN. Features handle
this as follows:

- **Listed, ratio-consistent split or bonus** (NSE corporate-actions API, 2016–2026, hash-verified; all 200 such
  actions in the research window matched the observed jump): features now use ln(close / (base × factor)) on the
  ex-date, and earlier prices are restated in post-action units for the 1-year range.
- **New ISIN after a listed action:** the predecessor's history is joined to the new ISIN, so the stock keeps its
  year of history.
- **Unlisted jumps and unexplained ISIN changes:** treated exactly as before, as missing data. Without the registry,
  behaviour is unchanged (tested).

## First real run (close of 5 Nov 2026; recorded before the 6 Nov open, so forward evidence)

| Item | Result |
|---|---|
| Panel | 582 sessions (3 Jul 2024 → 5 Nov 2026), 3,954 ISINs. 2025 verified from NSE circular NSE/CMTR/65587, 2026 from the built-in calendar, 2024 from observed publication. |
| Universe | 911 stocks kept. Excluded: 1,304 below ₹5 crore median traded value, 719 not EQ series, 356 ETFs, 62 not traded every session, 46 priced above ₹5,000, 47 under surveillance, 13 on 5% bands. |
| Model | Ridge λ = 1, 219,520 training rows over 311 dates (4 Jul 2025 → 5 Jun 2026). Calibration on 50,324 residuals (8 Jul → 6 Oct 2026). Notable coefficients: 12-1 momentum +0.0095, 1-year-range position +0.0199, 20-session return −0.0098, illiquidity −0.0111. |
| Calls | 0 buy candidates, 0 qualifies, 10 hold off, 791 high risk, 60 avoid (all exchange flags), 110 no forecast, 2,487 not eligible. |
| Why nothing qualifies | The median stock's 20-session typical move is ±11.5%, so its 10% outcome (≈ −15%) is far beyond the 8% tail limit. After shrinkage, 90% of forecasts lie within ±0.16% (the model keeps about 12% of its raw forecasts because 311 dates leave the coefficients uncertain). A round trip costs about 0.76% on a ₹5,000 position. |
| What would change it | More history (the backfill) shrinks the bootstrap error, so less of each forecast is cut away. Calmer markets loosen the tail gate. A larger account lowers costs: the same stocks cost about 0.5% at ₹50,000. |

## Commands

```
marketlab --private-dir data/research/private --market-dir data/research/market rank
marketlab --private-dir data/research/private --market-dir data/research/market actions-import-api --folder <folder with raw/*.json + manifest.json>
marketlab --private-dir data/research/private --market-dir data/research/market actions-reconcile
marketlab --private-dir data/research/private --market-dir data/research/market dashboard --port 8770
```

`data/research/market/calendar_sources.json` declares the stored circulars. Years without one are reconstructed
from publication. `data/research/` is git-ignored: the exchange files are not redistributed.
