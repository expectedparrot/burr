"""The public burr command and its stable JSON boundary."""

import argparse
import contextlib
import csv
import io
import os
import sys
from pathlib import Path

from . import ENGINE_VERSION, SCHEMA_VERSION
from .errors import BurrError, require
from .model import Workspace, find_workspace
from . import operations as ops
from .storage import atomic_write, json_text, read_yaml, workspace_lock, yaml_text


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BurrError("usage_error", message, hint="run burr --help", exit_code=2)


def globals_parser():
    parser = Parser(add_help=False, allow_abbrev=False)
    parser.add_argument("--json", action="store_true", help="emit one JSON document")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    parser.add_argument("-s", "--scenario", default="base", help="named scenario (default: base)")
    parser.add_argument("-C", dest="directory", default=None, metavar="DIR", help="run from DIR")
    parser.add_argument("--version", action="store_true", help="show engine and schema versions")
    return parser


def parser():
    root = Parser(prog="burr", description="Driver-based firm modeling, valuation, and structured scenario exploration.",
                  parents=[globals_parser()], allow_abbrev=False)
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="scaffold a complete workspace")
    init.add_argument("directory")
    init.add_argument("--template", default="lemonade")
    sub.add_parser("guide", help="read the installed agent golden-path guide")
    descriptions = {
        "lint": "check structure and units", "validate": "compare opinions against facts", "check": "assert model invariants",
        "test": "test base and every scenario", "run": "evaluate forecast lines", "value": "compute DCF valuation",
        "compare": "compare all scenario valuations", "trace": "trace a line to its assumptions", "dag": "export dependency graph",
        "explain": "attribute a scenario valuation gap", "show": "show an assumption and its evidence",
        "sens": "two-dimensional sensitivity grid", "mc": "seeded Monte Carlo simulation", "try": "test a patch in memory",
        "patch": "atomically apply a validated patch", "record": "record an experiment", "log": "query the experiment journal",
        "replay": "re-run an experiment", "calibrate": "propose bindings from actuals", "export": "export tidy CSV",
        "emit": "compile a verified, live spreadsheet", "ingest": "reserved for future workbook input diffs",
        "plot": "plot reported history, forecasts, scenarios, or model drivers",
        "dashboard": "create an offline dashboard with assumption sliders and an experiment log",
        "next": "inspect workflow evidence and recommend the next agent action",
    }
    commands = {}
    for name, description in descriptions.items():
        command = sub.add_parser(name, help=description, description=description, allow_abbrev=False)
        command.add_argument("company")
        commands[name] = command
    commands["lint"].add_argument("--strict", action="store_true")
    commands["value"].add_argument("--exit-multiple", type=float)
    commands["trace"].add_argument("line")
    commands["dag"].add_argument("--format", choices=("mermaid", "dot", "json"), default="mermaid")
    commands["dag"].add_argument("--formulas", action="store_true")
    commands["explain"].add_argument("--frm", required=True)
    commands["explain"].add_argument("--to", required=True)
    commands["show"].add_argument("binding")
    for name in ("x", "y"):
        commands["sens"].add_argument(f"--{name}", required=True)
    commands["mc"].add_argument("--draws", type=int, default=1000)
    commands["mc"].add_argument("--full", action="store_true", help="include every draw in JSON")
    commands["patch"].add_argument("-f", "--file", required=True)
    for command in ("try", "record"):
        commands[command].add_argument("file")
    commands["record"].add_argument("--question", required=True)
    commands["record"].add_argument("--finding", required=True)
    commands["record"].add_argument("--tags", default="")
    commands["log"].add_argument("--param")
    commands["log"].add_argument("--tag")
    commands["log"].add_argument("--stale", action="store_true")
    commands["replay"].add_argument("experiment")
    for command in ("export", "emit"):
        commands[command].add_argument("-o", "--output", required=True)
    plot = commands["plot"]
    plot.add_argument("--kind", choices=("series", "scenarios", "drivers"), default="series")
    plot.add_argument("--lines", required=True, help="comma-separated metrics; each gets its own panel")
    plot.add_argument("--all-scenarios", action="store_true", help="include every scenario in a series plot")
    plot.add_argument("--actuals-only", action="store_true", help="plot reported history only, including extra actuals lines")
    plot.add_argument("--period", type=int, help="forecast year for scenario bars or driver values (default: final year)")
    plot.add_argument("--title", help="custom chart title")
    plot.add_argument("--note", default="", help="context or comparability note displayed with the plots")
    plot.add_argument("-o", "--output", required=True, help="standalone .html or .svg output")
    dashboard = commands["dashboard"]
    dashboard.add_argument("-o", "--output", required=True, help="standalone .html output")
    dashboard.add_argument("--slider", action="append", default=[], metavar="NAME=MIN:MAX:STEP",
                           help="enable a slider; annual profiles shift all years; NAME~level/~target selects a mode, NAME@YEAR edits one year")
    dashboard.add_argument("--title")
    for name in ("export", "emit", "dashboard"):
        commands[name].add_argument("--receipt", action="store_true", help="write a freshness receipt for burr next")
    route = commands["next"]
    route.add_argument("--patch", help="proposed patch path; evaluated in memory")
    route.add_argument("--question", help="select an exact journal question or supply a new one")
    route.add_argument("--finding", help="reviewed interpretation for a proposed new record")
    route.add_argument("--deliverable", choices=("dashboard", "csv", "excel"), default="dashboard")
    route.add_argument("--output", help="deliverable path; defaults to artifacts/COMPANY-SCENARIO.EXT")
    return root


def output_path(workspace, name):
    path = Path(name)
    resolved = path.resolve()
    protected = [workspace.root / "templates", workspace.root / "companies"]
    require(resolved not in {(workspace.root / "burr.lock").resolve(), (workspace.root / "world.yaml").resolve()}
            and not any(resolved.is_relative_to(p.resolve()) for p in protected),
            "patch_conflict", "exports cannot overwrite workspace source files; use an artifacts directory")
    return path


def dispatch(args, workspace):
    command, scenario = args.command, args.scenario
    if command == "next":
        from .guidance import next_step
        return next_step(workspace, scenario=scenario, patch=args.patch, question=args.question,
                         finding=args.finding, deliverable=args.deliverable, output=args.output)
    if command == "ingest":
        raise BurrError("usage_error", "ingest is reserved; spreadsheet compilation is one-way", exit_code=2)
    if command == "test":
        return ops.coherent(workspace)
    if command == "compare":
        return {"ok": True, "scenarios": [{"scenario": name, **workspace.model(name).value()} for name in ["base", *workspace.scenarios()]]}
    if command == "explain":
        return ops.explain(workspace, args.frm, args.to)
    if command == "sens":
        return ops.sensitivity(workspace, scenario, args.x, args.y)
    if command == "mc":
        return ops.monte_carlo(workspace, scenario, args.draws, args.seed, args.full)
    if command in {"patch", "try", "record"}:
        envelope = read_yaml(args.file)
        if command == "patch":
            return ops.apply_patch(workspace, envelope, scenario)
        if command == "try":
            return ops.try_patch(workspace, envelope, scenario)
        return ops.record(workspace, envelope, scenario, args.question, args.finding, args.tags)
    if command == "log":
        return ops.journal(workspace, param=args.param, tag=args.tag, stale=args.stale)
    if command == "replay":
        return ops.replay(workspace, args.experiment)
    if command == "show":
        return ops.show(workspace, scenario, args.binding)
    if command == "calibrate":
        return ops.calibrate(workspace, scenario)
    if command == "plot":
        from .plots import emit_plot
        return emit_plot(workspace, output_path(workspace, args.output), kind=args.kind,
                         lines=args.lines, scenario=scenario, all_scenarios=args.all_scenarios,
                         actuals_only=args.actuals_only, period=args.period, title=args.title, note=args.note)
    if command == "dashboard":
        from .dashboard import emit_dashboard
        return emit_dashboard(workspace, output_path(workspace, args.output), scenario=scenario,
                              sliders=args.slider, title=args.title)
    if command == "export":
        path = output_path(workspace, args.output)
        rows = [{"entity": workspace.params["entity"], "scenario": "actuals", **row,
                 "provenance": workspace.relative(workspace.company / "actuals.csv")} for row in workspace.actuals]
        for name in ["base", *workspace.scenarios()]:
            rows.extend(workspace.model(name).rows())
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=["entity", "scenario", "period", "line", "value", "provenance"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["scenario"], r["period"], r["line"])))
        atomic_write(path, stream.getvalue())
        return {"ok": True, "output": str(path), "rows": len(rows)}
    model = workspace.model(scenario, strict=getattr(args, "strict", False))
    if command == "lint":
        return {"ok": True, "diagnostics": [d.to_dict() for d in model.warnings]}
    if command == "validate":
        return {"ok": True, "cross_checks": model.validate()}
    if command == "check":
        return {"ok": True, "checks": model.check()}
    if command == "run":
        return {"ok": True, "rows": model.rows()}
    if command == "value":
        return model.value(args.exit_multiple)
    if command == "trace":
        return ops.trace(model, args.line)
    if command == "dag":
        return ops.graph(model, args.formulas)
    if command == "emit":
        from .workbook import emit
        return emit(model, output_path(workspace, args.output))
    raise BurrError("usage_error", f"unknown command {command}", exit_code=2)


def table(headers, rows):
    values = [[f"{v:,.6g}" if isinstance(v, float) else str(v) for v in row] for row in rows]
    widths = [max(len(str(h)), *(len(row[i]) for row in values)) if values else len(str(h)) for i, h in enumerate(headers)]
    return "\n".join("  ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)).rstrip() for row in [headers, *values])


def human(result, args):
    if not result["ok"]:
        return "\n".join(f"{d['severity'].upper()} {d['code']} {d['where'].get('file', '')}:{d['where'].get('key', '')}: {d['message']}\n  Fix: {d['fix_hint']}" for d in result["diagnostics"])
    command = args.command
    if command == "guide":
        return result["guide"].rstrip()
    if command == "next":
        lines = [f"{result['state']}: {result['message']}"]
        if result["action"]:
            lines.append(result["action"]["shell"])
        lines.extend(f"Input {r['name']}: {r['reason']}" for r in result["required_inputs"])
        lines.extend(f"{d['code']}: {d['message']} — {d['fix_hint']}" for d in result["diagnostics"])
        return "\n".join(lines)
    if command == "init":
        import shlex
        return f"Created {result['workspace']}\nAgent guide: burr guide\nNext: burr --json -C {shlex.quote(result['workspace'])} next stand"
    if command == "lint":
        warnings = "\n".join(f"WARNING {d['code']}: {d['message']} ({d['where']['key']})" for d in result["diagnostics"])
        return "lint OK" + ("\n" + warnings if warnings else "")
    if command == "run":
        years = sorted({r["period"] for r in result["rows"]})
        lines = sorted({r["line"] for r in result["rows"]})
        lookup = {(r["line"], r["period"]): r["value"] for r in result["rows"]}
        return table(["Line", *map(str, years)], [[line, *[lookup[line, year] for year in years]] for line in lines])
    if command == "value":
        return table(["Measure", "Value"], [[key, result[key]] for key in ("ev", "equity", "per_share", "terminal_weight")])
    if command == "compare":
        return table(["Scenario", "EV", "Equity", "Per share", "Terminal weight"],
                     [[r["scenario"], *[r[k] for k in ("ev", "equity", "per_share", "terminal_weight")]] for r in result["scenarios"]])
    if command == "dag":
        if args.format == "json":
            return json_text(result).rstrip()
        import json
        if args.format == "dot":
            nodes = [f'  "{n["id"]}" [label={json.dumps(n["id"] + (": " + n["formula"] if "formula" in n else ""))}];' for n in result["nodes"]]
            edges = [f'  "{e["from"]}" -> "{e["to"]}"' + (' [style=dashed,label="lag"]' if e["lagged"] else '') + ';' for e in result["edges"]]
            return "digraph burr {\n" + "\n".join(nodes + edges) + "\n}"
        nodes = [f'  n_{n["id"]}["{(n["id"] + (": " + n["formula"] if "formula" in n else "")).replace(chr(34), "#quot;")}"]' for n in result["nodes"]]
        edges = [f'  n_{e["from"]} {"-. lag .->" if e["lagged"] else "-->"} n_{e["to"]}' for e in result["edges"]]
        return "flowchart LR\n" + "\n".join(nodes + edges)
    if command in {"try", "explain"}:
        lead = f"Gap: {result['gap']:,.6g}"
        if command == "try":
            lead = f"Base: {result['base_per_share']:,.6g}  Trial: {result['trial_per_share']:,.6g}  " + lead
        metadata = "\n".join(f"{r['key']}: " + "; ".join(f"{k}: {v}" for k, v in r["metadata"].items())
                             for r in result["attribution"] if r.get("metadata"))
        return lead + "\n" + table(["Assumption", "Per-share impact"], [[r["key"], r["delta"]] for r in result["attribution"]]) + f"\nInteractions: {result['interactions']:,.6g}" + ("\n" + metadata if metadata else "")
    if command == "sens":
        return table([result["y"]["key"] + " / " + result["x"]["key"], *[f"{x:g}" for x in result["x"]["values"]]],
                     [[y, *row] for y, row in zip(result["y"]["values"], result["grid"])])
    if command == "mc":
        scale = max(r["count"] for r in result["histogram"])
        histogram = "\n".join(f"{r['lo']:12,.4f} – {r['hi']:12,.4f} {'█' * round(r['count'] / scale * 32)} {r['count']}" for r in result["histogram"])
        return table(["Percentile", "Per share"], list(result["percentiles"].items())) + "\n\n" + histogram
    if command == "log":
        return "\n\n".join(f"{e['id']}" + (" [STALE]" if e["stale"] else "") + f" — {e['question']}\n{e['finding']}\n"
                            + f"Base: {e['results']['base_per_share']:,.6g}  Trial: {e['results']['trial_per_share']:,.6g}  Gap: {e['results']['gap']:,.6g}\n"
                            + yaml_text({"patch": e["patch"], "tags": e.get("tags", [])}).rstrip()
                            for e in result["entries"]) or "No experiments."
    if command == "replay":
        return f"{result['id']}: {result['status']}\n" + table(["Result", "Recorded", "Current"], [[k, result["recorded"][k], result["current"][k]] for k in ("base_per_share", "trial_per_share", "gap")])
    if command == "record":
        return f"Recorded {result['experiment']['id']}\n{result['experiment']['finding']}"
    if command == "calibrate":
        return yaml_text(result["patch"]).rstrip()
    if command == "validate":
        return table(["Key", "Period", "Status"], [[r["key"], r["period"], "OK"] for r in result["cross_checks"]]) if result["cross_checks"] else "validate OK (no overlapping facts)"
    if command == "check":
        return table(["Check", "Period", "Status"], [[r["check"], r["period"], "OK"] for r in result["checks"]]) if result["checks"] else "check OK (no declared checks)"
    if command == "test":
        return "\n".join(f"{r['scenario']}: lint / validate / check OK" for r in result["scenarios"])
    if command in {"export", "emit"}:
        return f"Wrote {result['output']}" + (" (recalculated and verified)" if command == "emit" else f" ({result['rows']} rows)")
    if command == "plot":
        return f"Wrote {result['output']} ({result['kind']}; {len(result['panels'])} panels)"
    if command == "dashboard":
        return f"Wrote {result['output']} ({result['controls']} editable assumptions)"
    return yaml_text(result).rstrip()


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    machine = "--json" in arguments
    original_directory = Path.cwd()
    try:
        global_args, remaining = globals_parser().parse_known_args(arguments)
        machine = global_args.json
        if global_args.version:
            result = {"ok": True, "engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION}
            print(json_text(result).rstrip() if machine else f"burr {ENGINE_VERSION} (schema {SCHEMA_VERSION})")
            return 0
        if machine and any(flag in remaining for flag in ("--help", "-h")):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                try:
                    parser().parse_args(remaining)
                except SystemExit as exc:
                    if exc.code != 0:
                        raise
            print(json_text({"ok": True, "help": stream.getvalue()}).rstrip())
            return 0
        args = parser().parse_args(remaining)
        for key, value in vars(global_args).items():
            if key != "directory":
                setattr(args, key, value)
        if global_args.directory:
            os.chdir(global_args.directory)
        if args.command == "init":
            from .starter import init
            result = init(args.directory, args.template)
            result["guide_argv"] = [sys.executable, "-m", "burr", "guide", "--json"]
            result["next_argv"] = [sys.executable, "-m", "burr", "--json", "-C",
                                   str(Path(args.directory).resolve()), "next", "stand"]
        elif args.command == "guide":
            from .guidance import guide
            result = guide()
        else:
            root, _ = find_workspace(args.company)
            with workspace_lock(root):
                workspace = Workspace(args.company)
                if getattr(args, "receipt", False):
                    # Do not create an artifact if its requested receipt cannot
                    # describe a coherent workspace.
                    ops.coherent(workspace)
                result = dispatch(args, workspace)
                if getattr(args, "receipt", False):
                    from .guidance import write_receipt
                    result["receipt"] = write_receipt(workspace, args.output, args.command, args.scenario)
        print(json_text(result).rstrip() if machine else human(result, args))
        return 0
    except BurrError as exc:
        result = {"ok": False, "diagnostics": [d.to_dict() for d in exc.diagnostics]}
        print(json_text(result).rstrip() if machine else human(result, None))
        return exc.exit_code
    except (OSError, UnicodeError) as exc:
        error = BurrError("usage_error", str(exc), exit_code=2)
        result = {"ok": False, "diagnostics": [d.to_dict() for d in error.diagnostics]}
        print(json_text(result).rstrip() if machine else human(result, None))
        return 2
    except Exception as exc:
        # Total CLI boundary, including malformed shapes and numeric overflow.
        error = BurrError("eval_error", f"{type(exc).__name__}: {exc}")
        result = {"ok": False, "diagnostics": [d.to_dict() for d in error.diagnostics]}
        print(json_text(result).rstrip() if machine else human(result, None))
        return 1
    finally:
        os.chdir(original_directory)


if __name__ == "__main__":
    raise SystemExit(main())
