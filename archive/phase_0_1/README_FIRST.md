# Start here

This kit is a build specification, phased instructions and planned test registries. It is not an executable trading app. No broker is connected, no funds are committed, no simulations have run and no performance is claimed.

1. Read NSE_BSE_Build_Guide.md.
2. Open this extracted folder in VS Code.
3. Sign in to the official Claude Code extension using your existing subscription.
4. Paste prompts/00_START_HERE.txt into the coding conversation.
5. Complete Phase 0 only, then have GPT review the handoff using prompts/REVIEW.txt.
6. Continue one phase at a time using prompts/PHASE_PROMPTS.md.

Use one implementation owner at a time. Default owner: Claude Code. Default reviewer: GPT. Use a paid Fable review only for a bounded problem that warrants it.

## Contents

- PROJECT_BRIEF.md: the product scope and decisions.
- AGENTS.md and CLAUDE.md: instructions for coding tools.
- NSE_BSE_Build_Guide.md: the complete guide, costs and dated primary sources.
- docs/IMPLEMENTATION_CONTRACT.md: accounting, data, research and execution contracts.
- docs/VALIDATION_PLAN.md: what the two experiment registries mean.
- docs/TASK_BOARD.md: ordered milestones.
- docs/HANDOFF.md: the handoff template.
- configs/example_policy.json: illustrative paper-only configuration, not implemented controls.
- experiments/coverage_matrix_1200.json: 1,200 planned functional scenario combinations.
- experiments/research_trials_1000.json: 1,000 proposed research configurations.
- prompts/: kickoff, phase, reviewer and failure-analysis prompts.

The registries must be turned into actual fixtures/runs. The kit's packaging checks verify their counts and uniqueness, not trading correctness or investment performance.

All fees, product terms and model prices are a dated snapshot from 3 November 2026. Verify them before implementation and before activation.
