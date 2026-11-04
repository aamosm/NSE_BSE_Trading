# Cash research reset handoff

Date: 4 November 2026. Upstream: aamosm/NSE_BSE_Trading at 19d12dcac7415b17d3a5192035517ad285f9b389.
Active package version: 0.2.0. Delivery: complete source ZIP plus UPGRADE.patch. No new commit has been pushed to GitHub.

## User's revised scope

Remove MTF. Build a cash-only NSE/BSE research base, connect Kite for data with no actual orders, prepare primary-source research and sequential Claude/Fable/testing handoffs, and provide server/phone setup instructions.

The user explicitly authorized source edits. The older reviewer-only rule and mandatory-MTF plan are superseded. The next implementation owner is Claude; Fable follows after its engineering handoff.

## Implemented

- Fixed-host read-only REST adapter with endpoint/method allowlist at both dispatch and HTTP layers. Login token exchange is the only POST. No live-order mode.
- Private daily-token workflow using hidden terminal input; no stored API secret, password or OTP seed.
- Broker observation collector, master snapshots, bounded history downloader and provenance metadata.
- Timestamped append-only SQLite observations plus repeated receipt records, deduplication, as-of reads, quota and consistent backup.
- RSS/Atom evidence import/download and normalized external-trade observations.
- Exploratory one-instrument baseline simulation with current estimated fees, slippage, later-bar execution, conservative cash and explicit limitations.
- Experiment start/completion/failure events with source/data hashes; unique default output paths and no report overwrite.
- Typed forecast validation and one-entry paper proposal sizing with evidence/calibration, fresh quote/status, cost, risk, cash, liquidity and concentration checks.
- Deterministic explanations and a loopback status page, with Ubuntu service files and private phone-access instructions.
- Primary-source research brief, quantitative specification and four stage-specific prompts.

All 61 original tracked files are preserved under archive/phase_0_1 and were verified against their upstream Git blob hashes. The original review and ten legacy counterexamples are preserved under docs/reviews. The archive is not installed or included in active test discovery.

## Validation actually run

Environment: Linux Python 3.12.14, exact requirements-dev.lock packages. Runtime itself uses the Python standard library.

| Check | Result |
| --- | --- |
| Active pytest suite | 76 passed, 0 failed, 0 skipped |
| Python compilation | Passed |
| Synthetic daily demo | Passed, 260 made-up bars, three diagnostic comparisons |
| Saved synthetic RSS import | Passed |
| Dataset audit on synthetic demo | Passed as a command; correctly reported missing provenance/verification |
| CLI help | Passed |
| Mock broker integration | Passed: reads, history identity, metadata, expiry, gzip response |
| SQLite duplicate/revision/backup/quota checks | Passed |
| Local HTTP smoke | GET / and /health succeeded; file traversal 404; POST /orders 501 |
| Complete upstream archive | 61 file hashes verified |

Raw command results are in docs/validation. The property test uses a 100-example budget; it is counted as one pytest test, not 100 strategies. The planned 1,000-scenario campaign has NOT been run.

The old 211-test suite passed during the preceding review; it is not a test count for this rewritten active package.

## NOT RUN / not delivered as complete

- Real Kite account login or paid-endpoint compatibility on the user's account.
- Real-market strategy backtests, model training or demonstrated predictive edge.
- Windows setup/ACL testing.
- Cloud-server provisioning or live service installation.
- Browser visual check: Playwright was present but its browser executable was absent. Rendering/string escaping and actual local HTTP responses were checked.
- Full security master, exchange calendars/restrictions, corporate actions or historical information reconstruction.
- News extraction into financial/event features.
- Complete multi-broker account reconciliation and portfolio reservations.
- Joint multi-asset optimization, forecast-driven sell/rebalance policy or autonomous paper loop.
- WebSocket tick recording or low-latency intraday infrastructure.

## Scope of current financial results

Every included demonstration is synthetic. The simple baselines are controls, not the requested final model. The fee estimator uses a resident cash-equity schedule observed on 4 November 2026 and paise rounding assumptions; account classification, aggregation and rounding must be reconciled. Using it for earlier years is counterfactual.

Current simulation limitations are embedded in reports. Dataset metadata alone is not proof of a clean dataset. A successful API download is not strategy validation.

The paper sizing function is not a portfolio coordinator. Its supplied account exposures, evidence IDs and cash must be independently reconciled and serialized by the next milestone.

## Exact next task

Claude: follow prompts/01_CLAUDE_ENGINEERING.txt. Audit the reset, finish the explicitly listed data/account/calendar integration contracts, verify read-only login locally when the user authenticates, and return a concrete FABLE_HANDOFF.md with actual schemas and data coverage.

Fable: follow prompts/02_FABLE_QUANT.txt and docs/FABLE_MATH_SPEC.md. Ask the searching assistant precise missing-source questions through SEARCH_REQUESTS.md.

Independent tester/reviewer: follow prompts/03_VALIDATION.txt and prompts/04_INDEPENDENT_REVIEW.txt after Fable's implementation. No real orders at any stage.
