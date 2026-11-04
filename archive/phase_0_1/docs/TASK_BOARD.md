# Task board

Check a milestone only after its acceptance evidence is recorded **and** reviewed.

Status on 4 Nov 2026:
- **Phase 0:** deliverables done; awaiting GPT review.
- **Phase 1:** implemented with fixtures A–H and invariants; awaiting review. It was started before the Phase 0 review, at the user's direction.
- **Phases 2–10:** not started.

| Phase | Primary owner | Reviewer | Deliverable |
| --- | --- | --- | --- |
| 0 | Claude Code | GPT | Environment, source/rule register, architecture decisions |
| 1 | Claude Code | GPT; Fable for difficult ledger questions | Cash/MTF accounting and hand-calculated fixtures |
| 2 | Claude Code | GPT | Point-in-time ingestion and evidence schemas |
| 3 | Claude Code | GPT | Replay clock, simulated broker, recovery and durable events |
| 4 | Claude Code | GPT; optional Fable | Forecast, allocator, risk and MTF decision interfaces |
| 5 | Claude Code | GPT; optional Fable statistical audit | Scenario harness, research grid and honest evaluation |
| 6 | Claude Code | You and GPT | Phone dashboard, audit views and deterministic explanations |
| 7 | Claude Code | GPT | Broker read-only adapter and reconciliation |
| 8 | Claude Code | GPT | Deployment package and hosted paper operation |
| 9 | Claude Code | You | Android build and phone verification |
| 10 | Claude Code prepares release | You decide activation; independent review recommended | Explicitly capped live configuration if evidence warrants it |

Stage the earliest vertical demonstration after Phase 3: simulate a cash and MTF purchase/exit on synthetic data, show the ledger and explain the decision. This is an internal accounting demo, not a profitable strategy claim.

Review cadence: after each accounting, data, execution or risk milestone. UI-only changes need proportionate review. Large research reruns occur when changes affect results, not after every wording edit.
