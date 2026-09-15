# burr(1) — Specification

**burr** — a domain-specific language and command-line tool for
driver-based firm modeling, valuation, and structured scenario
exploration.

Version 1.0. This document is the complete, normative specification.
Implementations MUST satisfy every requirement stated with MUST/MUST NOT;
SHOULD denotes strong defaults.

---

## 1. Philosophy

`burr` treats a financial model as an argument between explicit
beliefs, not a grid of numbers. Its design commitments:

1. **Four kinds of content, four homes.** Logic (how a kind of business
   works), facts (what was reported), opinions (what you believe), and
   questions (what you ask) are stored separately and may not mix.
2. **Deterministic and total.** The same workspace and command always
   produce byte-identical output; every failure is a structured
   diagnostic, never a crash.
3. **Small action surface.** All writes go through validated, atomic
   patches. All artifacts are line-oriented text, reviewable as diffs.
4. **Evidence travels with conclusions.** What was tried, what resulted,
   and what was concluded are recorded together, reproducibly, with
   staleness tracked when the underlying model changes.
5. **The DSL is the source of truth.** Spreadsheets and datasets are
   compile targets, never inputs.

The tool is equally operable by humans and by LLM agents; §14 defines
the agent protocol. `burr` does not know what its callers are doing —
research, planning, or multi-agent exercises — and MUST NOT acquire
features that presume a use case (see §16, Non-goals).

## 2. Invocation

```
burr <command> [arguments] [options]
```

Global options, valid on every command:

| Option | Meaning |
|---|---|
| `--json` | machine-readable output on stdout (schemas: §12) |
| `--seed N` | seed for all stochastic behavior (default 42) |
| `-s, --scenario NAME` | operate on a named scenario (default: base) |
| `-C DIR` | run as if invoked from DIR |
| `--version` | print engine and schema versions |

Exit codes (agents branch on these):

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | model diagnostics — the workspace or patch is invalid or failed checks; details on stdout as diagnostics (§12.1) |
| 2 | usage error — bad flags, missing files, malformed YAML |

Human-readable output goes to stdout; incidental progress to stderr.
With `--json`, stdout carries exactly one JSON document.

## 3. Workspace

```
workspace/
├── burr.lock                # engine + schema version pin
├── world.yaml                 # optional shared exogenous series (§7.3)
├── templates/
│   └── <template>.yaml        # LOGIC
└── companies/
    └── <entity>/
        ├── params.yaml        # OPINIONS (binds exactly one template)
        ├── actuals.csv        # FACTS
        ├── scenarios/         # optional shared patch files (§9)
        │   └── <name>.yaml
        └── experiments/       # journal, append-only (§13)
            └── exp-NNN.yaml
```

`burr init [--template NAME] <dir>` scaffolds a workspace, writes
`burr.lock`, and creates a commented starter template and params file.

`burr.lock` records `engine_version` and `schema_version`. Commands
MUST refuse (exit 1, code `version_mismatch`) to operate on a workspace
whose lock requires a newer engine.

## 4. Templates (logic)

A template defines how a *kind* of business works. It contains no
numeric literals outside `checks`.

```yaml
template: marketplace_platform        # id referenced by params files
doc: two-sided marketplace with an optional managed segment

parameters:                           # the interface, exhaustive
  - name: take_rate
    unit: ratio                       # §8
    doc: marketplace revenue / marketplace GSV
  - mkt_gsv0                          # bare-string shorthand: unit unknown

lines:                                # name: expression (§5)
  mkt_gsv:  grow(mkt_gsv0, (1 + client_growth) * (1 + spend_growth) - 1)
  revenue:  mkt_gsv * take_rate + ent_gsv * ent_take_rate
  ...

checks:                               # invariants evaluated on every run
  - ebitda <= gross_profit
  - revenue >= 0
```

Rules:

- Every parameter MUST be used by at least one line (`lint`:
  `unused_parameter`); every name a line references MUST be a parameter
  or another line (`lint`: `unknown_name`).
- Line and parameter names share one namespace of identifiers matching
  `[a-z][a-z0-9_]*`.
- Dependency cycles are errors (`circular_dependency`), except cycles
  passing through `lag` (§5.2).
- Templates MAY declare `extends: <template>` to inherit and override
  another template's parameters and lines; a child MAY add lines and
  parameters and MAY replace a line, but MUST NOT silently change a
  parameter's declared unit.

## 5. Formula language

Deliberately closed: no loops, no conditionals, no user-defined
functions, no I/O. Grammar:

```
expr    := term (("+" | "-") term)*
term    := unary (("*" | "/") unary)*
unary   := "-" unary | factor
factor  := NUMBER | NAME | "(" expr ")" | call
call    := FUNC "(" expr ("," expr)* ")"
FUNC    := "grow" | "delta" | "lag" | "minimum" | "maximum"
         | "clip" | "abs"
```

Every expression evaluates to a scalar or a length-N series, where N is
the forecast horizon; scalars broadcast. Division by zero is a
diagnostic (`eval_error`), not infinity.

### 5.1 Builtins

| Function | Semantics |
|---|---|
| `grow(x0, g)` | `x0 · cumprod(1 + g)`: compound a base-year scalar along a growth series |
| `delta(x, base0)` | period-over-period change of `x`, first period measured against `base0` |
| `lag(x, base0)` | the prior period's value of `x`; `base0` seeds period 1 |
| `minimum(a,b)` `maximum(a,b)` `clip(x,lo,hi)` `abs(x)` | elementwise |

### 5.2 Recurrence semantics

`lag` may reference the line being defined
(`cash: lag(cash, cash0) + fcf`), enabling balance-sheet roll-forwards.
When any line in a template uses `lag`, the engine evaluates
period-by-period in topological order per period; otherwise evaluation
is vectorized. The two strategies MUST agree bit-for-bit on
lag-free models. Cycles are legal only if every edge in the cycle
passes through a `lag`; all other cycles are `circular_dependency`.

## 6. Params files (opinions)

```yaml
entity: marketplace_demo
template: marketplace_platform
periods: 2026..2031
base_year: 2025

bindings:
  take_rate:
    start: 0.192
    end: 0.208
    dist: normal              # drawn only by `mc`; deterministic runs use mean
    mean: 0.208
    sd: 0.012
    lo: 0.18                  # clamp applied to draws
    hi: 0.24
    applies_to: end           # which glide endpoint a draw replaces
    rationale: hypothetical monetization growth toward a 21% ceiling
    source: illustrative assumption
    confidence: medium        # low | medium | high
    as_of: 2026-02-15

valuation:
  fcf: fcf                    # which line to discount
  wacc: 0.105
  terminal_growth: 0.025
  net_cash: 260.0
  shares: 137.0

scenarios:                    # inline patches; §9
  bear:
    thesis: AI substitutes low-end freelance work; costs re-expand
    bindings: { ... }
    valuation: { terminal_growth: 0.015 }
```

### 6.1 Value forms

| Form | Syntax | Resolves to |
|---|---|---|
| scalar | `0.24` | scalar |
| series | `[0.19, 0.20, ...]` | length-N series; wrong length is `length_mismatch` |
| glide | `{start: a, end: b, shape: linear\|geometric}` | interpolated series (default linear) |
| step | `{until: 2028: a, after: b}` | piecewise-constant series |
| distribution | `{dist: normal, mean, sd, lo?, hi?}` or `{dist: uniform, low, high}` | scalar draw under `mc`; `mean` (or midpoint) otherwise |
| glide + distribution | glide keys + dist keys + `applies_to: start\|end` | draw replaces one endpoint, then interpolate |

Metadata keys — `rationale`, `source`, `confidence`, `as_of`, `unit` —
are carried and surfaced (`show`, `explain`, `log`) but MUST NOT affect
evaluation. Valuation parameters accept the same value forms, including
distributions (so `mc` can draw WACC).

### 6.2 Merge semantics

Patches deep-merge over the base document with one rule: any mapping
containing a value-form or metadata key is a **leaf** and is replaced
wholesale, never merged into. This prevents base-case distribution or
glide metadata from surviving into an override that did not restate it.

## 7. Facts

### 7.1 actuals.csv

Tidy long format, append-only by convention:

```csv
period,line,value
2025,revenue,787.8
2025,gsv,4028.4
```

`line` names SHOULD match template lines where the concept corresponds;
extra reported lines are allowed and pass through to `export`.

### 7.2 Cross-checks

`validate` compares opinions against facts wherever they touch: any
binding named `<x>0` whose stem corresponds to a base-year fact MUST
match it within tolerance (default 0.5%, configurable per binding via
`tolerance:`), and declared segment decompositions MUST sum to their
reported total within 1%.

### 7.3 world.yaml

An optional workspace-level file of shared exogenous named series
(macro rates, category TAM). Templates reference world series like
parameters; `lint` verifies availability. World values are facts or
assumptions about the *environment*, never about an entity.

## 8. Units

Unit system: `currency_m`, `currency`, `count`, `ratio`,
`per_period_ratio`. When declared, the checker enforces:

- `ratio × currency_m → currency_m`; `currency_m ± currency_m → currency_m`;
  mixing `currency` and `currency_m` is `unit_mismatch`.
- A binding declared `ratio` with `|value| > 1.5` raises warning
  `ratio_magnitude` (the percent-vs-basis-points trap).
- `grow`'s second argument and `terminal_growth` must be
  `per_period_ratio` or `ratio`.

Undeclared units disable checking for the terms involved; `lint --strict`
makes missing units a warning.

## 9. Scenarios and patches

A **scenario** is a named, thesis-bearing patch stored in `params.yaml`
under `scenarios:` or as a file in `scenarios/`. A **patch envelope** is
the only write path into a workspace:

```yaml
op: add_scenario         # add_scenario | set_binding | set_valuation
                         # | add_check | fork_template
name: ai_substitution
thesis: >
  AI tools absorb low-complexity tasks; client count erodes 3%/yr while
  enterprise is insulated.
bindings:
  client_growth: {start: -0.03, end: -0.01}
```

`burr patch <company> -f envelope.yaml` applies atomically:
parse → merge → lint → validate → check → write. Any failure leaves the
workspace untouched and emits diagnostics. `op: fork_template` copies a
template under a new id and applies line/parameter edits — the sanctioned
way to challenge a model's *logic* rather than its numbers.

## 10. Command reference

Commands are grouped by the question they answer. All support the
global options of §2.

### 10.1 Integrity

**`burr lint <company>`** — structural checks: every template
parameter bound; no orphan bindings; no unused parameters; identifiers
valid; units consistent (§8). Output: diagnostics or `lint OK`.

**`burr validate <company>`** — opinions vs facts (§7.2). Lists each
cross-check with OK/FAIL.

**`burr check <company>`** — evaluate and assert every template
`checks:` invariant, per period. First failure names the check, the
period, and both sides' values.

**`burr test <company>`** — lint + validate + check across the base
case and every scenario. The CI command; exit 0 means the whole
workspace is coherent.

### 10.2 Evaluation

**`burr run <company>`** — evaluate all lines. Human output: line ×
period table. `--json`: tidy rows
`{entity, scenario, period, line, value, provenance}`.

**`burr value <company>`** — DCF on the configured FCF line:
enterprise value, equity value, per-share value, terminal weight.
Terminal value uses Gordon growth; `--exit-multiple M` substitutes an
exit-EBITDA multiple as a cross-check.

**`burr compare <company>`** — base and every scenario, side by side.

### 10.3 Interrogation

**`burr trace <company> <line>`** — the dependency tree from a line
down to bindings, with evaluated values at every node and each
binding's rationale. Answers "why is this number what it is."

**`burr dag <company> [--format mermaid|dot|json]`** — the dependency
graph, mechanically derived; suitable for rendering. `--formulas`
annotates nodes with their expressions.

**`burr explain <company> --frm A --to B`** — attribute the per-share
gap between two scenarios to individual assumption differences via
one-at-a-time substitution, sorted by |impact|, with the interaction
residual reported explicitly, never dropped. Answers "why do these
scenarios disagree."

**`burr show <company> <binding>`** — a binding's value form,
metadata, every experiment touching it (§13), and every scenario that
overrides it. Answers "what do we believe about this, and why."

### 10.4 Exploration

**`burr sens <company> --x k=lo:hi:step --y k=lo:hi:step`** — 2-D
per-share grid over any two bindings or valuation parameters.

**`burr mc <company> [--draws N]`** — Monte Carlo over every declared
distribution (bindings and valuation). Output: percentiles p5/p25/p50/
p75/p95 and a histogram; `--json` adds all draws. Deterministic under
`--seed`.

**`burr try <company> <patch.yaml>`** — apply a patch **in memory**:
report base vs trial per-share, the gap, and per-key attribution.
Writes nothing. The sandbox for cheap hypothesis testing.

### 10.5 Learning

**`burr record <company> <patch.yaml> --question Q --finding F
[--tags a,b]`** — persist an experiment: question, patch, machine-
computed results, prose finding, tags, timestamp, and the workspace
fingerprint (§13). Findings whose numeric claims contradict their own
attached results SHOULD be flagged by implementations.

**`burr log <company> [--param NAME] [--tag T] [--stale]`** — query
the journal. Entries recorded against a workspace state other than the
current one are marked `[STALE]`. `--param` answers "what have we
learned about this assumption."

**`burr replay <company> <exp-id>`** — re-run a recorded experiment
against the current workspace; report `HOLDS` or `DRIFTED` with both
result sets.

### 10.6 Ingestion and emission

**`burr calibrate <company>`** — derive historical ratios and growth
rates from `actuals.csv` and emit a *proposed* patch of base-case
bindings, each with `source: derived from actuals`. Never auto-applied.

**`burr export <company> -o out.csv`** — the tidy fact table: all
scenarios' forecasts plus actuals, one observation per row, with a
provenance column. The interchange format for databases and analysis.

**`burr emit <company> -o out.xlsx`** — compile the model to a live
spreadsheet: an Assumptions sheet of editable input cells (glide paths
expanded per period), a Model sheet where every cell is a real formula
compiled from the template AST (`grow` unrolled to per-period
recurrences), a DCF sheet, and a read-only Actuals sheet. Finance
color conventions: blue inputs, black formulas, green cross-sheet
links. Emission MUST verify the recalculated workbook against the
engine and fail on disagreement beyond floating-point tolerance.
Compilation is one-way; `burr ingest` (reserved) will diff a returned
workbook's input cells and *propose* a patch.

## 11. Determinism and fingerprints

- Evaluation is pure: identical workspace + command + seed ⇒ identical
  output.
- The **workspace fingerprint** is a content hash of the resolved
  params document plus actuals. Experiments store it; `log` compares
  it; `replay` revalidates across it.
- Randomness exists only in `mc` and only via `--seed`.

## 12. JSON contracts

Schemas are versioned in `burr.lock`; fields are only ever added.

### 12.1 Diagnostics (any command, exit 1)

```json
{"ok": false,
 "diagnostics": [{
   "severity": "error",
   "code": "unbound_parameter",
   "where": {"file": "companies/marketplace_demo/params.yaml", "key": "tax_rate"},
   "message": "missing binding for template parameter 'tax_rate'",
   "fix_hint": "add bindings.tax_rate"}]}
```

Diagnostic codes: `unbound_parameter`, `orphan_binding`,
`unused_parameter`, `unknown_name`, `circular_dependency`,
`length_mismatch`, `unit_mismatch`, `ratio_magnitude` (warning),
`fact_mismatch`, `check_failed`, `eval_error`, `unknown_scenario`,
`patch_conflict`, `version_mismatch`.

### 12.2 Results

- `run`: `{"ok": true, "rows": [{entity, scenario, period, line, value,
  provenance}]}`
- `value`: `{"ok": true, "ev", "equity", "per_share", "terminal_weight"}`
- `explain`: `{"ok": true, "from", "to", "gap",
  "attribution": [{"key", "delta"}], "interactions"}`
- `try`: `{"ok": true, "base_per_share", "trial_per_share", "gap",
  "attribution": [...]}`
- `mc`: `{"ok": true, "percentiles": {"p5", "p25", "p50", "p75", "p95"},
  "draws": [...]}` (draws only with `--full`)

## 13. Experiment journal

`experiments/exp-NNN.yaml`, append-only, one file per experiment:

```yaml
id: exp-002
at: 2026-09-13T14:02:11
question: Impact of a regulatory take-rate cap at 18.5% from 2029?
scenario: base
patch: {bindings: {take_rate: [0.192, 0.195, 0.198, 0.185, 0.185, 0.185]},
        valuation: {terminal_growth: 0.02}}
results: {base_per_share: 19.36, trial_per_share: 17.30, gap: -2.06,
          attribution: [{key: take_rate, delta: -1.15},
                        {key: terminal_growth, delta: -0.97}]}
finding: Costs ~2/sh, split between the cap itself and its terminal effect.
tags: [regulation, downside]
fingerprint: 3f9c1a2b8de4
```

Implementations MUST NOT rewrite existing entries. Callers own any
additional tag semantics (actors, turns, visibility); the engine
neither interprets nor enforces them.

## 14. Agent protocol

The intended loop for an LLM operating `burr` on a principal's
behalf:

1. Orient: read `params.yaml` (with rationales), `compare --json`,
   `log`.
2. Translate the principal's stated belief into a patch envelope with a
   written thesis.
3. Probe with `try`; on exit 1, repair from diagnostics and retry.
4. Commit deliberately: `patch` for durable scenarios, `record` for
   findings worth keeping; prefer recording over patching.
5. Interrogate with `value`, `explain`, `mc`, `sens`, `trace`; narrate
   to the principal citing rationales and attribution, then propose the
   next probe.

Agent obligations: never edit `actuals.csv` or `world.yaml` facts
directly (ingestion tooling only); never delete `rationale` fields;
prefer adding scenarios to mutating the base case; cite a `source` for
any base-case change; treat `[STALE]` findings as unverified until
replayed.

## 15. Emission targets summary

| Target | Command | Audience | Direction |
|---|---|---|---|
| tidy CSV | `export` | databases, dataframes, agents | one-way |
| live xlsx | `emit` | spreadsheet-native humans | one-way (ingest reserved) |
| mermaid/dot | `dag` | documentation, review | one-way |

## 16. Non-goals

Portfolio construction, market-implied calibration, tick or intraday
data, GAAP statement rendering, spreadsheet round-trip editing, access
control and multi-party visibility rules, and any awareness of the
social context in which the tool is used. `burr` models one firm at a
time as an argument between explicit beliefs; everything else belongs
to its callers.

---

## Appendix A. Minimal complete workspace

```yaml
# templates/lemonade.yaml
template: lemonade
parameters: [{name: cups0, unit: count}, {name: cup_growth, unit: ratio},
             {name: price, unit: currency}, {name: cost_pct, unit: ratio}]
lines:
  cups:    grow(cups0, cup_growth)
  revenue: cups * price
  profit:  revenue * (1 - cost_pct)
checks: [profit <= revenue]
```

```yaml
# companies/stand/params.yaml
entity: stand
template: lemonade
periods: 2027..2029
base_year: 2026
bindings:
  cups0: {value: 1000, source: last summer's tally}
  cup_growth: {start: 0.10, end: 0.05, rationale: word of mouth fades}
  price: 2.50
  cost_pct: {dist: normal, mean: 0.40, sd: 0.05, lo: 0.2, hi: 0.7}
valuation: {fcf: profit, wacc: 0.20, terminal_growth: 0.0, shares: 2}
```

```csv
# companies/stand/actuals.csv
period,line,value
2026,revenue,2500
```

`burr test companies/stand && burr value companies/stand` completes
the tour.
