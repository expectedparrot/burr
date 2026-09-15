# Burr agent guide

Run `burr guide` to read this installed guide. Use `burr next COMPANY --json`
after material changes. `next` inspects current evidence and returns one action
or explicit missing inputs. Execute `action.argv` as an argument array; it uses
the current Python interpreter, an absolute workspace, and the selected scenario.
The `shell` form is quoted for Bash/Zsh. Never concatenate unquoted input into it.

## Golden path

1. **Orient and validate.** Run `next`. It checks all scenarios and returns the
   selected scenario's assumptions, valuation comparison, and relevant journal
   evidence. Read rationales and the principal's question. `repair` or
   `repair_patch` means inspect diagnostics and correct their cause before
   continuing. Do not weaken a check just to get a pass.
2. **Translate a belief.** Write a YAML patch with a thesis or rationale, keeping
   numeric business assumptions in parameters. Prefer a new scenario to changing
   base. Use `--patch PATH --question TEXT` on `next` to select this task.
3. **Probe.** `next --patch PATH` evaluates the patch in memory and returns
   `evidence.trial` including attribution and interactions. `burr try` remains
   available for a standalone probe. Both commands write nothing.
4. **Interpret and record.** Supply `--finding TEXT` after inspecting the results.
   Follow the returned `record` action. The question and interpretation come from
   the caller; `next` does not invent them. Recording preserves evidence without
   applying the patch. If a durable change is requested, use `patch` deliberately
   and call `next` again after the resulting fingerprint change.
5. **Review evidence.** `next` replays the selected record in memory. A stale
   record remains stale even when its numeric result still holds. Review the new
   calculation and append a fresh record; never overwrite the original. If a
   source patch file is unavailable, write `evidence.suggested_patch` to a new
   YAML file and pass its path. A revised patch or question starts a different
   selection and does not require clearing unrelated journal history.
6. **Export.** Choose `--deliverable dashboard` (default), `csv`, or `excel`, and
   optionally `--output PATH`. Execute the returned export action, then rerun
   `resume_argv`. The export action uses `--receipt` to write `OUTPUT.burr.json`
   alongside the artifact. Receipts bind its SHA-256 digest, workspace, scenario, command, and
   all scenario fingerprints. Old exports without receipts must be regenerated.
7. **Conclude.** `complete: true` means the model validates, the selected finding
   is current and replays, and this one deliverable is current. Present the
   finding, assumptions, sources, and artifact. This is a technical completion
   condition; judge separately whether the principal's question is answered.

`next` has no hidden progress file. It cannot know whether you have read an
assumption or whether the user agrees with a finding. It performs inspect/probe/
replay checks itself so repeatedly running a read-only action does not trap the
workflow. `required_inputs` may be supplied from authorized task context; ask the
principal only when their intent or missing evidence requires it.

Without `--patch` or `--question`, the most recent journal entry for the selected
scenario is used. With either option, only matching entries are used. Patch
matching compares parsed content, including metadata. Keep passing the same
selection options, or run the returned `resume_argv`. A new finding on an already
current record selects a new append-only record when it differs; supply the patch
path and question as well. Exports describe saved scenarios; an unapplied trial remains
in the journal rather than becoming the exported forecast.

## Example (from a source checkout)

```bash
burr guide
burr --json -C examples/starbucks next starbucks \
  --patch patches/slower_traffic.yaml \
  --question 'What if customer visits do not recover?'
```

The bundled example already has a matching journal entry, so this may proceed
directly to export. For a new question, inspect `evidence.trial`, supply a finding,
execute `action.argv`, and rerun `resume_argv` until complete or input is needed.
Installed packages do not include the example workspace. Start with
`burr init my-model`, then `burr --json -C my-model next stand`.

For example, a price experiment in the starter can use `my-model/premium.yaml`:

```yaml
bindings:
  price:
    value: 3.0
    rationale: Illustrative premium for convenience; volume held fixed.
    source: tutorial assumption
```

Run `burr --json -C my-model next stand --patch premium.yaml --question 'What if
price rises to 3.00?'` as one command. Read the returned trial before supplying a
finding. A plain `bindings`/`valuation` envelope probes the saved assumptions
without naming a new scenario. Durable `add_scenario` operations require a new name.
Use `burr patch stand --help` for durable edits; the plain mapping above is for
`try` and `record`, not a durable `patch` operation.

## Modeling obligations

- Distinguish reported facts, management guidance, and assumptions. Preserve
  source dates, rationales, units, fiscal periods, and share scaling.
- Do not directly rewrite `actuals.csv` or factual `world.yaml` data during
  opinion exploration; use reviewed ingestion tooling for facts.
- Preserve rationale metadata when replacing value forms. Cite sources for
  base-case changes. Never turn an illustrative assumption into a reported fact.
- Treat stale findings as unverified until replayed and reviewed. Journal entries
  are append-only. Browser dashboard logs are separate from the workspace journal.
- Use `trace`, `show`, and `explain` to connect results to drivers. Use `sens` for
  ranges and `mc` only when declared distributions represent intended uncertainty.
- Valuation requires an explicit cash-flow line, discount assumptions, and
  consistent shares/currency units. Operating-only models can still use `run`
  and `plot`; the valuation golden path stops for missing valuation inputs.
- No provider calls, spending, messaging, or publication is required by this
  local workflow. Respect the principal's authorized scope for durable edits.

## Machine contract

`--json` controls output, not input. Patch inputs accept YAML (including JSON).
Successful guidance returns `ok`, `protocol_version`, `state`, `complete`,
`action`, `next_steps`, `required_inputs`, `evidence`, `diagnostics`, `warnings`,
and `resume_argv`. `action` is null when input is needed or the path is complete.
The states are `repair`, `repair_patch`, `review_stale`, `needs_input`, `record`,
`export`, and `complete`. Guidance may return `ok: true` with `state: repair`:
the inspection succeeded but the model needs work. Do not equate `ok` with
completion. Unreadable workspaces or malformed command inputs use normal errors.

Exit codes: 0 for successful commands, 1 for model/patch diagnostics, 2 for usage
or malformed-file errors. Diagnostics include `code`, `where`, and `fix_hint`.
Run `burr COMMAND --help --json` to inspect options. `ingest` is reserved;
spreadsheet edits do not flow back into the workspace.
