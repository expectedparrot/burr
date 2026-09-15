import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from burr.cli import main
from burr.storage import yaml_text
from conftest import edit_yaml


def invoke(capsys, *args):
    status = main(list(args))
    captured = capsys.readouterr()
    assert not captured.err
    return status, json.loads(captured.out)


@pytest.mark.parametrize("command", [
    ["lint", "--strict"], ["validate"], ["check"], ["test"], ["run"], ["value"], ["compare"],
    ["trace", "profit"], ["dag", "--format", "dot", "--formulas"],
    ["explain", "--frm", "base", "--to", "bear"], ["show", "price"],
    ["sens", "--x", "price=2:3:.5", "--y", "wacc=.1:.2:.05"],
    ["mc", "--draws", "5", "--full"], ["calibrate"], ["log"],
])
def test_json_command_surface(workspace, capsys, command):
    status, result = invoke(capsys, command[0], "stand", *command[1:], "-C", str(workspace.root), "--json")
    assert status == 0 and result["ok"]


@pytest.mark.parametrize("command", ["run", "value", "compare", "dag", "mc", "test"])
def test_byte_deterministic_cli(workspace, capsys, command):
    argv = ["--json", "-C", str(workspace.root), command, "stand"]
    if command == "mc":
        argv += ["--draws", "20", "--full"]
    assert main(argv) == 0
    first = capsys.readouterr().out
    assert main(argv) == 0
    assert capsys.readouterr().out == first


def test_exports_and_source_protection(workspace, capsys, tmp_path):
    output = tmp_path / "out.csv"
    status, result = invoke(capsys, "export", str(workspace.company), "-o", str(output), "--json")
    rows = list(csv.DictReader(output.open()))
    assert status == 0 and result["rows"] == len(rows)
    assert {r["scenario"] for r in rows} == {"base", "bear", "actuals"}
    assert any(r["line"] == "cups" and r["scenario"] == "actuals" for r in rows)
    before = workspace.params_file.read_bytes()
    status, result = invoke(capsys, "export", str(workspace.company), "-o", str(workspace.params_file), "--json")
    assert status == 1 and workspace.params_file.read_bytes() == before
    assert invoke(capsys, "emit", str(workspace.company), "-o", str(tmp_path / "out.xlsx"), "--json")[0] == 0


def test_cli_patch_record_replay(workspace, capsys, tmp_path):
    patch = tmp_path / "patch.yaml"
    patch.write_text(yaml_text({"op": "set_binding", "name": "price", "value": 3}))
    common = ["--json", "-C", str(workspace.root)]
    assert invoke(capsys, *common, "try", "stand", str(patch))[0] == 0
    assert invoke(capsys, *common, "record", "stand", str(patch), "--question", "Price?", "--finding", "It rises")[0] == 0
    assert invoke(capsys, *common, "replay", "stand", "exp-001")[1]["status"] == "HOLDS"
    assert invoke(capsys, *common, "patch", "stand", "-f", str(patch))[0] == 0


def test_usage_and_model_exit_codes(workspace, capsys, tmp_path):
    assert invoke(capsys, "run", "missing-company", "--json")[0] == 2
    assert invoke(capsys, "run", "--json")[0] == 2
    assert invoke(capsys, "run", "stand", "--nonsense", "--json")[0] == 2
    assert invoke(capsys, "mc", str(workspace.company), "--draws", "0", "--json")[0] == 2
    status, result = invoke(capsys, "run", str(workspace.company), "-s", "missing", "--json")
    assert status == 1 and result["diagnostics"][0]["code"] == "unknown_scenario"
    patch = tmp_path / "broken.yaml"
    patch.write_text("bindings: [\n")
    assert invoke(capsys, "try", str(workspace.company), str(patch), "--json")[0] == 2
    patch.write_text("op: set_binding\nname: price\nvalue: 1\nvalue: 2\n")
    assert invoke(capsys, "patch", str(workspace.company), "-f", str(patch), "--json")[0] == 2
    edit_yaml(workspace.root / "burr.lock", lambda d: d.update({"engine_version": "99.0.0"}))
    status, result = invoke(capsys, "lint", str(workspace.company), "--json")
    assert status == 1 and result["diagnostics"][0]["code"] == "version_mismatch"


@pytest.mark.parametrize("value", [None, [], True, "oops", {"start": []}, {"dist": []}, float("inf")])
def test_bad_shapes_are_diagnostics_not_tracebacks(workspace, capsys, value):
    edit_yaml(workspace.params_file, lambda d: d["bindings"].update({"price": value}))
    status, result = invoke(capsys, "run", str(workspace.company), "--json")
    assert status == 1 and not result["ok"] and result["diagnostics"]


def test_global_version_and_directory(workspace, capsys):
    status, result = invoke(capsys, "--version", "--json")
    assert status == 0 and result["engine_version"] == "1.0.0"
    original = Path.cwd()
    assert invoke(capsys, "--json", "-C", str(workspace.root), "value", "stand", "-s", "bear")[0] == 0
    assert Path.cwd() == original


def test_json_help(capsys):
    status, result = invoke(capsys, "--json", "--help")
    assert status == 0 and "Driver-based" in result["help"]
    status, result = invoke(capsys, "emit", "--help", "--json")
    assert status == 0 and "--output" in result["help"]


def test_cli_init(capsys, tmp_path):
    status, result = invoke(capsys, "init", str(tmp_path / "new"), "--template", "custom", "--json")
    assert status == 0 and result["template"] == "custom"
    status, _ = invoke(capsys, "test", str(tmp_path / "new/companies/stand"), "--json")
    assert status == 0


@pytest.mark.parametrize("command", [["run"], ["value"], ["compare"], ["dag", "--formulas"], ["dag", "--format", "dot"],
    ["explain", "--frm", "base", "--to", "bear"], ["show", "price"], ["mc", "--draws", "5"], ["check"], ["validate"], ["test"]])
def test_human_renderers(workspace, capsys, command):
    assert main([command[0], str(workspace.company), *command[1:]]) == 0
    output = capsys.readouterr().out
    assert output.strip() and "Traceback" not in output
