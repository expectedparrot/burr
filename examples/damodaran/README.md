# Runnable Damodaran models

Three Burr models reconstructed from Aswath Damodaran's historical FCFF
spreadsheets, with 23 baseline and perturbation scenarios. The templates and
parameters are ordinary Burr YAML and run without the benchmark adapter.

| Model | Firm value | Equity value per share | Workbook |
| --- | ---: | ---: | --- |
| Stable growth | 13,147.560971 | Not supplied by source | [Excel](artifacts/stable-base.xlsx) |
| Two-stage growth | 69,175.152334 | 66.782564 | [Excel](artifacts/two_stage-base.xlsx) |
| Three-stage growth | 66,666.833118 | 44.011222 | [Excel](artifacts/three_stage-base.xlsx) |

Values retain the source workbooks' native units and illustrative assumptions.
They are not current company valuations. The stable model's one synthetic share
makes Burr's per-share output equal firm value. Its actual share count and equity
bridge are not modeled. Periods are relative years beginning at 1.

## Run and inspect

From the repository root:

```sh
.venv/bin/burr --json -C examples/damodaran next three_stage
.venv/bin/burr -C examples/damodaran compare three_stage
.venv/bin/burr -C examples/damodaran run three_stage
.venv/bin/burr -C examples/damodaran trace three_stage fcff
.venv/bin/burr -C examples/damodaran -s margin_down value three_stage
```

The companies are `stable`, `two_stage`, and `three_stage`. Each has an empty
`actuals.csv`, since the source inputs are benchmark assumptions rather than
independently ingested reported facts. Cell references and rationales are preserved
in `params.yaml`. The [source manifest](../../benchmarks/damodaran/sources.json)
pins the originals by URL and SHA-256 hash.

All three models include a recorded, replayable experiment increasing the
risk-free rate by one percentage point:

```sh
.venv/bin/burr -C examples/damodaran replay three_stage exp-001
.venv/bin/burr --json -C examples/damodaran next three_stage \
  --patch patches/three_stage_discount_up.yaml \
  --question 'Does the runnable Burr model reproduce the source workbook under a higher discount rate?' \
  --deliverable excel --output artifacts/three_stage-base.xlsx
```

WACC and terminal-growth valuation settings now reference their model line or
binding; the patch only changes the risk-free input. Expanded annual operating
profiles are still adapter inputs: when changing the primitives used to build
those profiles, regenerate or update the dependent profiles too. Named
scenarios contain those coordinated changes. For a two-stage model whose
primitive inputs and valuation assumptions are all linked, use
[the corrected pilot workspace](../damodaran_linked/README.md).
Original `exp-001` records remain intact; `exp-002` records review after the
valuation migration. The [benchmark guide](../../benchmarks/damodaran/README.md)
explains the terminal-year conventions and how the profiles were derived.

## Verify and export

```sh
.venv/bin/burr -C examples/damodaran emit three_stage \
  -o artifacts/three_stage-base.xlsx --receipt

# Requires LibreOffice. Recalculate every formula in all 23 exported workbooks
# and compare this saved workspace with the external source references.
.venv/bin/python -m benchmarks.damodaran.exercise \
  --workspace examples/damodaran \
  --output examples/damodaran/artifacts/verification.json
```

The [verification report](artifacts/verification.json) records source agreement,
external recalculation results, and fingerprints for every saved scenario.
Base-case workbooks remain here for inspection; the checker uses temporary files
for its 23-case export run. Microsoft Excel itself has not been used for these
checks. This exercise validates runnable reconstructions, not a blinded agent eval.
