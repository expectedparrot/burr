# burr

![A green parrot perched on a brass stock ticker under a glass dome](docs/assets/burr-artwork.jpg)

A command-line language for driver-based company models. Business logic lives in
templates, reported facts in CSV, beliefs in params, and questions and findings in
an append-only experiment journal.

**[Package walkthrough](docs/index.html)** — build a model, explore a pricing
scenario, record an experiment, and share a dashboard or spreadsheet. Open the
HTML file in your browser; no documentation server is needed.

Implemented from [burr-spec.md](burr-spec.md). Requires Python 3.11 or newer on
macOS or Linux (workspace transactions use POSIX advisory locks).

```sh
uv venv
uv pip install -e '.[dev]'
source .venv/bin/activate

burr -C examples/lemonade test stand
burr -C examples/lemonade compare stand
burr -C examples/lemonade run stand
```

Without installation, `python -m burr` works when PyYAML and openpyxl are installed.
To create your own workspace:

```sh
burr init my-model
burr -C my-model value stand --json
```

A Starbucks example is available in [examples/starbucks](examples/starbucks/README.md),
using FY2024–FY2025 reported results as a fixed teaching baseline, with explicit
forecast assumptions, three scenarios, an experiment, and verified Excel output:

```sh
burr -C examples/starbucks compare starbucks
```

The starter is a lemonade stand, with a base and bear scenario. Its dollar
valuation is intentionally a small teaching example, not an investment forecast.
`init --template NAME` gives this starter logic the specified template ID.

## Explore a belief

The included patch raises the price per cup and records why:

```sh
burr -C examples/lemonade try stand ../patches/premium.yaml
burr -C examples/lemonade record stand ../patches/premium.yaml \
  --question 'What if customers accept a higher price?' \
  --finding 'Higher pricing raises per-share value under the existing cost model.' \
  --tags pricing
burr -C examples/lemonade log stand --param price
burr -C examples/lemonade replay stand exp-001

# Apply a durable, validated scenario when ready.
burr -C examples/lemonade patch stand -f ../patches/premium.yaml
burr -C examples/lemonade explain stand --frm base --to premium
```

`try` writes nothing. `patch` validates structure, facts, and checks before
committing. `record` attaches machine-computed results to your question and
finding. Journal entries are never overwritten. Logic, environment, opinion, or
fact changes can mark earlier evidence stale.

## Commands

| Purpose | Commands |
| --- | --- |
| Agent guidance | `guide`, `next` |
| Integrity | `lint`, `validate`, `check`, `test` |
| Evaluation | `run`, `value`, `compare` |
| Interrogation | `trace`, `dag`, `explain`, `show` |
| Exploration | `sens`, `mc`, `try` |
| Changes and learning | `patch`, `record`, `log`, `replay` |
| Ingestion proposals and output | `calibrate`, `export`, `emit` |
| Visualization | `plot` (series, scenario bars, driver diagrams) |
| Interactive decisions | `dashboard` (assumption sliders, live valuation, experiment log) |

```sh
burr -C examples/lemonade trace stand profit
burr -C examples/lemonade dag stand --format mermaid --formulas
burr -C examples/lemonade sens stand --x price=2:3:.25 --y wacc=.15:.25:.025
burr -C examples/lemonade mc stand --draws 1000 --seed 42 --full --json
burr -C examples/lemonade calibrate stand
burr -C examples/lemonade export stand -o artifacts/forecast.csv
burr -C examples/lemonade emit stand -o artifacts/model.xlsx
```

Every command accepts `--json`, `--seed N`, `-s/--scenario NAME`, `-C DIR`, and
`--version`, before or after the command. Paths, including output and patch paths,
are relative to `-C`. Companies can be addressed by workspace-local name, company
directory, or their `params.yaml`. `--help` lists commands and command options.

Exit status is **0** for success, **1** for model/patch diagnostics, and **2** for
usage and malformed-file errors. Machine output is one JSON document on stdout.
`mc --json` returns summary percentiles and a histogram; `--full` adds each draw.
Warnings do not change a successful exit status. `ingest` remains reserved, as
specified.

## Agent golden path

```sh
burr guide
burr --json -C examples/starbucks next starbucks \
  --patch patches/slower_traffic.yaml \
  --question 'What if customer visits do not recover?'
```

`guide` ships with the installed package. `next` validates the workspace, inspects
assumptions and journal evidence, evaluates a supplied patch, and replays the
selected experiment. It returns `action.argv` to execute, `resume_argv` for the
next inspection, or `required_inputs` when a patch, question, or finding is needed.
Supply those from the task context and inspected results; do not invent the
principal's objective. Use `--finding` to provide your reviewed interpretation.

The path is **validate → inspect → probe → record → compare/replay → export**.
Choose `--deliverable dashboard` (default), `csv`, or `excel`. Export actions use
`--receipt` to write a small `OUTPUT.burr.json` file. `next` checks its model
fingerprints and file hash before declaring that deliverable current. A stale
experiment must be reviewed and recorded again without overwriting the old entry.

`next`, `try`, and `replay` write nothing. `ok: true` means guidance succeeded;
check `state` and `complete` to determine progress. Completion covers the selected
experiment and requested deliverable, with the principal's broader question still
requiring your judgment. See [the installed guide source](burr/agent_guide.md) and
[repository agent instructions](AGENTS.md). `burr init` also returns `guide_argv`
and `next_argv` for programmatic discovery.

## Plots and diagrams

Create offline HTML charts or standalone SVGs directly from facts and model
outputs. No valuation configuration is required. Each metric has its own axis;
reported observations and forecasts remain distinct.

```sh
burr -C examples/starbucks plot starbucks --lines revenue,ebit,fcff \
  --all-scenarios -o artifacts/trends.html
burr -C examples/starbucks plot starbucks --kind scenarios --lines revenue,fcff \
  --period 2030 -o artifacts/scenarios.svg
burr -C examples/starbucks plot starbucks --kind drivers --lines revenue \
  -o artifacts/revenue-drivers.html
```

HTML includes series toggles, data inspection, SVG/data downloads, and printing.
Both formats embed source data and workspace fingerprints. See
[plotting documentation](docs/plots.md) for options and interpretation, or open
the [Starbucks business charts](examples/starbucks/artifacts/business-trends.html).

## Interactive decision dashboards

Turn assumptions into sliders and see their effect on forecasts and implied
value per share in a standalone HTML file. Save experiments with notes, restore
choices, and download the local log or a replayable model patch.

```sh
burr -C examples/lemonade dashboard stand --slider price=1:4:.05 \
  --slider valuation.wacc=.08:.3:.005 -o artifacts/dashboard.html
```

Open the [Starbucks decision dashboard](examples/starbucks/artifacts/dashboard.html)
or the [lemonade dashboard](examples/lemonade/artifacts/dashboard.html).
Users can add sliders and edit ranges in the browser. See
[dashboard documentation](docs/dashboards.md) for annual inputs, logging, and
recording downloaded choices in the workspace journal.

## Spreadsheet output

The workbook contains editable blue inputs on **Assumptions**, real formulas on
**Model**, a live **DCF**, and a protected **Actuals** sheet. Green formulas link
across sheets; black formulas calculate within a sheet. Metadata is attached as
input-label comments, and growth-factor helper rows are hidden on Model.

Before emission, burr saves and reloads the workbook, evaluates the actual Excel
cell graph with a separate calculator, and compares every model output and DCF
summary to the DSL engine. A disagreement prevents the write. Cached formula
results support readers that do not calculate formulas; Excel and LibreOffice
can recalculate editable inputs when opened. No Excel/LibreOffice installation is
required. The bundled calculator supports the formula subset burr emits; it is
not a general spreadsheet importer.

## Language and implementation conventions

See [docs/semantics.md](docs/semantics.md) for value forms, recurrence semantics,
patch envelopes, valuation conventions, and the resolutions of ambiguous or
contradictory passages in the specification. JSON contracts are provided in
[schemas/1.0.0.json](schemas/1.0.0.json).

## Development

```sh
.venv/bin/pytest -q
.venv/bin/burr -C examples/lemonade test stand --json
```

The tests cover the closed grammar, units, value forms, recurrence and vector
agreement, hand-calculated valuations, CLI exit codes, scenario attribution,
patch rollback, journal staleness, deterministic random draws, and independently
recalculated spreadsheet formulas. The implementation uses the standard library
plus PyYAML and openpyxl.
