"""Dependent valuation inputs must remain live in Python, Excel and the browser."""

import copy
import json
import random
from pathlib import Path

import pytest

from benchmarks.damodaran.linked_pilot import create
from burr.cli import main
from burr.dashboard import dashboard_data
from burr.errors import BurrError
from burr.model import Workspace
from burr.operations import prepare
from burr.storage import merge
from burr.workbook import Compiler, ExcelCalculator
from conftest import edit_yaml
from test_dashboard import browser

PILOT = Path(__file__).resolve().parents[1] / "benchmarks/damodaran/agent_pilot"
CASES = json.loads((PILOT / "hidden-inputs.json").read_text())
ORACLE = json.loads((PILOT / "oracle.json").read_text())["cases"]


@pytest.fixture
def linked(tmp_path):
    return create(tmp_path / "linked")


def changed_model(workspace, inputs):
    params = copy.deepcopy(workspace.params)
    for key, value in inputs.items():
        params["bindings"][key]["value"] = value
    return workspace.model(params=params)


@pytest.mark.parametrize("case", CASES)
def test_saved_input_edits_match_independent_oracle(linked, case):
    model = changed_model(linked, CASES[case])
    result, value = model.run(), model.value()
    actual = {key: result[key][:len(values)] for key, values in ORACLE[case].items()
              if key not in {"ev", "per_share", "equity_before_options", "terminal_value", "pv_terminal"}}
    actual["ev"] = [value["ev"]]
    actual["per_share"] = [value["per_share"]]
    for key in ("equity_before_options", "terminal_value", "pv_terminal"):
        actual[key] = [result[key][4]]
    for key, expected in ORACLE[case].items():
        assert actual[key] == pytest.approx(expected, rel=1e-9, abs=1e-7)
    assert value["per_share"] == pytest.approx(result["per_share"][4])


@pytest.mark.parametrize("case", CASES)
def test_edits_to_exported_excel_stay_linked(linked, case):
    compiler = Compiler(linked.model())
    workbook = compiler.build()
    for key, value in CASES[case].items():
        for cell in workbook["Assumptions"][compiler.input_rows[key]][1:]:
            cell.value = value
    calc = ExcelCalculator(workbook)
    assert calc.cell("DCF", "B9") == pytest.approx(ORACLE[case]["ev"][0])
    assert calc.cell("DCF", "B13") == pytest.approx(ORACLE[case]["per_share"][0])
    for row in workbook["Assumptions"]:
        if str(row[0].value).startswith("valuation."):
            assert all(c.data_type == "f" and c.protection.locked for c in row[1:])


@pytest.mark.parametrize("case", CASES)
def test_browser_edits_match_source_and_patch_replays(linked, case):
    data = dashboard_data(linked)
    assert not any(c["section"] == "valuation" for c in data["controls"])
    assert "error" in browser(data, {"valuation.wacc": .1})
    changed = {f"bindings.{k}": v for k, v in CASES[case].items() if k != "high_years"}
    result = browser(data, changed)
    assert result["result"]["value"]["per_share"] == pytest.approx(ORACLE[case]["per_share"][0])
    assert "valuation" not in result["patch"]
    trial = prepare(linked, result["patch"], "base")[1] if result["patch"] else linked.model()
    assert trial.valuation_refs == linked.model().valuation_refs
    assert trial.value() == pytest.approx(result["result"]["value"])


@pytest.mark.parametrize("form,code", [
    ({"ref": "missing"}, "unknown_name"),
    ({"ref": ["wacc"]}, "unknown_name"),
    ({"ref": "wacc", "value": .1}, "eval_error"),
    ({"ref": "wacc", "start": .1, "end": .2}, "eval_error"),
    ({"ref": "wacc", "confidence": "certain"}, "eval_error"),
    ({"ref": "shares"}, "unit_mismatch"),
    ({"ref": "wacc", "unit": "currency"}, "unit_mismatch"),
])
def test_invalid_references_keep_cli_diagnostics(linked, form, code, capsys):
    edit_yaml(linked.params_file, lambda p: p["valuation"].update(wacc=form))
    assert main(["--json", "value", str(linked.company)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"][0]["code"] == code
    assert payload["diagnostics"][0]["where"]["key"] == "valuation.wacc"


def test_reference_replacement_is_atomic_and_scenario_can_override(linked):
    assert merge({"ref": "wacc", "source": "old"}, {"value": .11}) == {"value": .11}
    assert merge({"value": .11}, {"ref": "wacc"}) == {"ref": "wacc"}
    edit_yaml(linked.params_file, lambda p: p.update(scenarios={
        "stress": {"thesis": "Higher risk-free rate", "bindings": {"riskfree": .0707}},
        "override": {"thesis": "Explicit discount assumption", "valuation": {"wacc": {"value": .12}}},
    }))
    ws = Workspace(linked.company)
    assert ws.model("stress").value()["per_share"] == pytest.approx(44.7010442150672)
    assert ws.model("base").value()["per_share"] == pytest.approx(66.7825642215609)
    assert "wacc" not in ws.model("override").valuation_refs
    assert ws.model("override").valuation["wacc"] == .12


def test_reference_uses_same_monte_carlo_draw(linked):
    edit_yaml(linked.params_file, lambda p: p["bindings"].update(
        riskfree={"dist": "uniform", "low": .055, "high": .08}))
    for seed in range(5):
        m = Workspace(linked.company).model(rng=random.Random(seed))
        assert m.valuation["wacc"] == m.run()["wacc"]
        assert m.value()["per_share"] == pytest.approx(m.run()["per_share"][4])


def test_reference_only_inputs_and_first_last_period_semantics(workspace):
    def template(p):
        p["parameters"].extend([{"name": "discount", "unit": "ratio"},
                                {"name": "share_count", "unit": "count"},
                                {"name": "terminal", "unit": "ratio"},
                                {"name": "cash_balance", "unit": "currency"}])
    edit_yaml(workspace.root / "templates/lemonade.yaml", template)
    def params(p):
        p["bindings"].update(discount=[.21, .22, .23], share_count=[10, 20, 30],
                             terminal=[.01, .02, .03], cash_balance=[7, 8, 9])
        p["valuation"].update(wacc={"ref": "discount"}, shares={"ref": "share_count"},
                              terminal_growth={"ref": "terminal"}, net_cash={"ref": "cash_balance"})
    edit_yaml(workspace.params_file, params)
    ws = Workspace(workspace.company)
    linked = ws.model()
    flows = linked.run()["profit"]
    present = flows[0] / 1.21 + flows[1] / (1.21 * 1.22) + flows[2] / (1.21 * 1.22 * 1.23)
    terminal = flows[2] * 1.03 / (.23 - .03) / (1.21 * 1.22 * 1.23)
    expected = (present + terminal + 7) / 10
    assert linked.value()["per_share"] == pytest.approx(expected)
    assert ExcelCalculator(Compiler(linked).build()).cell("DCF", "B13") == pytest.approx(expected)
    assert browser(dashboard_data(ws))["result"]["value"]["per_share"] == pytest.approx(expected)


def test_valuation_reference_cannot_be_used_as_input_binding(linked):
    edit_yaml(linked.params_file, lambda p: p["bindings"].update(riskfree={"ref": "risk_premium"}))
    with pytest.raises(BurrError):
        Workspace(linked.company).model()
