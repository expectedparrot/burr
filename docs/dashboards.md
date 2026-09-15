# Decision dashboards

`burr dashboard` creates a standalone HTML file with live operating forecasts,
implied value per share, and an experiment log. Open it in a modern browser;
it needs no server, internet connection, or spreadsheet software.

```sh
burr -C examples/lemonade dashboard stand -o artifacts/dashboard.html \
  --slider price=1:4:.05 --slider valuation.wacc=.08:.3:.005

burr -C examples/starbucks dashboard starbucks -o artifacts/dashboard.html \
  --slider traffic_growth=-.10:.10:.005 \
  --slider operating_margin=-.05:.05:.001 \
  --slider valuation.terminal_growth=0:.05:.005
```

Use `-s bear` to start from a named scenario and `--title 'Decision workshop'`
to customize the title. `--json` returns the output path, editable input count,
and model fingerprint. Output paths follow `-C` and cannot overwrite model sources.

## Turn an assumption into a slider

Choose an assumption in the dashboard and click **Make slider**. Use its slider
or exact numeric input to change the value. **Range and evidence** lets you edit
minimum, maximum, and step size and inspect the saved input's evidence. Suggested
ranges are mechanical starting points; choose ranges appropriate to the business.
They must contain both the saved value and current choice.

`--slider NAME=MIN:MAX:STEP` optionally enables a slider before sharing the file.
Names default to `bindings.NAME`; valuation inputs use `valuation.NAME`.
Command-line ratios use decimals (`.12` means 12%); browser controls display
percentages (`12` means 12%). **Return to fixed** removes a slider and restores
that input's saved value. **Reset values** restores all saved assumptions while
keeping the selected sliders.

Operating assumptions with annual profiles now have one **whole-forecast** slider
by default. Its mode determines the question you are asking:

- **Raise / lower every year:** add the chosen amount to each saved annual input.
  For a growth rate, +2 means +2 percentage points each year. The saved trajectory
  is preserved and zero returns the original forecast. The resulting growth rates
  still compound normally in the model.
- **Same value every year:** use one rate or value throughout the forecast. For
  example, choose 5% customer growth in every forecast year.
- **Gradually reach a target:** phase in the difference between the target and the
  saved final-year input. The first forecast year stays fixed; the last reaches
  your target. Intermediate years retain the saved trajectory plus a linearly
  increasing adjustment. This is a target for the assumption, not for the output
  metric or share price.

**Annual assumption values** shows the exact saved and chosen path. Switching
modes replaces the previous changes for that assumption. Reset restores the saved
path and returns whole-forecast controls to the neutral raise/lower mode.

For annual operating profiles, `--slider traffic_growth=-.1:.1:.005` controls a
change to all years. Ratios use decimal changes on the command line and percentage
points in this mode's browser control. Use `traffic_growth~level` or
`traffic_growth~target` to start in the other modes; their bounds are absolute
rates/values. Selecting a level immediately sets all years to its displayed value.

**Advanced: include individual years** exposes the original controls such as
`operating_margin@2028`. Annual discount-rate profiles also remain in this advanced list,
because their effective period rates may encode a partial first year. Scalar
inputs continue to use one absolute value. Distribution inputs start at their
deterministic resolved values. Shared world inputs and base-year bindings
reconciled to reported facts remain fixed.

The experiment log saves the selected mode, slider values, and complete resolved
patch. Older experiments with individual-year overrides can still be restored.

The dashboard shows your implied value per share, its difference from the saved
scenario, enterprise value, terminal contribution, and a selectable operating
forecast chart/table. Currency and share scaling come from the model; the tool
does not infer a currency code. Calculations match `burr value`, including its
period-specific discount rates. A model that encodes an initial stub period as
an effective discount rate retains that convention; changing that year's rate
changes the effective rate, not an annualized rate.

The chart and table include all available pre-forecast observations for the
selected metric from the company's `actuals.csv`. Blue points and lines show
reported history, gray dashed lines the saved forecast, and green lines your
choices. A shaded forecast region marks the boundary. Historical values remain
fixed as sliders change. Missing years appear as gaps and are not joined;
history and forecasts are separate series. Hover over a reported point to see its
year, value, and source file.

History matches the exact metric name and uses only years before the forecast.
Metrics without matching observations say so explicitly. For example, reported
FCF is not automatically substituted for modeled annual FCFF: the definitions
can differ. No historical values are estimated or backfilled.

Model checks run on each recalculation. Invalid inputs, nonfinite calculations,
and invalid terminal growth/discount-rate combinations clear the displayed
results and prevent saving. The file is a model snapshot: regenerate it after
changing workspace assumptions or logic.

## Save and share experiments

Enter a question or finding, then click **Save experiment**. Each explicit save
appends a timestamped entry containing:

- The starting scenario and model fingerprint.
- Your note, changed assumptions, and slider ranges.
- Forecast lines, valuation results, and the saved scenario's valuation.
- A patch compatible with Burr's existing exploration commands.

**Restore choices** revisits a saved experiment. Moving a slider alone does not
create a log entry. Log entries persist in browser local storage when available,
isolated by model fingerprint. Browser settings, file-URL handling, storage
limits, or clearing browser data may prevent persistence. A status message reports
storage failures and entries remain downloadable during the session.

**Download log** exports all entries as JSON for sharing or archiving. This is a
local working log, not a tamper-proof or shared audit trail, and is not synced to
Burr's workspace journal. There is currently no log import UI.

**Download current choices** exports a JSON patch (JSON is also valid YAML).
To validate and record those choices in the append-only workspace journal, use
an absolute download path and the same starting scenario:

```sh
burr -C examples/starbucks try starbucks /absolute/path/starbucks-choices.json -s base
burr -C examples/starbucks record starbucks /absolute/path/starbucks-choices.json -s base \
  --question 'What if customer growth improves?' \
  --finding 'Describe the observed result and the business rationale.' \
  --tags dashboard,growth
```

`record` recomputes results using the current workspace. Compare its fingerprint
with the downloaded log if the workspace has changed since the HTML was created.

## Verification

Python tests run the browser expression interpreter under Node and compare all
forecast lines and valuation fields against Burr's Python engine, including
recurrences, invalid trials, whole-forecast modes, annual overrides, and the bundled regression scenarios.

With Playwright and Chromium installed, run `node scripts/check_dashboard.cjs`
from the repository root using its existing regression fixtures. If Playwright
is installed elsewhere, set `BURR_PLAYWRIGHT_MODULE` to its module path. This checks
slider editing, ranges, invalid inputs, local logging, reload/restore, downloads,
storage failure, and mobile layout. Playwright is a development-only check, not a
runtime dependency of the package or emitted HTML.
