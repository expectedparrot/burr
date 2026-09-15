# Built-in plots

`burr plot` renders the business model and reported observations directly to
standalone **HTML** or **SVG**. It works without a valuation configuration and
does not calculate share prices. This is an additive extension to the v1 command
surface, implemented with no new dependencies.

```sh
# Historical observations and the selected forecast, one panel per metric.
burr -C examples/starbucks plot starbucks --lines revenue,ebit,fcff \
  -o artifacts/trends.html

# Compare every scenario over time.
burr -C examples/starbucks plot starbucks --lines revenue,fcff \
  --all-scenarios -o artifacts/scenario-trends.html

# Compare operating outcomes at a particular forecast date.
burr -C examples/starbucks plot starbucks --kind scenarios \
  --lines revenue,ebit --period 2030 -o artifacts/scenarios.svg

# Explore the actual formula dependencies of revenue.
burr -C examples/starbucks plot starbucks --kind drivers --lines revenue \
  --period 2026 -o artifacts/revenue-drivers.html

# Reported history only; allows extra actuals that have no forecast line.
burr -C examples/starbucks plot starbucks --lines operating_cash_flow \
  --actuals-only -o artifacts/reported-operating-cash-flow.html
```

## Options and semantics

| Option | Behavior |
| --- | --- |
| `--kind series` | Default. Annual actuals plus forecast trajectories. |
| `--kind scenarios` | Bars for base and all named scenarios, for each selected metric. |
| `--kind drivers` | Upstream formula graph for exactly one line; values at the selected period. |
| `--lines a,b` | Required. One to 24 line names. Each metric gets its own panel and axis. |
| `--all-scenarios` | Include every scenario in a series plot. |
| `--actuals-only` | Plot annual actuals only; mutually exclusive with `--all-scenarios`. |
| `--period YEAR` | Year for scenario bars or driver values; defaults to the last forecast year. |
| `--title TEXT` | Override the document title. |
| `--note TEXT` | Add context, currency, timing, or metric-comparability qualifications. |
| `-o PATH` | Required. `.html` or `.svg`; relative to `-C`. |

The usual `-s/--scenario`, `-C`, and `--json` flags apply. Scenario bars always
include all scenarios; other plots use the selected scenario unless overridden
by `--all-scenarios`. Plotting validates/evaluates the selected model(s), even for
an actuals-only view. It does not mutate facts, assumptions, or the journal.

Reported points are solid; forecasts are dashed and the forecast area is shaded.
Missing years and the history/forecast boundary are never joined. Bars start at
zero, and signed values are supported. Ratios use percentage labels while raw
downloaded values remain decimals. Currency labels follow declared units; the
engine does not infer a currency code. Add the currency in `--note` when needed.
Extra reported lines without a model unit are labeled **Unit unspecified**.

Actuals match forecasts only by exact line name. The plotting tool cannot infer
whether two definitions are economically comparable. For example, Starbucks'
reported `operating_cash_flow` includes financing-related cash-flow effects and
other adjustments absent from modeled unlevered `fcff`. They remain separate
metrics. Quarterly supplemental observations are not silently mixed into the
annual `actuals.csv` series.

Driver diagrams include all upstream inputs and formulas. Solid arrows show
same-period dependencies, dashed arrows show `lag` dependencies. Input boxes are
shaded; formula boxes are white. Hover exposes formulas or input metadata. The
data table includes exact values, units, formulas, rationales, and provenance.
This is a formula dependency diagram, not evidence that the relationships are
causal. Large graphs can be scrolled horizontally.

## HTML, SVG, and reproducibility

HTML charts include series checkboxes, point tooltips, expandable data tables,
SVG downloads, a JSON data download, and print styling. Hiding a series preserves
the axes for comparison. SVG downloads include all series, as the button label
states. Both formats embed the underlying data and scenario-specific workspace
fingerprints. HTML includes all styling and scripts locally, with no CDN or
network requests. There is no Markdown/math parsing in the plot renderer.

Identical model inputs and arguments produce byte-identical output. Artifacts
are snapshots; regenerate after changing the model. Chart output uses atomic
writes, preserves an existing artifact if validation/rendering fails, and cannot
overwrite protected workspace source paths.

`--json` returns one object with `ok`, `output`, `kind`, `entity`, `title`, `note`,
`fingerprints`, `scenario_theses`, and `panels`. A series/scenario panel has `line`,
`unit`, and `rows` with raw values, periods, scenario, `kind` (`reported` or
`forecast`), and provenance. A driver panel has `line`, `scenario`, `period`,
`nodes`, and `edges`, including the `lagged` flag. JSON is also embedded in SVG
`metadata` and the HTML `plot-data` element.

The initial plot command supports operating trends, scenario bars, and driver
diagrams. The existing `sens` and `mc` commands still produce their original
table/JSON outputs; they do not yet have built-in graphical renderers.
