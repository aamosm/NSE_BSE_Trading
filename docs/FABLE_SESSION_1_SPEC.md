# Fable session 1: frozen design specification (v1, 5 November 2026)

Author: Claude Fable 5.1, acting as quantitative designer. Owner: the user. Implementer: Claude (lower-cost models) for plumbing and backfill; the equations below are what they implement.

Status words used throughout: **[VERIFIED]** checked against a primary source, a real file or exact arithmetic (the arithmetic was recomputed in a script; it is not mental estimation); **[DEFAULT]** my design choice, changeable with a reason; **[UNKNOWN]** not established, gated. Nothing here claims that a model is trained, profitable, or ready for live trading. The strongest permitted end state is *bounded, independently reviewed prospective paper observation*.

The engineering deliverables (extension map, laptop operating spec, research-job schemas and provider contract, reproducibility rules, cost/latency budget, implemented contracts, backlog) are in `docs/FABLE_SESSION_1_PREP.md`. I reviewed them; §1 lists my overrides. This document is deliverables **2** (forecasting and allocation mathematics), **8** (evaluation plan), the reliability-update rule of **5**, and the forecasting/allocation contracts of **7**, plus the economics the owner asked to understand.

---

## 0. The economics first: what ₹10,000 can and cannot do

**Costs [VERIFIED, from the cited fee schedule].** NSE delivery, per side: STT 0.1% (rounded to the rupee per security-day), stamp 0.015% on buys, exchange 0.00307%, SEBI 0.0001%, GST 18% on the latter two. Variable round trip ≈ **0.2225%** of value (buy 0.1187%, sell 0.1037%). Plus a **fixed ₹15.34 DP charge per ISIN per delivery sell day**. Slippage and spread come on top.

Break-even for a round trip, as a fraction of position value V:

    b(V) = 0.002225 + 15.34 / V

| V | b(V) |
| --- | --- |
| ₹1,000 | 1.76% |
| ₹2,000 | 0.99% |
| ₹5,000 | 0.53% |
| ₹10,000 | 0.38% |

The position value at which the round trip costs ≤ 0.5% is **₹5,528**; ≤ 1% is **₹1,973**.

**Consequence 1: concentration is forced.** The fixed charge makes the optimal number of simultaneous positions small. With equal weights, per-position mean μ and variance σ² per horizon, pairwise correlation ρ, fixed cost F per round trip, τ round trips per horizon and risk aversion γ, the per-horizon expected utility is

    U(n) = μW − (γ/2) W² σ² (ρ + (1−ρ)/n) − n F τ − (variable costs, independent of n)

Setting dU/dn = 0 gives

    n* = W σ √( γ(1−ρ) / (2 F τ) )

With half-Kelly risk aversion γ = 2/W (defined in §5), σ = 6% per 20 sessions, ρ = 0.3, F = ₹19.79 (DP + variable costs on a ₹2,000 leg), τ = 1:

| W | n* |
| --- | --- |
| ₹10,000 | **1.1** |
| ₹1,00,000 | 3.6 |
| ₹10,00,000 | 11.3 |

[VERIFIED arithmetic.] At ₹10,000 the system should hold about **one position at a time**, of ₹4,000–8,000. Diversification at this capital comes from **sequencing** (independent bets over time) and from running **different research families**, not from many simultaneous names. The existing 20% per-stock cap (₹2,000) is wrong at this capital: it makes every trade cost ≈ 1% and should be raised to 50% for the swing family (§5.4).

**Consequence 2: the detectable edge is coarse.** A one-sided test at α = 0.05 with power 0.8 needs n_eff = ((1.645 + 0.842) σ / μ)² = (2.4865 σ / μ)² independent trades: at σ = 6% per 20 sessions, **890** trades to detect 0.5% net, **223** for 1%, **56** for 2% [VERIFIED]. After the planned backfill (NSE 2016–2025 ≈ 123 non-overlapping 20-session blocks; ~20 selected trades per block with within-block residual correlation 0.2 → 4.2 effective trades per block) N_eff ≈ 512, so the **minimum detectable net edge per 20-session trade is about 0.66%** [DEFAULT assumptions, VERIFIED arithmetic]. For a 60-session horizon (41 blocks, σ ≈ 10.4%) it is **about 2.5%**. Any strategy whose true edge is below those numbers will be indistinguishable from noise with this data, however good it is.

**Consequence 3: recurring costs dominate.** Kite's ₹500/month is 60% of the capital per year. The owner has accepted this as a learning cost. It is excluded from per-trade economics and reported separately (per the contract), but every report must show net rupees after it.

**What this means for the design.** The system is first a **measuring instrument** that must refuse to trade when the edge is below cost or below detectability. Cash is the expected answer most days. That is a correct outcome, not a failure.

---

## 1. Overrides to `FABLE_SESSION_1_PREP.md` (everything else is accepted as is)

| Item | Change | Why |
| --- | --- | --- |
| Per-stock cap 20%, sleeve caps core 50 / swing 20 / intraday 10 | Replace with: per-position **minimum ₹ edge** (§5.2), position count cap K (default 2 at ₹10k), per-stock cap 50%, cash reserve 20%, no sleeve caps | §0: fixed DP charge; sleeve caps would force uneconomic sizes |
| Intraday family listed as a research interface | Keep the interface; **no candidate**, no evaluation; stays INSUFFICIENT DATA (no unadjusted intraday bars, no depth, no MIS list) | Costs, speed competition, SEBI loss statistics; cannot be validated with daily bars |
| Perplexity provider | Removed by owner decision (5 Nov). Keep the provider contract, budget ledger, evidence schema, queue; the default provider is **none** | Owner: "AI API is unlikely to add much value"; the exchange's own feeds are the primary event source |
| Hard-coded calendar years | Calendar years are **loaded from NSE's holiday APIs** (trading + clearing) per stored vintage; circular-based entries become overrides and cross-checks (weekend trading days, special-session timetables) | Owner: no hard-coded dates; 2027 must appear without a code change |
| Hard-coded watchlist | Replaced by a **dated universe screen** (§3.1) over the whole exchange | Diversity of candidates; survivorship-free by construction |
| Freshness default "quote ≤ 5 min" | Kept, plus: **decision inputs for session D must be received before the decision time**, and a post-close decision must use the bhavcopy of D (published ≈ 16:35) | Timing table §2.3 |

---

## 2. Definitions

### 2.1 Time, sessions and information sets

- Sessions D are exchange trading days from the loaded calendar (holidays from the NSE API; special sessions such as Muhurat 8 Nov 2026 use their circular's table).
- **Decision time** t_d is a wall-clock instant (IST). The **information set** I(t_d) is every observation whose *first receipt* by this system is ≤ t_d. In historical replay, where receipt times do not exist, availability is the documented publication time of the file type (§2.3) and the replay must label itself "reconstructed availability".
- The decision for an entry on session D+1 is made at t_d ∈ [16:45 of D, 09:00 of D+1) using D's bhavcopy and D's after-close rule files (which describe D+1).
- Submission s satisfies t_d ≤ s ≤ t_d + 120 s (existing contract; otherwise REVALIDATION_REQUIRED).

### 2.2 Prices, entries and exits (daily-bar convention) [DEFAULT]

Daily bars cannot say whether a limit order fills. The documented convention:

- **Entry**: a paper market order in the pre-open of D+1, filled at the opening price O_{D+1} with slippage s_in: P_entry = O_{D+1}(1 + s_in).
- **Exit** after a horizon of h sessions: decided after the close of D+h, filled at O_{D+h+1}(1 − s_out). The label therefore runs open-to-open over h sessions plus one overnight.
- s_in = s_out = **0.10%** for securities whose 20-session median traded value ≥ ₹10 crore, **0.25%** otherwise [DEFAULT]; stress at ×2 (§8.5).
- If the security does not trade at the open (band limit, suspension, call auction) the paper fill is **deferred** to the next tradable open and marked `FILL_DEFERRED`; a deferral of more than 3 sessions cancels the entry (`ENTRY_FAILED`) with no fictional fill.
- Exits are never "at the close" because a single market-on-close order gets the closing auction price only for CAS securities; the next-open convention is achievable for all.

### 2.3 Timing table [VERIFIED for 4 Nov 2026; distributions UNKNOWN]

| Item | Time (IST) | Describes |
| --- | --- | --- |
| NSE / BSE bhavcopy | ≈ 16:35 of D | session D (actual prices) |
| sec_list (bands, series) | 18:00 of D | **session D+1** |
| REG1_IND (surveillance, suspension) | 19:50 of D | session D+1 |
| eq_band_changes dated D+1 | 18:00 of D | effective D+1 |
| index closes | 23:20 of D | session D |
| delivery data | 23:55 of D | session D |
| Kite account batch | every 5 min, 08:05–16:30 | now |

Decision at 08:30 of D+1 may use all of the above for D. A decision at 17:00 of D may use the bhavcopy but **not** sec_list/REG1_IND for D+1 (not yet published): the rules engine then sees the previous day's series/band, which must be marked ASSUMPTION; prefer the morning decision.

### 2.4 Corporate actions and total return

Exchange bhavcopy prices are actual. On an ex-date X the bhavcopy's `PrvsClsgPric` is the exchange-adjusted base price, so the **exchange-implied adjustment factor** is

    f_X = PrvsClsgPric_X / ClsPric_{X−1}

(e.g. 0.2 for a 5-for-1 split; 0.5 for a 1:1 bonus). The gross total-return label over a window with ex-dates X₁..X_k is

    R_gross = ( P_exit / Π_j f_{X_j} ) / P_entry − 1

This reproduces "value of one original share plus entitlements" for splits and bonuses exactly, and approximates reinvested dividends if the exchange also reduces the base price by the dividend.

**Hypothesis H-CA1 [UNKNOWN]:** NSE adjusts the base price for ordinary cash dividends as well. Verification procedure (backlog): for 10 known actions of each type, compare f_X with the official ratio / (1 − dividend ÷ prior close). Until verified: splits and bonuses use f_X; dividends are omitted from labels (bias ≈ −0.1% per 20 sessions at a 1.2% yield; stated in every report). Windows containing an f_X that matches no listed action and differs from 1 by more than 0.05% are **excluded** from labels and counted.

Worked example [VERIFIED]: O_entry = 100.00, O_exit = 104.00, s_in = s_out = 0.1% → P_entry = 100.10, P_exit = 103.896, R_gross = 3.7922% (log 0.037221). With a 1:1 bonus inside the window the raw exit is 52.00 → 51.948 / 0.5 = 103.896, the same label. Benchmark index 23,000 → 23,230 (1.0000%) → excess 2.7922%.

### 2.5 Net outcome at quantity q [VERIFIED with the implemented fee code]

    NetPnL(q) = q·P_exit − q·P_entry − C_buy(q·P_entry) − C_sell(q·P_exit) − DP·1[q>0] + dividends received

q = 20 of the example: buy value ₹2,002.00, buy charges ₹2.37 (STT ₹2, other ₹0.37); sell value ₹2,077.92, sell charges ₹17.41 (STT ₹2, other ₹0.07, DP ₹15.34); **NetPnL = ₹56.14, net return 2.80%** against a gross 3.79%. Net probability of profit is a function of q; only gross quantities are modelled, costs are subtracted by the allocator (§5).

---

## 3. Universe, families and features

### 3.1 Dated universe U_D [DEFAULT]

For session D, from the previous session's bhavcopy and after-close files (all available before the decision):

1. NSE series **EQ** only (no BE/BZ trade-for-trade, no SME SM/ST/SZ, no ETFs: `FinInstrmNm` containing "ETF" or symbols in the ETF list are excluded — the EQ series contains ETFs [VERIFIED: 2,739 EQ rows on 4 Nov include ETFs]);
2. traded on each of the last 20 sessions (no zero-volume day);
3. 20-session median traded value ≥ **V_min = ₹5 crore**;
4. close ≤ P_max = 50% of W (so at least one share fits a half-position);
5. not under GSM/ASM/ESM/IBC/USM, not suspended, not in periodic call auction (REG1_IND, available from Jan 2025);
6. static band ≥ 10% or no band (sec_list, available from 2022).

Replay before 2025 cannot apply rule 5 and before 2022 cannot apply rule 6. Those periods are marked `SURVEILLANCE_UNVERIFIED` / `BAND_UNVERIFIED`; rule 3 removes most affected names, but results from those periods are reported separately and never pooled silently.

On 4 Nov 2026 rule 3 alone leaves about 1,000 EQ rows (≥ ₹10 crore: 949) [VERIFIED]; the full screen will leave fewer.

### 3.2 Families and what each needs

| Family | Horizon (sessions) | Hypothesis | Features | Historical data | Status |
| --- | --- | --- | --- | --- | --- |
| **A** prices / liquidity / context | 20 (primary), 60 (secondary) | cross-sectional structure in returns (momentum, short-term reversal, liquidity, volatility) survives costs for a small account | §3.3 | bhavcopy 2016→, index closes 2020→ | testable after backfill |
| **B** = A + official events + financials | 5 and 20 after an event | after a results announcement, the post-reaction drift is predictable from the reaction, surprise proxy and liquidity | §3.4 | event history **not held** (announcement archive route is a search request); RSS collection running since 5 Nov 2026 | historical: INSUFFICIENT DATA; prospective from Q3 FY27 results |
| **C** = B + attention | same as B | attention (distinct-publisher coverage) modifies the drift | §3.5 | no approved publisher set; no history | prospective only |
| Core (fundamentals) | 60–250 | quality/value/momentum | needs filings | none | INSUFFICIENT DATA; interface only |
| Intraday | minutes | — | — | none | not a candidate |

**Event-time design for B.** The economic clock is the announcement time τ (NSE RSS `pubDate`, verified against the exchange filing). Reaction session R = the first session whose close follows τ. Decision after the close of R (or at the next pre-open), entry at O_{R+1}: the question is explicitly "what remains after the reaction". Pre-announcement features use only bars ≤ R−1; the reaction features use R.

### 3.3 Feature set A (per security i and decision session D; bars up to D) [DEFAULT]

All log returns r_t = ln(C_t / C_{t−1}) adjusted by exchange-implied factors.

| Name | Formula | Lookback |
| --- | --- | --- |
| mom_12_1 | Σ_{t=D−250}^{D−21} r_t | 250 |
| rev_5 | Σ_{t=D−4}^{D} r_t (sign expected negative: short-term reversal) | 5 |
| ret_20 | Σ_{t=D−19}^{D} r_t | 20 |
| vol_20 | sample std of r over 20 sessions | 20 |
| park_20 | √( mean of (ln(H_t/L_t))² / (4 ln 2) ) over 20 sessions | 20 |
| amihud_20 | mean of \|r_t\| / value_t (₹ crore) | 20 |
| lvalue_20 | ln(median traded value over 20 sessions) | 20 |
| deliv_20 | mean delivery % (from 2020; else missing) | 20 |
| range_250 | (C_D − min L) / (max H − min L) over 250 sessions | 250 |
| gap_1 | ln(O_D / C_{D−1}) | 1 |
| mkt_20, mkt_60 | index log return over 20 / 60 sessions | 60 |
| mkt_vol_20 | index realized vol | 20 |
| breadth_50 | fraction of U_D above its 50-session average close | 50 |

Cross-sectional standardization per date: rank → uniform on (−0.5, 0.5] for stock-level features; market-level features are the same for all stocks on a date and are standardized by their rolling 500-session z-score, winsorized at ±3. Missing stock-level feature (insufficient history) → the row is dropped from training; at decision time → ABSTAIN with `FEATURE_COVERAGE`.

### 3.4 Feature set B additions (event rows only)

reaction_1 = ln(C_R / C_{R−1}) − index return; reaction_gap = ln(O_R / C_{R−1}); abn_vol_R = value_R / median value_20 (pre-event); pre_drift_20 = Σ r over the 20 sessions before R; surprise proxy (time-series, no analysts): sp = (NP_q − NP_{q−4}) / σ(NP changes over the last 8 quarters), consolidated basis, from the filing — **needs extracted financials**, else missing; days_to_next_event (from board-meeting notices). Standardization within the event cross-section of the same results season.

### 3.5 Feature set C additions

att_3 = number of **independent** publishers (syndicated copies merged by the near-duplicate rule in `evidence.independent_sources`) covering the company in the 3 sessions after τ, from an owner-approved publisher list; att_rel = att_3 / its 250-session median for the company. [UNKNOWN until a publisher set exists.]

---

## 4. Forecasting model

### 4.1 Target

For family A: y_{i,D} = R_gross,excess(i, D, h) = gross total-return log return from O_{D+1}(1+s_in) to O_{D+h+1}(1−s_out) minus the index log return over the same window. The benchmark removes the market component (which this system does not try to time) and makes cross-sectional residuals less dependent. Winsorize y per date at the 2.5 / 97.5 percentiles (fitted on training only).

For B: the same, over h ∈ {5, 20} from O_{R+1}.

### 4.2 Estimator: cross-sectional ridge [DEFAULT]

Pool all (i, D) rows in the training window. With X the n×k standardized feature matrix (plus intercept, unpenalized) and λ ≥ 0:

    β̂ = (XᵀX + λI)⁻¹ Xᵀ y

Worked example [VERIFIED]: X = [[1,0],[0,1],[1,1],[2,1]], y = [1,2,3,5], λ = 1 → XᵀX + I = [[7,3],[3,4]], Xᵀy = [14,10], det = 19, **β̂ = (26/19, 28/19) = (1.3684, 1.4737)**.

λ ∈ {1, 10, 100} × (n/1000) chosen by inner validation (§8.3). Point forecast μ̂_i = x_iᵀ β̂. Ridge is the control estimator: interpretable, stable with ~15 features and tens of thousands of rows, hard to overfit when λ is chosen out of sample. Nonlinear models are allowed only later and only if they beat it on untouched folds after costs (contract §2).

### 4.3 Predictive distribution: split conformal, vol-scaled [DEFAULT]

Predicted scale σ̂_i = vol_20,i × √h (per-security volatility over the horizon). On the **calibration fold** (the last part of each training window, purged; never the test fold) compute standardized residuals z_j = (y_j − μ̂_j) / σ̂_j and keep their sorted values z_(1) ≤ … ≤ z_(n_c), requiring n_c ≥ 200 (else INSUFFICIENT_CALIBRATION → ABSTAIN).

    q_α,i = μ̂_i + σ̂_i · z_( idx(α) )   with idx(0.1) = ⌊(n_c+1)·0.1⌋, idx(0.9) = ⌈(n_c+1)·0.9⌉, q50 = μ̂_i + σ̂_i · median(z)
    P(y_i > c) = 1 − ( #{z_j ≤ (c − μ̂_i)/σ̂_i} + 1 ) / (n_c + 1)

Worked example [VERIFIED] with n_c = 10 (illustration only; the real minimum is 200): z = (−2.0, −1.2, −0.7, −0.4, −0.1, 0.2, 0.5, 0.9, 1.4, 2.3), μ̂ = 1%, σ̂ = 5% → idx(0.1) = 1, idx(0.9) = 10 → **q10 = −9.0%, q50 = 1.25%, q90 = 12.5%**; P(y > 0): c = −0.2, four z's ≤ −0.2 → 1 − 5/11 = **0.545**.

Properties: quantiles cannot cross (monotone in α); marginal coverage holds under exchangeability, which time dependence violates, so coverage is **measured** on test folds (§8.4) and the forecast is allowed only while the measured 80% coverage is within [0.72, 0.88].

### 4.4 Uncertainty of the mean and shrinkage

se_i = standard deviation of μ̂_i across B = 100 refits on stationary block-bootstrap resamples of training **dates** (block length h, Politis–Romano), each resample keeping all securities of the sampled dates (cluster by date).

The mean used for decisions is the **empirical-Bayes shrunk mean**

    μ̃_i = μ̂_i · τ² / (τ² + se_i²)      τ = 0.5% per 20 sessions [DEFAULT prior scale of true edges]

Worked example [VERIFIED]: μ̂ = 1.5%, se = 0.6% → μ̃ = 0.615%; μ̂ = 3.0%, se = 0.5% → μ̃ = 1.50%.

Why shrinkage rather than μ̂ − 2se: a lower confidence bound turns every uncertain positive forecast into a negative one and never trades; shrinkage discounts uncertain forecasts smoothly toward the prior that true edges are small, which is the honest belief. The tail gate (§5.2) handles downside separately.

### 4.5 Forecast record (extends `research.Forecast`)

Add: `target_id` ("A.h20.v1"), `benchmark_id`, `entry_rule_id` ("OPEN_NEXT_SESSION.v1"), `h_end_time` (open of D+h+1, for purging), `sigma_hat`, `mu_shrunk`, `tau`, `calibration_n`, `coverage_80_measured`, `features_coverage` (fraction present), `n_eff_training`, `regime_flags`. `probability_positive` = P(y_gross,excess > 0) (quantity-independent); `p_net_positive(q)` is derived by the allocator from P(y > b(qP) + s_in + s_out + index expectation 0).

---

## 5. Decision rule and allocation

### 5.1 Risk aversion

γ = 2 / W_total (₹⁻¹) — the **half-Kelly** choice: a stand-alone position's continuous optimum fraction is μ/(2σ²) of wealth. [DEFAULT; an owner-set `risk_multiplier` m ∈ [0.25, 1] gives γ = 2/(m W).]

### 5.2 Entry gate (all must hold; else ABSTAIN with the listed code)

1. `FEATURE_COVERAGE`: every feature present.
2. `INSUFFICIENT_CALIBRATION`: n_c ≥ 200 and measured 80% coverage ∈ [0.72, 0.88] on the latest test fold; Brier skill score vs. climatology > 0.
3. `MODEL_NOT_PROMOTED`: the candidate has passed the promotion rule (§8.6) and is not in DEMOTED state (§7).
4. `EDGE_BELOW_COST`: there exists q (within caps) with μ̃_i − b(q·P_i) − s_in − s_out ≥ m_min, m_min = **0.10%** [DEFAULT].
5. `TAIL_LIMIT`: q10,i − b(qP_i) − s_in − s_out ≥ −L, L = **8%** per position [DEFAULT].
6. `EXCHANGE_RULE_BLOCK`: the rules engine accepts the paper order on the dated snapshot (existing).
7. `ACCOUNT_DATA_STALE`: `fresh_for_cash_decision` true (existing).

Worked gate [VERIFIED]: μ̃ = 0.615% (from μ̂ 1.5%, se 0.6%): at V = ₹2,000 net edge −0.57%, at ₹5,000 −0.11%, at ₹8,000 +0.0005% → fails m_min everywhere: **no trade**. μ̃ = 1.5% (μ̂ 3%, se 0.5%): at ₹5,000 net edge +0.77% → passes. A forecast must be strong *and* precise to act at this capital.

### 5.3 Allocation objective (one book for all families) [DEFAULT]

Candidates i = 1..M that pass gates 1–3 and 6–7. Decision variables q_i ∈ ℤ≥0, V_i = q_i P_i.

    maximize  Σ_i [ (μ̃_i − c_v − s_in − s_out) V_i − F·1[q_i>0] ] − (γ/2) Σ_i Σ_j V_i V_j σ̂_i σ̂_j ρ_ij
    subject to Σ_i V_i (1 + c_buy) ≤ W_avail − R        (cash after fees, reserve R = 20% W)
               V_i ≤ cap_stock = 50% W;  Σ_{i∈sector} V_i ≤ 60% W (when sector data exists)
               #{i : q_i > 0} ≤ K  (K = 2 at ₹10k; K = round(n*) in general, § 0)
               existing holdings enter as fixed V_i with their own μ̃, σ̂ (aggregated by ISIN across NSE/BSE)

c_v = 0.2225%, c_buy = 0.1187%, F = ₹15.34 + rupee rounding (the implementation recomputes exact charges with `day_charges` after choosing q). ρ_ij from 60-session log returns with constant-correlation shrinkage ρ̂_ij = (1−δ) r_ij + δ r̄, δ = 0.5 [DEFAULT]; σ̂_i as in §4.3. Positive semidefiniteness is guaranteed by the shrinkage toward a constant-correlation matrix with r̄ ∈ (−1/(M−1), 1).

**Solver.** For M ≤ 10 and K ≤ 3 the integer problem is solved **exactly by enumeration** over subsets S ⊆ candidates with |S| ≤ K and q_i ∈ [0, ⌊cap/P_i⌋] (≤ 4 × 10⁴ combinations at these sizes). Larger cases: continuous optimum per subset by projected coordinate ascent, then integer neighbourhood search over q_i ∈ {⌊q*⌋−2, …, ⌈q*⌉+2}, recomputing exact charges and feasibility for every candidate point (the "documented rounding/repair procedure" of the contract), with the enumeration solver as the test oracle on small instances.

**Worked allocation [VERIFIED by exhaustive enumeration].** W = 10,000, R = 2,000, cap 5,000, K = 3, γ = 2/10,000, ρ = 0.3, s_in + s_out = 0.2%, F = 15.34:

| Candidate | P | μ̃ | σ̂ | edge after variable costs |
| --- | --- | --- | --- | --- |
| A | 250 | 1.2% | 6% | 0.7775% |
| B | 1,200 | 0.9% | 5% | 0.4775% |
| C | 80 | 0.4% | 9% | −0.0225% |

Optimum: **q_A = 20 (₹5,000), q_B = 0, q_C = 0**, objective ₹14.54. Adding B at q = 2 (₹2,400) gives 2,400 × 0.4775% = ₹11.46 expected, below its ₹15.34 fixed charge, so the objective falls to ₹7.06; A's continuous stand-alone optimum is ₹10,799, so the stock cap binds. C has negative edge after costs and is never held. This is the n* ≈ 1 result in action.

### 5.4 Position-count and cap defaults by capital

| W | K | cap_stock | typical position |
| --- | --- | --- | --- |
| ≤ ₹25,000 | 2 | 50% | ₹5,000–8,000 |
| ₹25,000–2,00,000 | 4 | 35% | |
| > ₹2,00,000 | round(n*) ≤ 10 | 20% | |

### 5.5 Exit policy EXIT.v1 [DEFAULT]

Evaluated after every close for each held position; actions execute at the next open.

1. **Horizon expiry** (h sessions elapsed): re-forecast. Hold if
   U_hold = V μ̃_cont − (γ/2) V² σ̂² (plus cross terms with other holdings)
   ≥ max(0, U_alt), where U_alt = V (μ̃_alt − c_v − s_in − s_out) − F − (γ/2) V² σ̂_alt² for the best unheld candidate (its full round trip is new cost; the current position's exit cost is sunk either way). Otherwise EXIT (and the allocator may enter the alternative).
   Worked [VERIFIED]: V = 5,000, μ̃_cont = 0.4%, σ̂ = 6% → U_hold = ₹11.00; alternative μ̃ = 1.1%, σ̂ = 6% → U_alt = ₹9.54 → **HOLD**; the alternative's 0.7% advantage does not pay its ₹15.34 fixed cost plus variable costs on ₹5,000.
2. **Re-evaluation triggers before expiry** (then rule 1 applies immediately): realized return since entry < q10 of the entry forecast; a new surveillance flag, series change to T2T, suspension or band ≤ 5%; an announced corporate action with ex-date inside the remaining horizon (family A) ; the candidate was DEMOTED (§7).
3. **Hysteresis**: a hold/exit flip requires the utility difference to exceed ₹5 (≈ a third of the fixed charge); horizons are never extended to hide a loss: every extension is a new decision record with its own forecast.
4. **Risk cap breach by appreciation**: trim only when the trimmed value exceeds 25% above cap and the trim's utility gain exceeds its costs.
5. **Protective rule**: no price stop. A loss beyond q10 triggers rule 2, and the decision is recorded even when the answer is HOLD. Gaps and circuits are modelled by the deferred-fill rule of §2.2; the paper ledger records the deferral, never an assumed fill.

---

## 6. Market understanding: when to trust a pattern

**Who is on the other side.** NSE cash turnover is dominated by institutions (domestic funds, FPIs), proprietary and high-frequency desks (co-located, microsecond reaction), and a large retail base. A ₹10,000 account trading at daily frequency has zero price impact and zero speed; it competes only on *patience* and *selectivity*. Anything that depends on being first (intraday reversals, news reaction in the first minutes, NSE–BSE price gaps) is already taken by faster participants before the open; the design excludes it. What remains plausible at a daily horizon: slow information incorporation in less-covered names (post-event drift), compensation for bearing short-term inventory risk (5-day reversal) and crowd behaviour over months (momentum). Each has an identifiable loser (impatient sellers, attention-driven buyers), which is the first trust criterion.

**India-specific frictions that the engine already enforces:** T2T series (delivery only), surveillance stages with 5%/2% bands and 100% margins, periodic call auctions for illiquid names, static bands, tick sizes, pre-open and CAS auctions, T+1 settlement, SEBI's retail-algo registration threshold, and the fixed DP charge.

**Trust criteria (a pattern is acted on only if all hold):**
1. *Preregistered* with an economic reason and an identified counterparty, before any result is seen.
2. *Out-of-sample*: positive net rupees in purged walk-forward folds (≥ 60% of folds) and on the untouched holdout.
3. *Selection-adjusted*: DSR ≥ 0.95 given the full trial count; PBO ≤ 0.25.
4. *Stable*: no single year, sector or stock contributes > 50% of net; sign stable across the pre-2020, 2020–2022 and 2023+ regimes (T+1 from Jan 2023; CAS from Aug 2026; pre-open change Sep 2026 — report by regime).
5. *Robust to execution*: survives costs ×2, slippage ×2, entry one session late, and the removal of the best 5% of trades.
6. *Powered*: N_eff ≥ the MinTRL / power requirement for the observed effect (§0, §8.4); otherwise INSUFFICIENT EVIDENCE regardless of the point estimate.
7. *Calibrated*: measured interval coverage and Brier skill as in §5.2.
8. *Prospectively confirmed*: ≥ 12 weeks of paper observation consistent with the backtest distribution (PIT uniformity, realized net within the forecast interval).

**Distrust signals (any one demotes to WAIT):** in-sample only; a rule changed after seeing results; dependence on fills at the close or inside the spread; effect concentrated in names below V_min or in surveillance periods; vintage leakage (adjusted prices, revised data, current index membership); edge decay (§7).

---

## 7. Monitoring and decay (offline learning loop)

For each promoted candidate, after every resolved trade compute the standardized error e_t = (y_t − μ̂_t)/σ̂_t and the PIT u_t = F̂_t(y_t).

- **CUSUM on the mean**: S_t = max(0, S_{t−1} − e_t − k), k = 0.25, alarm at S_t > 5 [DEFAULT]. An alarm sets the candidate to **DEMOTED**: no new entries; open positions follow EXIT.v1; re-promotion requires the full rule on data after the alarm.
- **Calibration drift**: on each rolling window of 100 resolved trades, 80% coverage outside [0.72, 0.88] or a KS statistic of the PITs > 0.15 → DEMOTED.
- **Economic drift**: rolling 60-trade mean net return below 0 with one-sided p < 0.1 (block-bootstrap by date) → review.

All parameter or feature changes happen in a new **versioned** candidate evaluated from scratch (§8); nothing updates weights after a loss.

---

## 8. Frozen evaluation plan

### 8.1 Data and periods

- NSE daily bhavcopy 2016-01-01 → latest; index closes 2020→ (before 2020 the benchmark is INSUFFICIENT → family A folds start 2021 for excess-return labels; a price-only pre-2020 sensitivity run uses the equal-weight universe return as benchmark, reported separately).
- Universe U_D per §3.1 with the stated unverified periods.
- **Holdout**: the last 12 months before the backfill date (locked at the date the registry is frozen). It is evaluated **once**, after everything else is final. A second look requires fresh prospective data.

### 8.2 Walk-forward

Rolling training window of 3 years; test fold = 6 months; step = 6 months. **Purge**: drop training rows whose label end time (open of D+h+1) is after the fold's first decision time; **embargo**: h sessions after the fold. Refit scalers, winsorization, λ and the conformal residual set within each training window.

### 8.3 Inner validation

The last 20% of each training window (by date, purged) selects λ by pinball loss at q10/q50/q90 plus MSE; the chosen λ is recorded per fold.

### 8.4 Metrics (per fold, and pooled)

- Net rupees at ₹10,000 through the full decision pipeline (gate + allocator + EXIT.v1 + exact charges), with recurring costs listed separately; also gross/net excess return per trade, hit rate, turnover, max drawdown, time in cash.
- Calibration: Brier and Brier skill vs. the climatological rate; pinball(0.1/0.5/0.9) vs. unconditional quantiles; 80% coverage; PIT histogram and KS statistic on non-overlapping trades.
- Discrimination: rank IC (Spearman) by date and its date-block bootstrap CI.
- Dependence: N_eff = Σ_blocks m_b / (1 + (m_b − 1) ρ̂_b) with ρ̂_b the within-date-block residual correlation; all t-statistics use N_eff.
- Selection: DSR with the **registered trial count** (candidates × λ grid × horizons × ablations), PBO by CSCV with 16 date blocks (midrank ties), MinTRL at 95%.
- Stress (§6, criterion 5).

### 8.5 Registered trials (frozen set)

| # | Candidate | Horizon | Grid |
| --- | --- | --- | --- |
| T0 | Cash (control) | — | — |
| T1 | Equal-weight U_D, monthly rebalance, with costs (control) | 20 | — |
| T2 | Index buy-and-hold (control; price index + dividend-yield proxy until a TR index exists) | — | — |
| T3 | Family A ridge | 20 | λ × 3 |
| T4 | Family A ridge | 60 | λ × 3 |
| T5 | Family B event ridge (prospective; historical only if the announcement archive is obtained) | 5, 20 | λ × 3 |
| ablations | T3 without mom_12_1; T3 without rev_5; T3 stock features only (no market context) | 20 | λ × 3 |

Trial count for DSR: 3 + 3 + 3 + 3 (T3, T4, ablations×3) = up to 21 fitted configurations; the count is recorded as actually run. Family C has no historical trial.

### 8.6 Promotion rule (written before any result)

A candidate is **PROMOTED to paper observation** only if, on the walk-forward folds: net ₹ > 0 pooled and in ≥ 60% of folds; DSR ≥ 0.95; PBO ≤ 0.25; BSS > 0; 80% coverage ∈ [0.72, 0.88]; survives all stresses with net ₹ > 0; no single year/stock > 50% of net; N_eff ≥ MinTRL; and the single holdout evaluation shows net ₹ > 0. If N_eff < MinTRL or any calibration test is inconclusive: **INSUFFICIENT EVIDENCE**. Otherwise **REJECT**. Paper observation lasts ≥ 12 weeks and ≥ 30 resolved trades; the audit (session 2) decides CONTINUE PAPER / REJECT / INSUFFICIENT EVIDENCE by the same thresholds on prospective data.

### 8.7 Engineering scenarios (separate registry)

≥ 1,000 generated cases over: missing/late files, duplicate receipts, sleep gaps, restart mid-batch, insufficient cash, deferred fills, band limits, ex-dates inside holdings, corrupt files, conflicting rule files. Counted and reported as engineering coverage, never as strategy evidence.

---

## 9. Reliability-update rule (deliverable 5, prediction-relevant part)

Three quantities, never mixed: **source factual reliability** r_s, **extraction accuracy** r_e, **market probability** p (only §4.3).

For a source class s (registrable domain × field class) and reviewed claims with c correct and w wrong (review = deterministic comparison with the authoritative record, or human review; never trading P&L):

    r_s ~ Beta(1 + c, 1 + w);  use the 5% posterior quantile r_s^(5);  score only when c + w ≥ 20; drop observations older than 2 years.

Worked [VERIFIED]: c = 18, w = 1 → Beta(19, 2): mean 0.905, **5% quantile 0.784** (CDF x¹⁹(20 − 19x), solved by bisection). Use: a fact from a class with r_s^(5) < 0.8 (or unscored) is a CANDIDATE until an independent primary source confirms it; it never enters a feature as a fact. The same Beta treatment applies per (template version, model, field) for r_e; versions are never pooled. These numbers never become p, and p is never adjusted by them except through feature *availability*.

---

## 10. Contracts to implement (signatures; worked values above)

| Function | In → Out |
| --- | --- |
| `labels.forward_return(panel, isin, D, h, slippage) → {gross, excess, entry, exit, factors, excluded}` | §2.4 example: gross 3.7922%, excess 2.7922% |
| `panel.implied_factor(isin, day)` | PrvsClsgPric / prior close; 0.5 for the 1:1 bonus |
| `features.set_a(panel, isin, D)`; `features.standardize_by_date` | §3.3 |
| `linalg.ridge(X, y, lam) → beta` | (26/19, 28/19) |
| `forecast.fit(rows, lam_grid, h) → Model`; `forecast.predict(model, x, sigma) → Forecast` | §4.3 example: q10 −9.0%, q50 1.25%, q90 12.5%, P 0.545 |
| `forecast.shrink(mu, se, tau)` | 1.5%, 0.6% → 0.615% |
| `allocate.plan(candidates, holdings, W, policy) → {q_i}, diagnostics` | §5.3 example: (20, 0, 0), objective 14.54 |
| `allocate.exit_decision(position, alternatives, policy)` | §5.5: HOLD (11.00 vs 9.54) |
| `evaluate.walk_forward(panel, config) → report`; `evaluate.promotion(report, thresholds)` | §8 |
| `monitor.cusum(errors, k, h)` | §7 |
| `reliability.update(c, w) → (mean, q05)` | (0.905, 0.784) |

---

## 11. What the data cannot support today (gates)

- Family A: **INSUFFICIENT DATA until the backfill** (none held before 30 Oct 2026). After backfill: testable at h = 20; h = 60 has an MDE of ≈ 2.5% and will likely be INSUFFICIENT EVIDENCE.
- Family B: **no historical events**; prospective only. First assessment after two results seasons (≈ 6 months of collection), earliest promotion after four.
- Family C and Core: **no data**.
- Dividends in labels: pending H-CA1.
- Any period before 2025 (surveillance) / 2022 (bands): reported as unverified.

---

## 12. SEARCH_REQUESTS (sparse, for GPT)

1. **NSE base-price adjustment rule**: the circular stating how `PrvsClsgPric` is adjusted on ex-dates, and whether ordinary cash dividends adjust it (decides H-CA1 and the total-return label).
2. **NSE corporate-action history**: an official route with ratios, record and payment dates (confirms implied factors; needed for the ledger).
3. **NSE corporate-announcement archive**: a route to historical results-announcement timestamps (unlocks family B historically).
4. **Industry mapping**: the archive of `ind_nifty500list.csv` (or equivalent) for dated sector membership (enables the sector cap and sector-relative features).

---

## 13. Prioritized backlog (quant; engineering items are in the prep document)

1. Panel builder over backfilled bhavcopies with exchange-implied factors (**lower models**), then the H-CA1 check (10 actions per type).
2. Run T0–T4 + ablations per §8; write model cards; do **not** open the holdout.
3. Prospective event registry from the NSE feeds (B), with the §3.4 features computed at R+1.
4. Paper ledger with cash reservations and deferred fills; FORWARD_PAPER adapter wired to the gate, allocator and EXIT.v1; dashboard views for forecasts, allocation and evaluation.
5. Monitoring (§7) on the paper log; audit bundle for session 2.
