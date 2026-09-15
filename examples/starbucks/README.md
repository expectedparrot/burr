# Starbucks: a worked Burr model

Explore the [decision dashboard](artifacts/dashboard.html),
[operating scenarios](artifacts/business-trends.html), and
[revenue drivers](artifacts/revenue-drivers.html).

This is a **fixed FY2025 teaching baseline**, using reported FY2024–FY2025 data
from [Starbucks’ October 29, 2025 results release](https://investor.starbucks.com/news/financial-releases/news-details/2025/Starbucks-Reports-Q4-and-Full-Fiscal-Year-2025-Results/).
Forecasts for FY2026–FY2030 are tutorial assumptions. Later disclosures and changes
in business ownership are outside this snapshot. The valuation discounts from
FY2025 year-end; it is not a current price target.

## Try the example

From the Burr source directory:

```bash
burr --json -C examples/starbucks test starbucks
burr --json -C examples/starbucks compare starbucks
burr --json -C examples/starbucks trace starbucks revenue
burr --json -C examples/starbucks try starbucks patches/slower_traffic.yaml
burr --json -C examples/starbucks log starbucks --param traffic_growth
burr --json -C examples/starbucks replay starbucks exp-001
```

`--json` controls output. The patch input remains YAML.

## What drives the business?

Company-operated revenue compounds three assumed growth factors:

```text
annual growth = (1 + footprint growth) × (1 + traffic growth) × (1 + ticket growth) − 1
total revenue = company-operated revenue + licensed revenue + other revenue
operating income = total revenue × operating margin
FCFF = operating income − taxes + depreciation − capex − incremental working capital
```

Footprint growth represents the revenue contribution of capacity and maturation.
Traffic and ticket are illustrative aggregate growth factors, not forecasts of
Starbucks’ formally defined comparable-store metrics. Licensed revenue is what
Starbucks recognizes from licensees; it excludes their retail sales. The other
revenue category differs from the Channel Development reporting segment.

## Facts and assumptions

Historical USD millions, from the annual columns of the primary release:

| Metric | FY2024 | FY2025 |
| --- | ---: | ---: |
| Company-operated revenue | 29,765.9 | 30,744.8 |
| Licensed revenue | 4,505.1 | 4,350.4 |
| Other revenue | 1,905.2 | 2,089.2 |
| Total revenue | 36,176.2 | 37,184.4 |
| Operating income | 5,408.8 | 2,936.6 |

See [the source register](sources/README.md) and [row-level evidence](sources/reported.csv).
Annual operating observations live in [actuals.csv](companies/starbucks/actuals.csv).

All forward assumptions have rationales in [params.yaml](companies/starbucks/params.yaml):
2% capacity contribution, 2% average-ticket growth, 4% licensed and other revenue
growth, 25% tax, D&A at 4.7% of revenue, capex declining from 6.5% to 6%, and
incremental working capital at 2% of the revenue change.

| Scenario | Annual traffic growth, 2026 → 2030 | Operating margin, 2026 → 2030 | Model value/share |
| --- | --- | --- | ---: |
| Bear | 0% throughout | 8% → 10% | $21.15 |
| Base | 1% → 3% | 10% → 14% | $39.98 |
| Bull | 3% → 4% | 12% → 16% | $52.30 |

These are conditional model outputs. All scenarios use 9% annual WACC and 2.5%
terminal growth; base terminal value supplies about 78.8% of enterprise value.
The saved experiment isolates flat traffic and lowers base value by $3.42/share
to $36.56, holding the other assumptions fixed.

## Valuation conventions

- All cash flows and capital amounts are **USD millions**, with **millions of
  shares** as the denominator, yielding dollars per share.
- The FY2025 capital bridge is cash 3,219.8 + short-term investments 247.2 −
  current debt 1,498.9 − long-term debt 14,575.9 − noncontrolling interests 7.4
  = **−12,615.2**. Debt uses reported carrying amounts. Other investments receive
  no separate capital add-on; investee earnings remain within operating income.
- The denominator is **1,136.9 million** year-end common shares, held fixed.
  Future repurchases and incremental equity-award dilution are not modeled.
- Operating margins include rent and equity compensation. Lease liabilities are
  not subtracted again, and equity compensation is not added back to cash flow.
- FCFF is an approximate unlevered cash-flow measure. It does not reproduce the
  reported operating cash-flow reconciliation or explicitly schedule leases,
  deferred revenue, restructuring payments, or acquisitions.
- Traffic, ticket, capacity, and margin can be changed independently. The model
  does not estimate their causal relationships. No distributions are specified,
  so Monte Carlo would repeat the deterministic result until uncertainty is added.

## Regenerate the outputs

```bash
burr -C examples/starbucks dashboard starbucks \
  --slider traffic_growth=-.05:.05:.005 \
  --slider operating_margin=-.05:.05:.005 \
  --title 'Starbucks | FY2025 teaching baseline | USD millions' \
  -o artifacts/dashboard.html
burr -C examples/starbucks plot starbucks --lines revenue,ebit,fcff \
  --all-scenarios --title 'Starbucks: operating scenarios' \
  --note 'USD millions. FY2024–FY2025 history; FY2026–FY2030 tutorial assumptions.' \
  -o artifacts/business-trends.html
burr -C examples/starbucks plot starbucks --kind drivers --lines revenue \
  -o artifacts/revenue-drivers.html
burr -C examples/starbucks export starbucks -o artifacts/starbucks.csv
burr -C examples/starbucks emit starbucks -o artifacts/starbucks.xlsx
```

Dashboard sliders for annual profiles shift every year by the selected amount;
their default zero preserves the original trajectory. Ratios use decimals in the
CLI and percentage points in these browser controls. The dashboard’s browser log
is separate from the workspace experiment journal.

The [Excel workbook](artifacts/starbucks.xlsx) contains editable assumptions and
formulas independently recalculated and checked by Burr before export.
