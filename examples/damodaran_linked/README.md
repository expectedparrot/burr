# Two-stage model with linked valuation assumptions

This is a corrected copy of the fresh agent's Damodaran two-stage workspace.
The original submission and evaluation records are preserved under
`benchmarks/damodaran/agent_pilot`.

```yaml
valuation:
  fcf: fcff
  wacc: {ref: wacc}
  terminal_growth: {ref: stable_growth}
  shares: {ref: shares}
  net_cash: {ref: net_cash_after_options}
```

Native DCF now reads its assumptions from the current model. Changing risk-free
rate, shares, cash, debt, options, or stable growth updates their dependent
calculations without rerunning an adapter. Excel exports retain formula links;
the browser recalculates them when their source inputs change. Numeric valuation
overrides are still permitted as explicit independent assumptions.

```sh
.venv/bin/burr -C examples/damodaran_linked value fcff
.venv/bin/burr --json -C examples/damodaran_linked next fcff \
  --patch patches/riskfree.yaml \
  --question 'Does changing the risk-free input now update native DCF consistently?' \
  --deliverable excel --output artifacts/fcff-base.xlsx
.venv/bin/burr -C examples/damodaran_linked dashboard fcff \
  --slider riskfree=.053:.08:.001 -o artifacts/fcff-dashboard.html
```

The base remains 66.7825642 per share. The recorded trial raises the risk-free
rate from 5.3% to 7.07%, producing 44.7010442, matching the source workbook.
The base export shows the unchanged saved base; the trial is in the journal.
`exp-001` is the preserved original experiment. `exp-002` records the fix's
verification without rewriting historical evidence.

The new regressions check all 15 pilot cases against the independent source
oracle, including changes to every valuation dependency, through Python,
edits to exported Excel inputs, and browser edits with replayable patches.
These use the existing spreadsheet oracle, not new agent trials.

Source assumptions are historical illustrations, not current financial facts.
The fixed switches and five-year growth horizon are unchanged. Period six is
the first stable cash-flow year, reconciling Burr's terminal convention with
the source's year-five boundary. See the preserved pilot notes for that algebra.

Reproduce a fresh corrected workspace (new directory required):

```sh
.venv/bin/python -m benchmarks.damodaran.linked_pilot --output /private/tmp/linked-fcff
.venv/bin/python -m benchmarks.damodaran.workflow_eval --linked-valuation \
  --output /private/tmp/linked-fcff-workflow
```
