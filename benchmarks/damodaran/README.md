# Damodaran numerical benchmark

Three independent Burr reconstructions of Aswath Damodaran's downloadable
[NYU Stern spreadsheets](https://pages.stern.nyu.edu/adamodar/New_Home_Page/spreadsh.htm).
The original Excel formulas are recalculated in LibreOffice to supply the
reference values. Burr's own Excel evaluator does not generate those references.

| Model | Original workbook | Cases | What it exercises |
| --- | --- | ---: | --- |
| Stable growth | `fcffst.xls` | 7 | Normalized reinvestment, CAPM, taxes, WACC, perpetual growth |
| Two-stage growth | `fcff2st.xls` | 8 | Fundamental growth, working capital, terminal reinvestment, equity bridge |
| Three-stage growth | `fcff3st.xls` | 8 | Changing growth and margins, forward-dependent capex, changing WACC, cumulative discounting |

The suite checks source-cell values and changes from baseline: operating results,
cash flows, financing assumptions, terminal value, firm value, and per-share
value where the source supplies it. It contains 23 cases and 3,014 numerical
checks. Baselines and perturbations use the same reviewed workbook switches.

## Run

From a source checkout with Burr's development dependencies installed:

```sh
# Fast, offline comparison with frozen independent reference values.
.venv/bin/python -m benchmarks.damodaran run
.venv/bin/pytest -q tests/test_damodaran.py

# Fetch checksum-pinned original .xls files, convert them, edit input cells,
# recalculate all cases, and compare both Burr and the frozen references.
.venv/bin/python -m benchmarks.damodaran run --live \
  --output benchmarks/damodaran/.cache/live-report.json
```

Live runs require LibreOffice. The runner looks for `libreoffice`, `soffice`,
or the standard macOS application path. Override discovery with `--soffice PATH`
or `BURR_LIBREOFFICE`. It uses a temporary profile and does not touch personal
LibreOffice settings. The initial run downloads three source workbooks; subsequent
runs use the verified cache. Offline runs need neither network nor LibreOffice.

Reports contain actual/expected values, absolute errors, separate scenario-delta
checks, tolerances, and oracle version. Exit 0 means every check passed; mismatches
or invalid inputs return nonzero. Missing cases, cells, or outputs are failures.

## Reproduce the Burr workspaces

Ready-to-run YAML models, recorded experiments, and Excel exports are available in
[examples/damodaran](../../examples/damodaran/README.md). To exercise the saved
models and independently recalculate all 23 Burr-generated Excel workbooks:

```sh
.venv/bin/python -m benchmarks.damodaran.exercise \
  --workspace examples/damodaran \
  --output examples/damodaran/artifacts/verification.json
```

To generate a separate fresh workspace:

```sh
.venv/bin/python -m benchmarks.damodaran workspace \
  --output benchmarks/damodaran/.cache/workspace
.venv/bin/burr --json -C benchmarks/damodaran/.cache/workspace next two_stage
.venv/bin/burr -C benchmarks/damodaran/.cache/workspace compare three_stage
.venv/bin/burr -C benchmarks/damodaran/.cache/workspace \
  -s discount_up run three_stage
```

The destination must be new. Workspace generation never overwrites a journal.
Every model has a base case and named perturbation scenarios, with input rationales
and source-cell provenance. Scenario generation updates both operating bindings
and valuation assumptions; editing a raw binding alone does not automatically
update separately stored valuation inputs or expanded annual profiles.

Use `next --patch ... --question ...`, inspect the trial, supply a finding, and
follow the returned action/resume arguments to record, replay, and export an
experiment. `next` without a selected experiment can request those missing inputs;
that does not indicate a failed numerical benchmark.

## Source and reference provenance

- `sources.json`: download URLs, SHA-256 hashes, retrieval timestamp, and attribution.
- `catalog.py`: reviewed input cells, supported switches, output cells, and perturbations.
- `inputs.json`: numeric input snapshot, extracted from literals and one explicitly
  reviewed direct input link. It contains no forecast or valuation outputs.
- `models.py`: independently authored Burr formulas and input transformations.
- `reference.json`: frozen LibreOffice results with input/source digests and
  per-case prepared/recalculated workbook hashes.
- `results.json`: concise results of the initial verified live run.

Original and converted workbooks stay in ignored caches or temporary directories.
The source page encourages downloads and modification; this repository attributes
the source and stores input/result extracts instead of redistributing its workbook
files. If an upstream file changes, its checksum fails; review the new version and
cell mappings before deliberately changing the pin.

Reference capture is explicit and only writes a new directory:

```sh
.venv/bin/python -m benchmarks.damodaran capture \
  --output benchmarks/damodaran/.cache/candidate-reference
```

Review candidate inputs/results against the committed snapshots before replacing
anything. Normal `run` and `run --live` never refresh expected values automatically.

## Conventions that matter

Amounts retain the source workbooks' native scale. Years are relative periods
starting at 1, with a synthetic base year of 0. These are historical illustrative
assumptions, not updated company forecasts. `actuals.csv` is intentionally empty:
the source inputs have not been independently ingested as reported facts.

**Stable growth:** the source replaces net capex with
`(capex/depreciation ratio - 1) * depreciation` under its selected switch. Burr
models one explicit cash-flow year followed by the identical growing perpetuity.
One synthetic share and zero net cash make Burr's normalized per-share value equal
to source firm value; the source does not supply an actual equity price.

**Two-stage growth:** the reviewed source uses five high-growth years and a new
terminal reinvestment rate based on growth/return on capital. Burr includes that
first stable year as year 6. Discounting year 6 plus the perpetuity beginning in
year 7 is algebraically equivalent to the source's terminal value at year 5:
`[FCF6 + FCF6*(1+g)/(w-g)]/(1+w) = FCF6/(w-g)`.
The separate terminal-value and terminal-PV checks retain the source's year-5
boundary. Burr's terminal-weight diagnostic would use the later boundary and is
therefore not a compared metric. Fundamental high growth simplifies from source
ROC times reinvestment rate to reinvestment divided by prior book capital.

**Three-stage growth:** years 1–5 grow rapidly and move from the current to target
margin. Years 6–10 move to stable growth, margin, leverage, beta, and debt cost.
Source capex in years 6–9 depends on year-10 capex. The Burr template expresses
the endpoint algebra from raw inputs; no reference forecast amounts are injected
as assumptions. Discounting compounds each year's WACC, matching the source.

Both equity models subtract equity-option value before dividing by shares. The
source's separately displayed equity value is *before* that option deduction;
the comparison explicitly reconciles the distinction.

## Interpretation and extension

Passing means the Burr engine plus these reviewed adapters reproduce these
specific source formulas under the declared cases. This is a numerical regression
benchmark, not a measured LLM-agent success rate or an arbitrary Excel importer.
LibreOffice is the independent calculation engine; Microsoft Excel has not been
run for this suite. Reference calculations are not independent audits of the
source models' economic assumptions.

A separate [fresh-agent pilot](agent_pilot/README.md) gave two agents the source
two-stage workbook, withholding these adapters and reference results. Both Burr
and direct Python passed all 14 unseen input cases. That single paired run shows
feasibility, not an accuracy advantage for Burr. Its report includes exact
submissions, independent scores, timing, and isolation limitations.

The follow-up [model maintenance stress tests](WORKFLOW_EVAL.md) exercise
scenario preservation, stale evidence, replay across a handoff, and export
integrity. Five safeguards worked; a dependent-WACC synchronization test failed.
These are feature exercises on the saved submissions, not a second agent trial.

The current adapters deliberately cover the pinned default switches. New branches
(directly supplied cost of equity, alternative growth weighting, or different
terminal reinvestment switches) need reviewed cell contracts and fresh cases.
Tolerances are `rel_tol=1e-9`, `abs_tol=1e-7` in native units, including for changes.
