# Language conventions and engineering notes

The specification is authoritative. These conventions resolve places where its
examples and prose disagree or a storage syntax is unspecified.

## Formulas

Expressions support arithmetic, parentheses, unary minus, and only `grow`,
`delta`, `lag`, `minimum`, `maximum`, `clip`, and `abs`. No Python evaluation,
attributes, indexing, comprehensions, arbitrary functions, or I/O are available.
Checks accept one of `<`, `<=`, `>`, `>=`, `==`, or `!=` between expressions.

Section 4 bans numeric literals but both its marketplace example and Appendix A
use `1` in formulas. burr permits **structural 0 and 1**, including unary negative
forms, and rejects other numeric literals outside checks. Business constants must
be declared parameters with values in params. Checks may contain numeric
thresholds.

`grow(x0, g)` multiplies `x0` by the cumulative product of `(1 + g)`; `x0` must be
scalar. `delta` and `lag` take scalar base values. A reference to any model line
is a series, even in a one-period model. Scalars broadcast across the horizon.
Division by zero and nonfinite arithmetic are diagnostics.

The recurrence rule is interpreted as **every dependency cycle must contain a
lagged edge**, equivalently the graph of current-period dependencies must be
acyclic. This is the conventional lag-breaking interpretation of sections 4 and
5.2; the last sentence of 5.2 instead says every edge of a cycle must be lagged.
The latter would forbid ordinary mutually dependent stock/flow roll-forwards.
Self-lag and multi-line lag-broken cycles are supported. The seed argument of
`lag` is a current-period dependency; only its first argument is delayed.

Lag-free models use vector evaluation; models containing `lag` use period-by-period
evaluation. Both paths perform multiplication in the same order, including the
cumulative growth factor, and are tested for bit-identical lag-free results.

## Opinion forms

```yaml
bindings:
  scalar: 0.2
  annotated: {value: 0.2, rationale: a belief, source: a filing}
  series: [0.2, 0.21, 0.22]
  glide: {start: 0.2, end: 0.22, shape: linear}
  geometric: {start: 1, end: 4, shape: geometric}
  step: {until: {2028: 0.2}, after: 0.25}
  uncertain: {dist: normal, mean: 0.2, sd: 0.01, lo: 0.1, hi: 0.3}
  uniform: {dist: uniform, low: 0.1, high: 0.3}
  uncertain_endpoint:
    start: 0.18
    end: 0.22
    dist: normal
    mean: 0.21
    sd: 0.01
    applies_to: end
```

The step syntax shown in section 6.1 (`until: 2028: a`) is not valid YAML; use the
nested mapping above. The cutoff year is inclusive. `{value: ...}` is supported
because Appendix A uses it. Linear and geometric glides include both endpoints;
one-period glides resolve to `start`. Geometric endpoints must share a nonzero
sign. Forecast years must be consecutive and follow `base_year` immediately.

Deterministic runs replace distribution values/endpoints with their mean or
midpoint. Draw clamps apply only during Monte Carlo. Metadata does not alter
numeric evaluation; unit and confidence metadata are validated, and tolerance
controls fact cross-checks. A value-form mapping is a replacement leaf, so an
override must restate any rationale or distribution metadata it wants to keep.

The engine does not enforce the caller behavior in section 14: agents remain
responsible for sources, preserving rationales, and preferring scenarios. In
particular, the merge rule deliberately does not restore omitted rationale fields
from a replaced leaf.

`burr guide` makes the agent protocol available in installed distributions.
`burr next` is a read-only evidence router: it evaluates the model and supplied
patch, replays selected journal evidence, and checks optional export receipts.
It never creates assumptions, records a finding, or applies a patch by itself.
Its `ok` reports successful inspection; `state` and `complete` report workflow
progress. See [the agent guide](../burr/agent_guide.md) for selection rules and
completion criteria. These additions do not enforce the caller obligations above.

## Shared environment, units, and facts

`world.yaml` accepts a mapping of names to value forms, optionally wrapped in
`series:`. Templates may reference world names directly or declare them in their
parameter interface. Entity bindings and lines cannot shadow world names.

Template parameters accept `name`, `unit`, and `doc`. `extends` merges parameters
and lines and accumulates inherited checks. An override may omit its parent's
unit, but cannot change it. Template parameters and lines share one identifier
namespace. Identifiers and template/scenario filenames use `[a-z][a-z0-9_]*`.

Ratio multiplication preserves the other operand's unit. Counts multiplied by a
currency-denominated per-item price produce that currency unit. Currency and
currency_m cannot mix without an explicitly modeled conversion. Missing units
disable checks for affected terms; `lint --strict` reports `missing_unit`
warnings. Ratios above 1.5 in absolute magnitude produce `ratio_magnitude` warnings.

Segment decomposition declarations use this template syntax:

```yaml
decompositions:
  revenue: [marketplace_revenue, enterprise_revenue]
```

When a reported total and any of its reported segments overlap in a year,
`validate` requires every declared segment and a sum within 1%. Years with no
reported segments are skipped. Base-year `<line>0` bindings are compared to the
reported line with 0.5% relative tolerance by default. For exactly zero facts,
the absolute numerical floor is 1e-12. Duplicate actuals observations are errors.
Extra actuals lines are retained in exports.

## Valuation

DCF discounts the configured forecast line at each period's WACC. If WACC varies,
the discount factor is the cumulative product of `(1 + wacc[t])`. Gordon terminal
value uses the final WACC and final terminal growth. Terminal WACC must exceed
growth, WACC must exceed -1, and growth must exceed -1. Shares must be positive.
`net_cash` defaults to zero; `terminal_growth` defaults to zero.

Each numeric valuation setting also accepts `{ref: NAME}` with optional source,
rationale, and other value metadata. `NAME` must be a model input, world input,
or calculated line, not another valuation setting or an inline expression:

```yaml
valuation:
  fcf: fcff
  wacc: {ref: wacc}
  terminal_growth: {ref: stable_growth}
  shares: {ref: shares}
  net_cash: {ref: net_cash_after_options}
```

Define any needed expression as a template line. References use the current
scenario and the same Monte Carlo draws as its forecasts; they are not copied
numeric assumptions. Excel exports retain cell formulas, and dashboard edits
recalculate references. Edit the source binding in the dashboard; linked
valuation settings have no independent slider. An explicit numeric scenario
override intentionally replaces the reference. References cannot combine with
a numeric value form and are supported only in valuation settings. Known units
must match: ratios for discount/growth, count for shares, currency for net cash.
Existing numeric value forms retain their behavior; Burr does not infer links
between unrelated numeric settings that happen to have equal values.

Net cash and shares refer to the present valuation date: if supplied as a series
or glide, their **first** values are used. WACC uses every period; terminal growth
uses the last. `--exit-multiple M` replaces Gordon growth with final-period
`ebitda * M`, requiring a line named `ebitda`. Terminal weight is terminal PV / EV;
it is reported as zero when EV is exactly zero.

Attribution replaces each changed binding or valuation leaf individually in the
starting scenario, evaluates its per-share impact, then reports the unexplained
interaction residual explicitly. Metadata accompanies attribution. If an
intermediate one-at-a-time model violates a check, attribution returns that
diagnostic rather than inventing an impact. Sensitivity axes may use
`bindings.name` or `valuation.name` to disambiguate names.

## Patch envelopes

All examples below are accepted by `patch -f`. `try` and `record` also accept a
plain mapping containing `bindings` and/or `valuation`.

```yaml
op: add_scenario
name: premium
thesis: Customers accept a higher price.
bindings:
  price: {value: 3.0, rationale: Higher willingness to pay, source: customer interviews}
```

```yaml
op: set_binding
name: price
value: {value: 3.0, rationale: Revised price, source: customer interviews}
```

```yaml
op: set_valuation
valuation:
  wacc: 0.18
  terminal_growth: 0.01
```

```yaml
op: add_check
check: profit >= 0
```

```yaml
op: fork_template
name: conservative_lemonade
lines:
  profit: revenue * (1 - cost_pct) * (1 - cost_pct)
```

`set_binding` also accepts a `bindings` mapping; `set_valuation` also accepts
`name`/`value`. With `-s`, set operations update that scenario's inline or external
patch. `add_scenario` is always a patch over base and requires a new name on a
durable write; in-memory trials and replays can re-evaluate an already existing
name. Scenario files must not collide with inline scenarios.

`fork_template` materializes inherited logic under a new ID, applies line and
parameter edits, and binds the company to the fork. `template` optionally chooses
the source template. Parameter edits are a list of declarations; existing
bindings must still exactly satisfy the resulting interface (world values may
supply added parameters). `checks` can explicitly replace checks in a fork.
`add_check` modifies shared logic and validates all companies before committing.

Every durable patch validates base and all scenarios before any replacement.
When valuation is configured, `test` and patch validation also evaluate it so
zero shares or an invalid terminal denominator cannot pass the integrity gate.
Commands coordinate through an advisory lock on `burr.lock`. Single-file writes
use same-directory temp files, fsync, and atomic replacement. Multi-file forks
hold the lock across replacements and roll back earlier writes on a write error.
Readers using burr see a complete transaction; external direct file readers do
not participate in the lock. Multi-file commits are not a crash-recovery database
transaction if the process or machine is killed between replacements.

Initialization is the bootstrap exception to patch-only source writes. Exports
are atomic derived-artifact writes and cannot target templates, companies, the
version pin, or world data. The journal uses exclusive file creation.

## Journal and determinism

The fingerprint includes resolved params and actuals, plus resolved template
logic, shared environment, and engine/schema versions. Including logic and world
values ensures that their changes invalidate evidence as well. Journal files
themselves are excluded. Replay compares both headline results and individual
attributions and never rewrites the original entry.

Evaluation and serialization are deterministic under a fixed engine/workspace/
seed. JSON keys, graph nodes, result rows, and scenario traversal have stable
ordering. Workbook ZIP timestamps and document metadata are normalized, and
cached formula values are included. `record` deliberately writes a current UTC
timestamp and the next sequential ID: these journal side effects are the
necessary exception to the spec's blanket same-command/same-output statement.

Monte Carlo follows section 12.2's narrower contract: individual draws appear
only with `--full`; `--json` alone returns percentiles and histogram bins. This
resolves the conflicting wording in section 10.4. No rejected draws are silently
discarded; a failing draw reports its one-based index as a diagnostic.

Numeric assertions written as `gap: N`, `base_per_share: N`, or
`trial_per_share: N` in a finding are checked against attached results and flagged
when inconsistent. Unstructured numerical prose is preserved without attempting
to infer its meaning.

`calibrate` proposes reported base values, annual observed growth, and ratios
recoverable from the template's driver equations. It does not estimate unobserved
drivers, run an optimizer, or apply its proposal.

## Spreadsheet verification

The Excel compiler walks the validated DSL AST. The independent cell calculator
then reads the **serialized workbook**, tokenizes Excel formulas, resolves cell
and range references, and evaluates arithmetic plus SUM/MIN/MAX/ABS. It does not
call the DSL evaluator or replace formulas with engine output. All Model cells
and the four DCF summary metrics must agree within 1e-10 relative / 1e-9 absolute
tolerance before writing. Cached results are verified on a final read.

This checks the generated formula subset without a third-party spreadsheet
application. Actuals sheet protection discourages editing, but is not an access
control or encryption mechanism. `ingest` is reserved and never imports a
returned workbook.
