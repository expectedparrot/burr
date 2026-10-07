# Fresh-agent two-stage FCFF pilot

Both fresh agents reproduced the selected Damodaran two-stage model on all
held-out cases. This pilot establishes feasibility; it does not demonstrate an
accuracy advantage for Burr over direct Python.

| Measure | Burr | Direct Python/Excel |
| --- | ---: | ---: |
| Baseline | Pass | Pass |
| Unseen cases | 14/14 | 14/14 |
| Numeric outputs, including baseline | 600/600 | 600/600 |
| Changes from baseline | 560/560 | 560/560 |
| Baseline Excel output checks after LibreOffice recalculation | 40/40 | 40/40 |
| Agent-reported elapsed time | 263 seconds | 205 seconds |
| Parent modeling hints or repairs | 0 | 0 |

Run date: 2026-10-07. Both agents used the same inherited model configuration,
with no model override and a 600-second wall-time allowance. Token usage and
monetary cost were not exposed by the agent tools and were not measured. Timing
comes from each agent's recorded start and finish, not instrumented CPU time.

## Procedure

Each agent started with a fresh conversation and a separate packet containing
the pinned original `fcff2st.xls`, a LibreOffice-converted copy, baseline numeric
inputs, and an input/output cell contract. The source formulas and cached
baseline values were intentionally visible. The Burr arm additionally received
the Burr runtime, agent guide, and semantics documentation. Both received the
same Python interpreter and supporting libraries.

The task was to implement `submission.py --inputs PATH --output PATH`, supporting
changed raw inputs, and produce an Excel workbook with live formulas. Runtime
calculations could not read the source workbook or cached answers. Burr had to
perform its financial calculations in Burr; the other arm used direct Python.
The exact instructions are in [burr-prompt.md](burr-prompt.md) and
[python-prompt.md](python-prompt.md). Their absolute paths describe this run.

The existing handwritten benchmark implementation, reference results, and
held-out cases were excluded from the task packets. File-access restrictions
were enforced by instructions, **not by an operating-system sandbox**. Thus this
is an exploratory blinded pilot, not a demonstrated security boundary. The
original packet files, including vendored Burr, matched their pre-run hashes
after completion. That check does not establish which other files were read.

Fourteen perturbations were fixed before submission, with the input commitment
in [holdout-commitment.json](holdout-commitment.json). They cover individual
changes to capital costs, reinvestment, taxes, capital structure, shares, and
terminal assumptions; negative working capital; and two combined changes.
All retain the source's five-year horizon and reviewed default switches.
Agents received no grader feedback before finishing. Completed packets were
copied to a frozen directory before grading; no submitted code was repaired.

Expected values came from fresh LibreOffice recalculations of the source
spreadsheet for every case. The evaluator checked all 40 contracted outputs in
each case and their changes from baseline, using relative tolerance `1e-9` and
absolute tolerance `1e-7`. These checks are correlated numerical comparisons,
not independent statistical trials. Separately, both submitted baseline Excel
workbooks were recalculated in LibreOffice: all 40 source metrics matched,
with no error cells or missing formula caches (230 Burr formulas; 87 Python
formulas). Microsoft Excel was not run.

## What this tells us

The Burr agent successfully expressed the financial formulas in Burr, used its
native DCF, preserved assumption sources and rationales, recorded an experiment,
replayed it, and exported a verified workbook. Its native six-period DCF is
algebraically equivalent to the source's five-period terminal boundary; the
agent documented that reconciliation without a modeling hint.

Direct Python achieved the same numerical accuracy and finished about a minute
sooner. Burr provided a structured workspace, evidence record, and export
receipt, but this run did not measure whether those features reduce review or
maintenance effort. One source model and one run per arm cannot establish a
general reliability difference. Public source formulas may also be familiar
from training; the unseen numeric inputs test recalculation, not novel finance.

There is a practical limitation in the Burr submission: its adapter copies
Burr-computed WACC and net cash into native valuation assumptions. Re-running
`submission.py` keeps these synchronized, as all held-out cases did. Manually
editing related bindings in the saved workspace or workbook can leave the
native DCF assumptions stale. Baseline Excel verification does not establish
arbitrary in-Excel edit correctness. See the agent's
[notes](submissions/burr/NOTES.md) for supported valuation domains and switches.

A useful next experiment would measure review and revision tasks across more
workbooks and repeated runs, where Burr's provenance and scenario workflow
might provide a measurable benefit.

## Preserved artifacts and reproduction

- [scores.json](scores.json): every independent output and delta check.
- [excel-checks.json](excel-checks.json): independent baseline export checks.
- [hidden-inputs.json](hidden-inputs.json) and [oracle.json](oracle.json): now
  disclosed holdouts and the separately calculated answers.
- [plan.json](plan.json): setup, source hashes, and initial packet hashes.
- [submission-manifest.json](submission-manifest.json): hashes of accepted
  code, notes, timing, baseline outputs, workbooks, and Burr workspace files.
- [submissions/burr](submissions/burr) and [submissions/python](submissions/python):
  exact agent artifacts, including their own verification scripts and reports.
  Agent self-checks are separate from the independent scores above.

Original source spreadsheets and vendored libraries are not duplicated in the
repository. Retrieve the checksum-pinned source with the parent benchmark's
`fetch` command. To reproduce in a scratch directory, copy each submission into
an arm directory (`burr/` and `python/`), and place `hidden-inputs.json` and
`oracle.json` alongside those directories. Each arm needs a `vendor/` containing
`openpyxl`, `et_xmlfile`, and `yaml`; the Burr arm also needs the repository's
`burr/` package. This is necessary because the grader deliberately starts Python
with `-S`. Then run from the repository:

```sh
.venv/bin/python -m benchmarks.damodaran.agent_pilot.grade score /path/to/scratch
```

To regenerate the oracle, put the converted source at
`scratch/burr/source.xlsx`, then run `grade oracle /path/to/scratch` before
scoring. `check_exports.py` preserves the exact independent export check used
for this run; its run-directory constant must be adjusted for another machine.
Use a scratch copy: submissions write model/export artifacts during execution.
