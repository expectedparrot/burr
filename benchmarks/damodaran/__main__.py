"""python -m benchmarks.damodaran {fetch,capture,run,workspace}."""

import argparse
import json
import tempfile
from pathlib import Path

from .catalog import ROOT
from .evaluate import compare, evaluate
from .models import write_workspace
from .oracle import fetch, load_json, recalculate, save_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["fetch", "capture", "run", "workspace"])
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache")
    parser.add_argument("--soffice", help="LibreOffice executable for live recalculation")
    parser.add_argument("--live", action="store_true", help="Recalculate original spreadsheets and check frozen references too")
    parser.add_argument("--output", type=Path, help="Report file, new capture directory, or new workspace directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            print(fetch(args.cache))
            return 0
        if args.command == "capture":
            if args.output is None or args.output.exists():
                raise ValueError("capture requires --output pointing to a new directory; references are never silently replaced")
            inputs, reference = recalculate(args.cache, args.soffice)
            save_json(args.output / "inputs.json", inputs)
            save_json(args.output / "reference.json", reference)
            print(args.output)
            return 0
        inputs = load_json(ROOT / "inputs.json")
        if args.command == "workspace":
            if args.output is None:
                raise ValueError("workspace requires --output pointing to a new directory")
            print(write_workspace(args.output, inputs))
            return 0
        reference = load_json(ROOT / "reference.json")
        live_checks = []
        if args.live:
            live_inputs, live_reference = recalculate(args.cache, args.soffice)
            if live_inputs != inputs:
                raise ValueError("Live source inputs differ from the reviewed input snapshot")
            if set(live_reference["cases"]) != set(reference["cases"]):
                raise ValueError("Live reference case coverage differs from the frozen reference")
            for key, case in live_reference["cases"].items():
                live_checks.extend(compare(case["outputs"], reference["cases"][key]["outputs"], "live/" + key))
            reference = live_reference
        with tempfile.TemporaryDirectory(prefix="burr-damodaran-") as tmp:
            workspace = write_workspace(Path(tmp) / "workspace", inputs)
            report = evaluate(workspace, inputs, reference, load_json(ROOT / "sources.json"))
        report["mode"] = "live" if args.live else "frozen"
        if args.live:
            report["live_reference_checks"] = len(live_checks)
            report["live_reference_failures"] = sum(not c["ok"] for c in live_checks)
            report["ok"] &= not report["live_reference_failures"]
            report["live_reference_details"] = live_checks
        if args.output:
            save_json(args.output, report)
        print(json.dumps({k: v for k, v in report.items() if k not in ("cases", "live_reference_details")}, indent=2))
        return 0 if report["ok"] else 1
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"benchmark error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
