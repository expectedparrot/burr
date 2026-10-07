# Model maintenance stress tests

Update: valuation references now fix the dependency failure in a migrated copy.
See [the corrected workspace](../../examples/damodaran_linked/README.md) and
[linked-workflow-results.json](linked-workflow-results.json). The original
results below remain a record of the unmodified pilot submission.

Burr's existing workflow safeguards helped with evidence freshness, scenario
organization, handoff, and export integrity. They did not prevent a wrong native
DCF value after a dependent assumption changed in the pilot model.

These are deterministic exercises on copies of the two saved pilot submissions,
not another blinded agent comparison. We selected tasks relevant to Burr's
design, wrote their criteria before execution, and retained the failure. No
agents were timed, no new Python workflow layer was built, and the archived
submissions were not repaired or modified. Consequently, five successful Burr
checks out of six is **not** a comparative agent success rate.

| Task | Observed Burr behavior | Existing Python submission |
| --- | --- | --- |
| Explore stable ROC of 14.7% without changing base | Read-only trial; value 77.2695; includes driver attribution and rationale | Same value; input dictionary unchanged |
| Save a named scenario | Base bindings unchanged; scenario preserves source, rationale, and thesis | Separate input files can represent scenarios; no supplied metadata convention |
| Change a source note, keep numbers fixed | Flags stale evidence even though replay numerically `HOLDS` | Numeric input contract has no evidence-freshness check |
| Revise capex, then hand off the prior experiment | Detects `DRIFTED`; appends `exp-002`, preserves `exp-001`; replays without original proposal file | Can recalculate; no saved hypothesis/finding/replay journal |
| Edit per-share value in the Excel deliverable to 999 | Detects modified file, regenerates export and receipt | No artifact receipt or freshness-check command supplied |
| Change the risk-free rate from 5.3% to 7.07% | **Fails numerical consistency:** native value stays 66.7826 | Correctly recalculates to 44.7010 |

The Python observations about absent safeguards come from inspection of the
existing submission's contract and code. We did not ask a fresh Python agent to
implement them. Hashes, metadata, journals, and replay can all be implemented in
Python; the demonstrated benefit is that Burr already supplies these mechanisms.

## What the failure means

The Burr agent's original adapter copied computed WACC into a separate numeric
native-valuation assumption. Editing the underlying risk-free binding therefore
updates the model's explicit formula lines, but not the native DCF assumption.
In this test the explicit Burr formula gives 44.7010442, matching both Python
and the saved independently calculated LibreOffice reference. Native DCF still
gives 66.7825642, an absolute discrepancy of 22.0815200 per share.

Validation passes, and the previously recorded native-valuation experiment
still reports `HOLDS`. `next` does flag the changed model fingerprint and requests
fresh review, so it does not silently declare the evidence current. However, it
does not diagnose the inconsistent dependent assumption. Rerunning the original
adapter synchronizes those values; manual workspace edits do not. This is a
limitation of the saved adapter and Burr's support for that representation, not
evidence that Burr's discounting arithmetic is wrong. We preserved the failure
instead of changing the evaluated implementation.

## Interpretation

There is concrete value here beyond numerical calculation: Burr notices when
evidence or a deliverable should no longer be trusted, retains the explanation
behind a scenario, and carries an experiment across a handoff. Those safeguards
worked on this financial model.

Whether they reduce analyst effort or agent mistakes remains unmeasured. A fair
next comparison would give fresh agents repeated revision and handoff tasks,
allow Python to add its own safeguards, and measure total implementation and
review time as well as missed stale results. The dependency problem above must
remain in scope; testing only favorable workflow features would overstate the
benefit.

## Reproduce

```sh
.venv/bin/python -m benchmarks.damodaran.workflow_eval \
  --output /private/tmp/burr-workflow-new-run
```

The output directory must not exist. It receives a plan before execution,
separate workspace copies, generated Excel files and receipts, complete CLI
transcripts, and results. `next` is run after each material workspace change;
record/export actions and their resume commands are executed as returned. No
network access or new spreadsheet conversion is required.

[workflow-results.json](workflow-results.json) preserves the measured results.
Baseline, 14.7% ROC, and 7.07% risk-free values are checked against the prior
pilot's LibreOffice oracle. The capex-plus-ROC replay comparison uses the
unmodified, previously validated Python implementation; it is not a fresh
independent spreadsheet calculation. Export repair checks Burr's verified
cached value and receipt, not a new external Excel-engine recalculation.
