# Active project instructions

The user changed scope on 2026-11-04 and explicitly authorized Codex to edit the repository and return a complete ZIP. That instruction supersedes the previous MTF mandate and reviewer-only ownership restriction.

Read README_FIRST.md, PROJECT_BRIEF.md, docs/IMPLEMENTATION_CONTRACT.md and docs/HANDOFF.md before editing.

- Active package: src/marketlab. Active tests: tests. archive/phase_0_1 is the original upstream snapshot, with known defects, retained for reference only. Do not import it into the active runtime.
- Cash equities on NSE/BSE only. No MTF, borrowing, derivatives, short selling or live execution.
- The app may read broker data and exchange a login request token. No order placement/modification/cancellation, product conversion, GTT, withdrawal or fund-transfer capability.
- No live-mode configuration switch. Do not add a generic broker SDK client to the forecasting process.
- One implementation owner at a time: Codex for this reset; then Claude for engineering; then Fable for the scoped quantitative stage. Preserve the user-requested sequence.
- Models may extract facts offline, with evidence. Models do not receive tokens, broker write tools, shell authority or permission to self-modify production.
- Do not infer a future price floor or ceiling, guaranteed appreciation or certainty from a confidence score.
- Missing data stays unknown. Publication, receipt and decision times are separate. No invented historical availability.
- Keep every experiment, including failures, and identify source/data/config hashes. Synthetic tests are not market backtests.
- Numbers used for money are Decimal. Scores are not probabilities without calibration.
- Preserve meaningful tests; add independent economic expectations. Do not skip or xfail a regression to obtain a passing count.
- Do not purchase services, publish private data or submit orders. Deployment instructions are provided; paid deployment itself is not performed in this handoff.
- End with docs/HANDOFF.md listing actual commands/results and exact unimplemented work.
