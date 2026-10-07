# Direct Python / Excel reconstruction

`submission.py` independently computes the requested FCFF metrics from the complete input JSON and authors a new Excel workbook with live formulas. It does not open the source spreadsheet, contract, or baseline at runtime; only the explicitly supplied input JSON is read. It uses the supplied vendored openpyxl package and standard library.

Run from this packet:

```sh
PYTHONPATH=vendor /Users/johnhorton/tools/ep/burr/.venv/bin/python -S submission.py --inputs baseline.json --output baseline-output.json
```

Input and output paths may be arbitrary absolute or relative paths, including paths containing spaces. The model locates its vendored dependency relative to its own file. For any JSON destination `DIRECTORY/NAME.json`, its new Excel export is `DIRECTORY/output/NAME.xlsx`. The baseline export is `output/baseline-output.xlsx`.

The workbook has editable numeric inputs on `Inputs`, live operating and valuation formulas on `Model`, and live contract-ordered references on `Outputs`. It requests automatic/full recalculation when opened. No source workbook is copied and no calculated caches are injected. Values in the JSON are calculated directly by Python.

## Source conventions preserved

All rates are decimal fractions. Currency and share counts retain the supplied source units without conversion. The source selections and five-year horizon are fixed as specified in the contract.

- Current NOPAT is EBIT times one minus the tax rate.
- Return on capital uses prior book debt plus prior book equity. Current cash is not deducted from that denominator.
- Reinvestment rate is current capex minus depreciation plus historical working capital change, divided by current NOPAT. High growth is the product of this rate and return on capital. The two intermediates are retained even though their product algebraically cancels current NOPAT.
- Cost of equity is the risk-free rate plus beta times the equity risk premium. Equity weight uses current share price times shares, divided by that market equity value plus debt. Debt weight is one minus equity weight. WACC weights this cost of equity and after-tax debt cost. Stable WACC is identical under the selected switches.
- NOPAT, capex, depreciation, and revenue grow at the same fundamental high-growth rate during the five explicit years. Net capex is forecast capex less forecast depreciation.
- The working capital ratio is current working capital divided by revenue, floored at zero. Forecast working capital change uses this ratio times the change in revenue. Historical working capital change affects fundamental growth; it is not directly rolled forward as forecast working capital change. Revenue therefore affects the reported ratio but algebraically cancels out of cash flows when current working capital is positive and held fixed.
- Terminal NOPAT is year-five NOPAT grown once at the stable growth rate. Terminal working capital change uses year-five revenue times stable growth times the working capital ratio, preserving the source's subtraction order.
- Stable total reinvestment is terminal NOPAT times stable growth divided by stable return on capital. Terminal net capex is that total less terminal working capital change. Terminal FCFF deducts both components exactly once.
- Terminal value is terminal FCFF divided by stable WACC less stable growth. It is discounted five years. Enterprise value is discounted explicit FCFF plus discounted terminal value. Equity before options adds cash and subtracts debt. Per-share value additionally deducts options, then divides by shares.

All four six-element arrays contain years one through five followed by the terminal year. The PV FCFF array contains only the five explicit years. All scalar metrics are one-element arrays.

## Verification

`baseline-output.json` matches every one of the 16 required metrics against the source workbook's cached baseline results. The largest absolute baseline difference is approximately 2.91e-11, attributable to floating-point precision.

`verify.py` is a development-only independent interpreter of the small formula subset used by the source. It recursively evaluates the original source formulas with substituted inputs, including lazy IF selection, SUM ignoring blank-year text, and Excel's text-versus-number ordering. It is not imported or used by the submission.

247 scenarios passed comparisons against these source formulas: baseline, two individual perturbations for each of the 20 variable numeric inputs, 200 deterministic combined perturbations, and six edge cases (negative and zero working capital, zero and negative stable growth, negative high growth, and zero debt). The fixed horizon was not perturbed. Three freshly generated live-formula workbooks also matched Python output using the same independent formula interpreter. Tolerances were 2e-12 relative or 2e-9 absolute. `verification.json` records the results.

An additional subprocess check ran the CLI from another directory inside this packet with absolute input/output paths containing spaces, and verified its JSON values and workbook creation.

## Limitations and scope

This reconstruction deliberately supports the current switches and five-year horizon only; another horizon is rejected. It requires the complete set of finite numeric input fields. Inputs with zero denominators (for example zero revenue, zero NOPAT, zero prior book capital, zero shares, zero stable return on capital, or stable growth equal to WACC) are outside the finite-output model domain, just as the spreadsheet would produce errors. It preserves the source's arithmetic, including a negative terminal value if stable growth exceeds WACC, rather than imposing an extra economic correction.

No Excel or LibreOffice engine was run. The generated workbook contains formulas without cached results, so consumers using `data_only=True` before a spreadsheet application recalculates it will see missing formula values. The baseline values are available separately in the JSON. The development formula interpreter is limited to this workbook's formula subset, not a general spreadsheet engine. No external evaluator results or outside financial sources were used. Token usage and monetary cost were not measurable.
