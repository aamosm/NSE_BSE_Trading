# Fable session 1: preparation bundle

> **Status (5 Nov 2026, late):** the session has been held. Its output is `docs/FABLE_SESSION_1_SPEC.md`, implemented in `src/marketlab/quant/`. Overrides to this document are listed in the spec's §1 (position caps, intraday removed as a candidate, Perplexity removed, calendar from APIs, dynamic universe). The Perplexity facts below are kept as a record; no provider is configured.

Prepared 5 November 2026 by Claude Opus 5.5, the implementation owner. The prompt is `prompts/02_FABLE_SESSION_1_DESIGN.txt`.

The engineering-heavy deliverables of that prompt are **already drafted, built and verified** below. They are numbered as in the prompt's DELIVER list: 1, 3, 4, 5 (reproducibility part), 6, 7 (non-forecasting functions) and 9 (backlog).

**Fable's token budget should go to deliverables 2 and 8, and the forecasting/allocation parts of 5 and 7.** For everything here, Fable needs only to review it and override it where its design requires.

| Label | Meaning |
| --- | --- |
| **[VERIFIED]** | Checked against a primary source or a real run, with the date or evidence given |
| **[DEFAULT]** | Claude's engineering choice; Fable may change it (say why) |
| **[UNKNOWN]** | Not established; treat as missing |

## 0. Facts Fable must not re-derive

| Fact | Status |
| --- | --- |
| No forecasting horizon is testable today: no historical backfill yet, and no official corporate-action history (`DATA_READINESS.md`) | [VERIFIED] |
| **Official archives exist (spot-checked):** NSE bhavcopy from 2016 (two formats), delivery data from 2020, sec_list (bands/series) from 2022, REG1_IND (surveillance stages) from Jan 2025, index closes from 2020, BSE bhavcopy from Jul 2024 | [VERIFIED] |
| **Not available historically:** fundamentals, F&O membership history, broker MIS lists, bid/ask depth, intraday unadjusted bars | [VERIFIED] |
| Kite history is **adjusted by Zerodha** (bonus, split, rights, spin-off, extraordinary ≥ 2% dividends, applied before the ex-date open). Labels must come from exchange bhavcopy prices (`corporate_actions.py`) | [VERIFIED] |
| **After-close file semantics:** sec_list and REG1_IND dated D describe session D+1 (3/3 series changes, 6/6 band changes cross-checked). Band-change files are dated by their effective session | [VERIFIED] |
| **Publication times on 4 Nov 2026 (Last-Modified, IST):** NSE/BSE bhavcopy ~16:35; sec_list 18:00; REG1_IND 19:50; index closes 23:20; delivery data 23:55. One day only; the distribution is [UNKNOWN] | [VERIFIED] |
| **Costs:** STT per security-day rounded to the rupee; DP ₹15.34 per ISIN per delivery sell day. Round trip at one price: ₹1,000 1.76%, ₹2,000 0.99%, ₹5,000 0.53%, ₹10,000 0.38%; intraday ₹10,000 0.11% before spread. Contract-note basis unreconciled | [VERIFIED formula] / [UNKNOWN reconciliation] |
| **4 Nov universe:** 2,739 EQ-series rows traded, **including ETFs**. Median close ₹192; 93% close ≤ ₹2,000 (the current 20% per-stock cap at ₹10,000). Median traded value ₹2.48 crore; ≥ ₹10 crore: 949 rows; ≥ ₹100 crore: 288 rows | [VERIFIED] |
| **4 Nov restrictions:** 229 T2T (BE/BZ) rows, 472 SME rows, 511 of 3,224 securities under a surveillance measure (ESM 224, LT-ASM 138, GSM 73, IBC 55, ST-ASM 52), 16 suspended | [VERIFIED] |
| NSE's close is an auction (CAS) price for F&O stocks from 3 Aug 2026, and VWAP-based otherwise. Entries and exits must be at a tradable price **after** the decision | [VERIFIED] |
| India post-earnings drift evidence is **mixed**: Gupta & Dhusia (2021) find efficiency with heterogeneity by liquidity; other studies report drift after bad news (`READING_LIST.md`) | [VERIFIED citation] |

## 1. Extension map

| Layer | Reused as is | Extended | New (Fable designs the maths, Claude builds) |
| --- | --- | --- | --- |
| Identity | `master.build_master` (ISIN-keyed NSE/BSE listings) | ISIN-change lineage; Kite token join | — |
| Rules | rules engine; `master.build_nse_snapshot` (point-in-time, provenance; `cutoff`=decision time) | intraday refresh (LTP, CAS reference) | — |
| Prices | `sources` bhavcopies (actual prices); `corporate_actions` series types | backfill + old-format parser; derived total-return series | label construction |
| Events | NSE RSS feeds (prospective); `researcher` evidence facts with times | event registry keyed by `evidence.event_identity`; trigger rules | event features, event-time windows |
| Financials | — | `bounded_company_research` jobs; XBRL filings later | feature set B |
| News/attention | — (approved publisher set is empty) | Search API counts per approved publisher | feature set C |
| Forecast | `research.Forecast` | target/label id, cost inclusion, coverage, tail measure, horizon end time | models, calibration |
| Proposal gate | `research.paper_proposal` (rules, costs, freshness, revalidation), `account.fresh_for_cash_decision` | REDUCE/EXIT/HOLD proposals; multi-asset | allocator |
| Paper ledger | — (review items R03/R06/R07 open) | — | ledger with cash reservations (Claude) |
| Replay | `Store.as_of`, `Inputs(cutoff)`, `ArchivedProvider`, `Archive.facts_as_of` | REPLAY/FORWARD_PAPER adapters | evaluation runner |
| Operations | `service` (calendar jobs, states, breakers, gaps, catch-up), `webapp`, `register_tasks.ps1` | research enqueue triggers; morning summary | — |
| Metrics | PSR, DSR, PBO (midrank ties), MinTRL, drawdowns, TWR/XIRR | — | evaluation protocol |

## 3. Laptop operating and state-transition specification (built; times IST)

**Windows** [DEFAULT, adjusted to the measured publication times]. Your proposed schedule fits, with two changes: closing exchange data arrives later than 16:45, so end-of-day collection runs from 16:45 until about midnight; and catch-up the next morning is bounded.

| Window | What runs | Basis |
| --- | --- | --- |
| 07:55 | Task Scheduler starts the scheduler, app and research worker (missed starts run late) | `deploy/windows/register_tasks.ps1` |
| 08:00 | Owner logs in to Kite (manual, official page) | handoff rule |
| 08:05 →, every 5 min to 16:30 | Account batch: holdings, positions, trades, funds, watchlist quotes. Muhurat: from 13:10 | `service.BROKER_LEAD` |
| 08:00–15:30, once | `prepare`: security master + watchlist `InstrumentSnapshot`s, inputs cut off at the decision time; WAIT record if analysis is active | `job_prepare` |
| 08:15–08:45 | Overnight research results and morning summary. **Summary not built**; research worker built | backlog |
| 06:00–23:45, every 30 min | NSE RSS items: announcements, results, board meetings, corporate actions | `job_feeds` |
| 16:45 → done | End-of-day files for today, retried every 30 min until stored; catch-up for 5 earlier sessions; files unpublished after 2 days recorded as missing | measured times |
| 18:00, once | Daily account read incl. instrument dumps | `job_broker` |
| 23:30 | Consistent SQLite backups | `job_backup` |
| Weekends / off-hours | `bounded_company_research` only outside 09:00–15:30 on weekdays | `KindPolicy.off_hours_only` |

**States**:
- `state` ∈ {RUNNING, AUTH_REQUIRED, DEGRADED}, and `analysis` ∈ {ACTIVE, PAUSED}.
- Each data section (holdings, funds, positions, trades) is one of OK, STALE, UNAVAILABLE, MALFORMED, MISSING or SESSION_UNKNOWN.

| Event | Behaviour (built unless marked) |
| --- | --- |
| Startup | Single-instance lock; schedule memory (state file) avoids duplicate once-per-day jobs |
| No or expired login (06:00 expiry) | AUTH_REQUIRED; broker jobs skipped; public files, feeds and research continue; alert if configured |
| Token invalidated early (TokenException) | AUTH_REQUIRED until a **newer** login |
| Late login (after the open) | Broker jobs resume. Cash-dependent proposals need `fresh_for_cash_decision`: batch ≤ 10 min old, after the login, sections OK |
| Laptop sleep / shutdown | Gap > 5 min recorded with its length. Jobs are wall-clock based and run when due. **No past decision, quote or fill is created.** Missed intraday quotes stay missing |
| Lost internet / source failure | Per-provider circuit breaker (15 min doubling to 6 h); DEGRADED; last good data shown with its age |
| Late start after the open | `prepare` runs until 15:30 with inputs received before the actual time; decision marked `late_start` |
| Maintenance / special sessions | Calendar-driven (holidays, settlement holidays, Muhurat); unknown calendars block session jobs |
| Restart / crash | Collection idempotent; WAIT decisions content-deduplicated; research jobs RUNNING > 15 min → FAILED (reservation stays counted) |

**During market hours** [DEFAULT, not enforced in code]:
- Experiments and replays run in separate processes against **copies** of the data directories (`--private-dir`, `--market-dir`), at low priority (`start /low`).
- The active model and strategy version is fixed for the session: a change takes effect at the next session.
- The research worker is a separate process; neither the scheduler nor the decision engine waits for it.

## 4. Research service: jobs, schemas, templates, provider contract (built: `src/marketlab/researcher/`)

**Provider facts** [VERIFIED 5 Nov 2026, docs.perplexity.ai]:
- **Agent API:** `POST /v1/agent`, Bearer auth.
  - Request: `model` or `effort` (the presets are now called *effort*), `max_output_tokens`, `max_steps` (1–500), `store`, `tools`, `response_format` `{type: json_schema, json_schema: {name, schema}}`.
  - `web_search` options: `search_type` fast/web, `max_results` ≤ 50, `max_tokens`, `max_tokens_per_page`, and `filters.search_domain_filter` (≤ 20 entries, allowlist or `-` denylist), plus MM/DD/YYYY date filters and recency.
  - Response: text in `output[]` message parts (`output_text`) with `url_citation` annotations; `search_results` output items (`id`, `url`, `title`, `snippet`, `date`, `last_updated`); cost in `usage.cost.total_cost`.
- **Prices:**
  - `openai/gpt-6-luna` $0.10/$0.50 per 1M tokens; `anthropic/claude-haiku-5-5` $0.10/$0.50 (needs `max_output_tokens`); `perplexity/sonar` $0.25/$2.50.
  - web_search $0.0025 (fast $0.001) per call; fetch_url $0.0005.
  - Search API $0.005 (fast $0.001) per request, up to 5 queries per request.
- **Limits:** tier 0 allows 1 request per second; 429s are not billed. **The console has no spending cap.**
- **Not documented:** whether structured output and tools work together, and which models support structured output.

**Compatibility status:**

| Item | Status |
| --- | --- |
| Agent API with the owner's key | 403 `restricted_api_key` [VERIFIED]. Model + tools + schema + filter compatibility **not yet verified**. `marketlab research-smoke --tools` does it once the key is allowed (known-answer test: Muhurat 8 Nov 2026, normal market 14:20) |
| Search API | 200 [VERIFIED]. `search_domain_filter` honoured: 5/5 results on nsearchives.nseindia.com; the target circular was found; $0.001; 0.61 s |

**Design** [DEFAULT, built and tested]:
- **Separation:** direct collection = `sources.py` (no LLM). Targeted search = Search API (ranked results only). Extraction and deeper research = Agent API jobs. The provider is replaceable through the `ProviderRequest` → `ProviderResult` contract.
- **Kinds, priority, limits (gpt-6-luna), worst-case reservation, cap, TTL:**

  | Kind | Priority | Steps | Worst case | Cap | TTL |
  | --- | --- | --- | --- | --- | --- |
  | material_event_investigation | 1 | 5 | $0.0173 | $0.05 | 3 h |
  | upcoming_event_verification | 2 | 3 | — | $0.03 | 24 h |
  | contradiction_resolution | 2 | 4 | — | $0.05 | 24 h |
  | overnight_update | 3 | 4 | $0.0127 | $0.03 | 10 h |
  | bounded_company_research (off-hours only) | 5 | 8 | $0.0528 | $0.25 | 72 h |
  | Search request | — | — | — | $0.005 | — |

  Daily counts per kind are capped as well.
- **Budget:** $5.00 a month and $0.50 a day, with a hard ceiling of $10.00 that configuration cannot exceed.
  - Each call reserves its worst case first and is settled to the reported cost (to the reservation if unknown; released on 429).
  - An overrun suspends the kind until reviewed.
  - When the budget is exhausted, jobs are DEFERRED (until the next hour for the daily cap, until expiry for the monthly cap), and decisions needing that evidence are WAIT.
- **Queue:** append-only jobs and events; dedup key (kind, ISIN, window, fields, known facts, trigger URL); priority, then age; TTL expiry; bounded retries (429/overload, honouring Retry-After, at most 3 attempts within the TTL); stale-running recovery.
- **Templates:** five versioned, hashed templates (`templates.py`):
  - inputs: ISIN, NSE symbol, BSE code, legal name, aliases, IST window, task, allowed sources by type, requested fields, known facts, trigger;
  - output: evidence and contradictions only; no opinions;
  - retrieved text treated as untrusted data.
- **Schema `evidence.v1`** (`evidence.py`):
  - a closed object; facts carry event type (22 kinds), summary, `published_at`, period, typed dates, values (field enum, amount, unit enum, basis), sources (URL, passage, source type), known fact id and novelty;
  - plus contradictions, unknown fields and `no_new_evidence`.
  - Times: `received_at` and `extraction_completed_at` are ours, never the model's.
- **Validation** (local, after the response):
  - task id and ISIN match the job;
  - HTTPS only; the domain must be allowed for the source type;
  - every cited URL must be among the **retrieved** URLs;
  - every passage must be found in retrieved text to be ACCEPTED (else CANDIDATE); news-only facts are CANDIDATES;
  - ISO times with an offset; no publication after receipt;
  - finite amounts;
  - novelty recomputed from fact identity;
  - syndicated copies count once.
- **Safety:** jobs refuse account fields; prompts are checked against every private env value before sending; the research package cannot import broker, login or account code (test).

**Not built** [backlog]:
- verifying passages against our own fetched copy of an official page;
- per-company IR-domain registry;
- the approved news-publisher set and attention measures;
- scheduler triggers that enqueue jobs (RSS item → material event; board meeting → verification);
- the morning summary.

## 5. Reproducibility rules (built) and reliability estimation (default for Fable to confirm)

**Built:**
- Raw provider responses are stored gzip under `research/raw/YYYY-MM/<sha256>.json.gz`, with metadata: request hash, template id and SHA-256, schema version and hash, model requested and reported, response id, usage, cost, latency, retrieved URLs.
- Facts are stored with `response_received_at` and `extraction_completed_at`. `Archive.facts_as_of(isin, t)` returns only facts validated by t.
- Replay uses `ArchivedProvider`: an unarchived request raises NOT_ARCHIVED and never searches live.
- **Retention:** provider responses are stored privately. Exchange files: terms of use not reviewed [UNKNOWN]. Third-party page content is not archived beyond the snippets returned.

**Reliability [DEFAULT, Fable may replace].** Three separate quantities, never mixed:
1. **Source factual reliability.**
   - Per (registrable domain, field class): counts of correct and incorrect *reviewed* claims, where review is a deterministic comparison with the authoritative record (exchange filing, bhavcopy, official corporate-action list) or human review.
   - Posterior Beta(α₀ + correct, β₀ + incorrect) with α₀ = β₀ = 1. Decisions use the posterior 5% quantile, and only after at least 20 reviewed claims; below that the class is "unscored".
   - Example: 18 correct, 1 incorrect → Beta(19, 2): mean 0.905, 5% quantile 0.784. For β = 2 the CDF is x¹⁹(20 − 19x); solved by bisection.
2. **Extraction accuracy:** the same Beta treatment per (template version, model, field). Versions are never pooled.
3. **Market probabilities:** calibrated only against realised outcomes in offline, versioned research. Never from model self-confidence, and never updated from trading profit.

## 6. Cost and latency budget

**Explicit assumptions:**

| Item | Estimate | Status |
| --- | --- | --- |
| Kite requests | 1.05 s spacing; a batch of 4–5 reads takes about 5 s; 102 intraday batches/day ≈ 510 requests (limits: quotes 1/s, historical 3/s, others 10/s) | [VERIFIED limits] [DEFAULT cadence] |
| Exchange files | About 15 dated + 7 snapshot files/day plus 30-minute retries; at most ~10 missing files × 15 attempts on a bad day | [DEFAULT] |
| Research spend | 10 watchlist stocks × 1 overnight job × 22 sessions = 220 jobs ≈ $1.10/month, plus verifications and events | [UNKNOWN until measured] |

The research estimate assumes about $0.005 per overnight job: 6k input + 1.5k output tokens plus 3 fast searches.

**Freshness requirements** [DEFAULT]:
- **Cash-dependent proposal:** account batch ≤ 10 min old and after the latest login.
- **Paper order price:** quote ≤ 5 min old at submission; decision → submission ≤ 120 s, else re-decide.
- **Rule inputs:** files describing session D received before the decision.
- **Daily features:** the previous session's bhavcopy, available from about 16:35.
- **Research facts:** usable only after `extraction_completed_at`.
- **Event features:** event published before the decision; first receipt recorded. Fable sets the windows.

**Measurements needed:**
- Agent API latency and cost per job kind (blocked by the key);
- RSS lag from `pubDate` to our receipt;
- bhavcopy and REG1_IND publication-time distributions over 20+ sessions;
- Kite endpoint latency;
- laptop uptime and sleep gaps (`service_state.json` `gaps`);
- the share of events found by RSS versus by search.

## 7. Function contracts already implemented (with hand-worked numbers)

| Function | Contract | Worked example (tests) |
| --- | --- | --- |
| `budget.worst_case_usd(model, Limits)` | Upper bound: s·P + (S + O)·s(s+1)/2 input tokens, s·O output, s tool calls | 4 steps, P = 3000, S = 3000, O = 1500: 57,000 in → $0.0057; 6,000 out → $0.003; 4 × $0.001 → **$0.0127** |
| `Ledger.reserve/settle/release` | Refuses JOB_CAP, DAILY_COUNT, DAILY_CAP, MONTHLY_CAP, KIND_SUSPENDED | Daily $0.05: $0.03 reserved, a second $0.03 refused; settled at $0.004 → room again |
| `evidence.assess(doc, …)` | ACCEPTED only with retrieved URL + allowed domain + passage found + primary sources | Dividend ₹1/share, record date 6 Nov, NSE URL in search results, passage in snippet → ACCEPTED; passage absent → CANDIDATE |
| `evidence.independent_sources` | Same publisher or near-identical passage (word sequences, 5-gram Jaccard ≥ 0.6) count once | Two outlets with one sentence (± full stop) → 1; plus a differently worded report → 2 |
| `account.fresh_for_cash_decision(view, t, login_at)` | (ok, reasons) | Batch 09:20, decision 09:45 → ACCOUNT_DATA_STALE |
| `rules.charges.day_charges(fills)` | STT per exchange/ISIN/day/kind/side, rounded to the rupee; brokerage per order; DP per ISIN per sell day | 3 sells of 1 @ ₹400 → STT ₹1 (aggregate 1.20), not 3 × ₹0 |
| `master.build_nse_snapshot(market, symbol, day, cutoff)` | Point-in-time `InstrumentSnapshot` + provenance | 21STCENMGM 5 Nov: EQ → BE, ESM 1, band 5% |
| `research.paper_proposal(...)` | One integer-share entry or ABSTAIN with reasons; rules, costs and freshness gated | `tests/test_costs_and_decision_time.py` |

**For Fable to specify:**
- the label builder;
- feature sets A, B and C with lags;
- fit and calibration;
- the forecast emitter (extended Forecast);
- the allocator (integer, fixed DP per sell day, shared cash, concentration);
- exit rules;
- the evaluation runner;
- each with hand-worked vectors.

## 9. Implementation backlog (engineering only; Fable adds research items) and sparse search requests

1. The owner enables Agent API access for a fresh key; run `research-smoke --tools` to record compatibility.
2. Historical backfill: bhavcopy (two formats), sec_list, REG1_IND, index closes; the old-format parser.
3. Official corporate-action history and reconciliation of 5 representative actions.
4. Research triggers (RSS → jobs), the IR-domain registry, our own official-page fetch for passage verification, and the morning summary.
5. Paper ledger with reservations; REPLAY and FORWARD_PAPER adapters; then Fable's specification.

**SEARCH_REQUESTS** (for GPT; kept short):
- (a) why Perplexity returns `restricted_api_key` and how to enable the Agent API;
- (b) NSE's documented REG1_IND field definitions (`Status`, `ICA`);
- (c) the NSE corporate-action history route.

**What Fable should not spend tokens on:** re-checking the items above, re-deriving costs or calendars, or designing the queue, budget, schema or templates. Change any of them only if the forecasting design requires it, and say why.
