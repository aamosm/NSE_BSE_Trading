# Next models: newly listed stocks, IPOs, mutual funds, ETFs and SME shares

**Status: designed, not built.** For whoever implements the next stage. Each section says what the instrument is,
what the evidence says about how it behaves, what MarketLab should compute, and how to test it. Literature claims
are from the standard references named; Indian rules are from SEBI's ICDR regulations as amended to 2022 and must be
re-checked against the current SEBI text before code depends on them.

## 1. Newly listed stocks (the 110 "no forecast" stocks of 5 Nov 2026)

**Why they get no forecast today.** The model needs 251 sessions: 12-1 momentum skips the last month of a year and
the 1-year range needs a year. A stock listed in October 2026 has ~25 sessions, so every long-window feature is
missing and the row is dropped. Missing data is not a neutral fact about a young stock; it is the most important
thing about it.

**What the evidence says about young stocks.**

| Effect | Evidence | Size and timing |
|---|---|---|
| Listing-day underpricing | Ibbotson (1975); Ritter & Welch (2002) review; Indian mainboard IPOs show large average listing gains | Day 1 only: not available to a buyer at the issue price unless allotted |
| Long-run underperformance | Ritter (1991), "The Long-Run Performance of Initial Public Offerings", *J. Finance*; Loughran & Ritter (1995), "The New Issues Puzzle" | Years 1–3 after listing, against size- and book-to-market-matched firms; concentrated in small, hyped issues |
| Lock-up expiry pressure | Field & Hanka (2001), "The Expiration of IPO Share Lockups", *J. Finance* | Negative abnormal return of roughly 1–3% around expiry, volume up sharply |
| Volatility decay | Common across markets | Early sessions are far more volatile; volatility settles over the first months |

**Indian lock-in calendar** (SEBI ICDR, as amended; verify before use): anchor investors' shares are locked 50% for
30 days and 50% for 90 days from allotment; the promoters' minimum contribution for 18 months (3 years when proceeds
fund capital expenditure), promoter holding above that for 6 months; other pre-IPO shareholders for 6 months. Each
expiry is a dated, known-in-advance supply event, which is exactly what a point-in-time model can use honestly.

**What to build.**

1. **Listing date** per ISIN: the first session with a bar in the exchange files (and, for listings before the panel
   starts, the Kite history or NSE's listing data). Stored, dated, sourced.
2. **Age-aware features** for stocks under 251 sessions: return since listing, volatility over all available
   sessions (minimum 10), sessions since listing (bucketed: < 20, 20–60, 60–125, 125–250), days to the next lock-in
   expiry (30, 90, 180 days, 18 months), and, when the issue price is sourced, the listing gain.
3. **Missing long-window features become the neutral rank (0) plus an indicator**, never a dropped row, and young
   stocks enter training with the same treatment so the model learns their coefficients instead of guessing them.
4. **Mondrian (group-conditional) conformal intervals** by age bucket (Vovk et al., conformal prediction): young
   stocks' residuals are larger, so their q10/q90 must be calibrated on young stocks, not borrowed from mature ones.
   This makes the tail gate automatically stricter where the evidence says risk is higher.
5. **A lock-in flag** on the card: "anchor lock-in ends in 6 sessions" is information the owner can act on.

**Test.** Cohort B4 of docs/BACKTEST_PLAN.md: IC and coverage for stocks aged < 2 years, before and after the age
features, against matched mature stocks. Pass if coverage is 7–13% at q10 within the young group.

## 2. IPOs before listing

An IPO cannot be bought on the exchange before listing, and its allotment is a lottery when oversubscribed, so it is
a different decision from a stock. What MarketLab can honestly offer: the IPO calendar (NSE/BSE public issue
pages), subscription by investor category as it updates (QIB, NII, retail), price band, issue size, anchor list,
and, from item 1, how comparable recent listings did after the lock-in dates. No forecast of listing gains: the
evidence on retail-oversubscription signals is mixed and the data history here is short.

## 3. Mutual funds

**Data:** AMFI publishes every scheme's daily NAV (free, official). **What to compute:** returns over standard
windows, volatility, maximum drawdown, rolling returns, the expense ratio (scheme documents), tracking error for
index funds, and a comparison against the scheme's own benchmark. **Not:** a forecast of fund returns; the evidence
that past fund performance persists is weak (Carhart, 1997, *J. Finance*), so the honest output is cost and risk,
which do persist. Projections (docs: build spec) belong here: bootstrap of the fund's own monthly returns.

## 4. ETFs

Excluded from the stock model on purpose: an ETF's return is its index's return, and ranking it against single stocks
on momentum features is meaningless. Analyse ETFs like index funds (section 3) plus what only listed funds have:
premium or discount to iNAV (the `-RL` iNAV instruments in Kite's dump), traded value and the bid-ask cost.

## 5. SME shares (series SM, ST)

Trade in lots set at listing (Kite's dump carries `lot_size`; the 6 Nov 2026 dump has 582 SME instruments). The
minimum lot is often ₹1 lakh or more, so affordability is decided by lot value, not one share. Liquidity is thin and
manipulation risk is documented by SEBI's surveillance actions. To add them: analyse with the stock model but a
separate Mondrian conformal group, cost them with the illiquid slippage tiers (E21), and mark affordability by lot.

## 6. Order of work

1. Newly listed stocks (section 1): the largest gap in today's ranking and the best-documented effects.
2. SME shares (section 5): mostly reuses section 1's machinery plus lot sizes.
3. Mutual funds and ETFs (sections 3–4): a separate module with its own data source; no forecasting model needed.
4. IPOs (section 2): information display only.
