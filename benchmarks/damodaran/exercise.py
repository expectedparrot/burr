"""Exercise a saved workspace and recalculate all of its Excel exports externally.

Run with: python -m benchmarks.damodaran.exercise --workspace examples/damodaran
"""

import argparse
import tempfile
from pathlib import Path

from openpyxl import load_workbook

from burr.model import Workspace
from burr.workbook import emit
from .catalog import MODELS, ROOT, variants
from .evaluate import compare, evaluate
from .oracle import convert, libreoffice, load_json, save_json


def check_recalculated(original, recalculated):
    """Compare every exported formula cell, including hidden growth helpers."""
    formulas = load_workbook(original)
    cached = load_workbook(original, data_only=True)
    actual = load_workbook(recalculated, data_only=True)
    if actual.sheetnames != formulas.sheetnames:
        raise ValueError("Recalculated workbook has different sheets")
    expected_cells, actual_cells = {}, {}
    for sheet in formulas:
        for row in sheet:
            for cell in row:
                if cell.data_type == "f":
                    key = f"{sheet.title}!{cell.coordinate}"
                    expected_cells[key] = [cached[sheet.title][cell.coordinate].value]
                    actual_cells[key] = [actual[sheet.title][cell.coordinate].value]
    if not expected_cells:
        raise ValueError("Export contains no formulas")
    checks = compare(actual_cells, expected_cells, str(original))
    return {"ok": all(c["ok"] for c in checks), "formula_cells": len(checks),
            "max_absolute_error": max(c["absolute_error"] for c in checks),
            "failures": [c for c in checks if not c["ok"]],
            "enterprise_value": actual["DCF"]["B9"].value,
            "per_share": actual["DCF"]["B13"].value}


def exercise(workspace, executable=None):
    workspace = Path(workspace).resolve()
    reference = load_json(ROOT / "reference.json")
    source_check = evaluate(workspace, load_json(ROOT / "inputs.json"), reference,
                            load_json(ROOT / "sources.json"))
    executable = libreoffice(executable)
    with tempfile.TemporaryDirectory(prefix="damodaran-exports-") as temporary:
        root = Path(temporary)
        exported = root / "exported"
        exported.mkdir()
        paths = []
        for name in MODELS:
            ws = Workspace(workspace / "companies" / name)
            for scenario in variants(name):
                path = exported / f"{name}--{scenario}.xlsx"
                emit(ws.model(scenario), path)
                paths.append(path)
        recalculated = convert(executable, paths, root / "recalculated")
        cases = {p.stem: check_recalculated(p, actual) for p, actual in zip(paths, recalculated)}
    return {"ok": source_check["ok"] and all(c["ok"] for c in cases.values()),
            "source_checks": {k: source_check[k] for k in (
                "case_count", "check_count", "failed_checks", "max_absolute_error", "tolerances")},
            "export_count": len(cases),
            "export_formula_checks": sum(c["formula_cells"] for c in cases.values()),
            "export_max_absolute_error": max(c["max_absolute_error"] for c in cases.values()),
            "fingerprints": {name: {s: Workspace(workspace / "companies" / name).fingerprint(s)
                                    for s in variants(name)} for name in MODELS},
            "exports": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--soffice")
    args = parser.parse_args()
    report = exercise(args.workspace, args.soffice)
    save_json(args.output, report)
    print({k: v for k, v in report.items() if k not in ("exports", "fingerprints")})
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
