The submitted program reconstructs the selected Damodaran two-stage FCFF spreadsheet using the vendored, unmodified Burr engine. It builds an ordinary YAML workspace, evaluates forecast and valuation formulas in Burr, uses Burr's native DCF, and exports a verified Excel workbook. No spreadsheet or cached baseline answers are read by submission.py at runtime.

Run from this packet:

```sh
PYTHONPATH=vendor /Users/johnhorton/tools/ep/burr/.venv/bin/python -S submission.py --inputs baseline.json --output baseline-output.json --workspace model --excel output/baseline.xlsx
```

Only --inputs and --output are required. Without the optional artifact paths, each invocation creates a unique persistent workspace beneath runs/ and an Excel export inside that workspace. Input and output paths can be arbitrary. The code locates vendor/ relative to submission.py, independently of the current working directory.

Conventions and formulas

- Numeric inputs retain their source cell addresses and assumption rationale in params.yaml and Excel comments. The packet supplies spreadsheet assumptions, not independently verified financial facts; actuals.csv therefore contains its header only. Currency and share count use the source's consistent scale, without an invented millions conversion. Periods 1–5 are high-growth years; period 6 is the terminal cash-flow year, not an additional high-growth year.
- Cost of equity is riskfree + beta × risk premium. Market equity weight is share_price × shares / (debt + share_price × shares). After-tax debt cost is debt_cost × (1 − tax_rate); WACC uses these equity and debt weights. The selected switches preserve WACC in the stable phase.
- Fundamental growth is reinvestment rate × return on capital. Return on capital is EBIT after tax divided by prior book debt plus prior book equity. Reinvestment rate is capex minus depreciation plus historical working-capital change, divided by EBIT after tax. These are evaluated separately, preserving the source's dependency structure.
- High-growth NOPAT, capex, depreciation, and revenue grow at fundamental growth. Forecast working-capital change is the revenue change multiplied by max(working_capital0/revenue0, 0); historical working_capital_change0 affects fundamental growth, not this forecast formula directly.
- Terminal NOPAT and revenue grow at stable_growth. Terminal net capex is terminal NOPAT × stable_growth/stable_roc minus terminal working-capital change. FCFF is NOPAT minus net capex minus working-capital change.
- Source terminal value is terminal FCFF/(WACC − stable_growth), discounted five periods. Enterprise value adds the first five FCFF present values. Equity before options adds cash and subtracts market debt; per share subtracts options and divides by shares.
- All these forecast amounts and source valuation metrics are Burr formula lines. The adapter copies Burr-computed WACC and net cash after options into Burr's numeric native valuation configuration. It does not calculate forecast amounts or valuation answers in Python.

Burr native DCF convention

Burr's standard Gordon implementation assumes its final forecast cash flow continues into the following year. To preserve the source's distinct stable reinvestment rate without changing Burr, the workspace contains five high-growth years and the first stable cash-flow year. Burr's native DCF includes that sixth cash flow explicitly, then values year 7 onward at the end of year 6. Algebraically,

FCFF6/(1+w)^6 + FCFF6(1+g)/(w−g)/(1+w)^6 = FCFF6/(w−g)/(1+w)^5.

Thus native enterprise value and per-share value equal the source's five-year valuation. The program checks this equivalence on every invocation. Requested terminal_value and pv_terminal are taken from the Burr Model lines in period 5, matching source E147 and F150. The export's standard DCF sheet instead displays its own end-of-year-6 terminal subtotal; its enterprise value is the same. Native DCF equity includes the option deduction, whereas requested equity_before_options excludes it.

Verification completed

- Every requested baseline metric matched the source workbook's cached values at relative tolerance 1e-10 and absolute tolerance 1e-8.
- verify.py independently parses and recursively evaluates the actual source Excel formulas after substituting changed input cells. It is development tooling only; submission.py never imports it.
- All 56 changed-input cases passed: ±10% changes to each of the 20 variable numeric fields, negative and zero working capital, zero stable growth, a negative terminal FCFF case, and 12 combined deterministic random perturbations. The largest scaled relative discrepancy against independently evaluated source formulas was 2.424e-15. This is local verification, not evaluator feedback.
- Each test constructed a workspace and exported through Burr, which independently recalculates the emitted workbook formulas and verifies cached results.
- Baseline Burr next reached complete after validate/inspect, a stable-ROC sensitivity probe, append-only evidence recording, replay, and an Excel export with receipt. Stable ROC of 0.132 versus 0.12 raised per-share value from 66.7825642215609 to 71.97308385937993. The trial was not applied to the baseline. See workflow-record.json, model/companies/fcff/experiments/, output/baseline.xlsx.burr.json, and verification-report.json.
- Baseline EV: 69175.15233361626. Baseline equity before options: 67853.15233361626. Baseline per share: 66.7825642215609.

Limitations

The program intentionally supports the task's fixed source switches and five-year high-growth horizon only. Undefined source arithmetic (for example zero revenue, zero prior capital, zero stable ROC, or zero EBIT after tax) is not assigned fabricated values. Burr's native DCF additionally requires positive shares, WACC greater than terminal growth, WACC above −1, and terminal growth above −1; algebraically finite spreadsheet cases outside that valuation domain are rejected. Negative terminal FCFF within that domain is supported.

Because native valuation configuration accepts numeric assumptions rather than formula references, manually patching workspace bindings that affect WACC, net cash, shares, or stable growth requires regenerating the workspace with submission.py to synchronize native valuation assumptions. The submission does this on every invocation, including all changed-input verification runs. The recorded stable-ROC probe does not change those assumptions.

No external APIs, network resources, other packets, repository files, evaluator feedback, or external spreadsheet engine were used. No token or monetary measurements are claimed. Timing is recorded separately in timing.json.
