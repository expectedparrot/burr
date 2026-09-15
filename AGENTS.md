# Working with Burr

For modeling tasks, start with `burr guide` and `burr next COMPANY --json`.
The installed guide is maintained in `burr/agent_guide.md`.
Run `next` after material workspace changes. Follow `action.argv`, then rerun
`resume_argv`; inspect `state`, `required_inputs`, and diagnostics before acting.
Use the principal's actual question and existing authorization. Supply missing
inputs from context where possible; ask only when necessary.

Golden path: validate → inspect assumptions → probe a belief → record evidence
→ compare/replay → export. `complete` covers one selected experiment and one
current deliverable, not whether the principal's broader objective is satisfied.

Keep facts, assumptions, and sources separate. Preserve rationales. Prefer new
scenarios to base-case changes. Use reviewed ingestion for factual updates.
Never rewrite journal entries. `try`, `next`, and `replay` must remain read-only.

For package development, preserve existing CLI JSON and exit-code behavior.
Run focused tests for changes, then the full `.venv/bin/pytest -q` suite before
reporting completion of CLI or model changes. Check that installed distributions
include the guide and browser assets. Keep the Starbucks documentation example
and its fixed FY2025 baseline consistent with the implementation.
