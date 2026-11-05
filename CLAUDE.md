Read AGENTS.md, README_FIRST.md and docs/HANDOFF.md before editing.
Scope: cash-only NSE/BSE research and paper investing; read-only Kite data; laptop now, private server + phone PWA later; no order capability and no live switch (MTF removed 2026-11-04).
The quantitative design is frozen in docs/FABLE_SESSION_1_SPEC.md; implement it, do not reinvent it. Where it was inconsistent or silent, the implemented resolution is in docs/SPEC_ERRATA.md. Current plan: docs/ROADMAP.md section 2. Data state: docs/DATA_READINESS.md and docs/SOURCE_STATUS.md.
archive/phase_0_1 is history only. Never store broker passwords/PINs/OTP seeds; never print secrets or account data from data/private. No LLM provider is configured (owner decision); do not add one without a verified price recorded in researcher/budget.py.
Dates come from the loaded exchange calendar (NSE holiday APIs plus cited circular overrides); do not hard-code new dates in code.
Use targeted tests for changed behaviour; do not re-run unchanged suites just to report a count.
