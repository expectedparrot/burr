import math
import random
import struct

import pytest

from burr.errors import BurrError
from burr.expressions import Evaluator, parse, topological
from burr.model import Workspace
from burr.storage import merge, read_yaml, yaml_text
from burr.values import resolve
from conftest import edit_yaml


def code(error):
    return error.value.diagnostics[0].code


def test_hand_computed_dcf(workspace):
    model = workspace.model()
    assert model.run()["cups"] == pytest.approx([1100, 1182.5, 1241.625])
    profit = [1650, 1773.75, 1862.4375]
    ev = sum(v / 1.2 ** (i + 1) for i, v in enumerate(profit)) + profit[-1] / 0.2 / 1.2 ** 3
    assert model.value()["per_share"] == pytest.approx(ev / 2)


@pytest.mark.parametrize("form, expected", [
    (0.24, 0.24), ({"value": 3, "rationale": "test"}, 3),
    ([1, 2, 3], [1, 2, 3]), ({"start": 1, "end": 3}, [1, 2, 3]),
    ({"start": 1, "end": 4, "shape": "geometric"}, [1, 2, 4]),
    ({"until": {2028: 1}, "after": 2}, [1, 1, 2]),
    ({"dist": "normal", "mean": 2, "sd": 1}, 2),
    ({"dist": "uniform", "low": 2, "high": 4}, 3),
    ({"start": 1, "end": 5, "dist": "normal", "mean": 3, "sd": 0, "applies_to": "end"}, [1, 2, 3]),
])
def test_value_forms(form, expected):
    assert resolve(form, [2027, 2028, 2029]) == expected


@pytest.mark.parametrize("form, expected_code", [
    ([1, 2], "length_mismatch"), (True, "eval_error"), (float("nan"), "eval_error"),
    ({"start": 0, "end": 3, "shape": "geometric"}, "eval_error"),
    ({"dist": "normal", "mean": 0, "sd": -1}, "eval_error"),
    ({"dist": "uniform", "low": 3, "high": 2}, "eval_error"),
    ({"start": 1, "end": 3, "dist": "normal", "mean": 1, "sd": 0}, "eval_error"),
    ({"value": 3, "unit": "dollars"}, "unit_mismatch"),
    ({"value": 1, "start": 1, "end": 2}, "eval_error"),
])
def test_invalid_forms(form, expected_code):
    with pytest.raises(BurrError) as error:
        resolve(form, [2027, 2028, 2029])
    assert code(error) == expected_code


def test_draw_clamp_and_metadata():
    form = {"dist": "normal", "mean": 10, "sd": 0, "lo": 0, "hi": 1}
    assert resolve(form, [2027]) == 10
    assert resolve(form, [2027], random.Random(42)) == 1
    assert resolve({"value": 0.2, "confidence": "low", "as_of": "2026-02-15", "source": "a"}, [2027]) == .2


def test_leaf_replacement():
    base = {"bindings": {"x": {"start": 1, "end": 2, "dist": "normal", "mean": 2, "sd": 1, "rationale": "base"}, "y": 3}}
    changed = merge(base, {"bindings": {"x": {"value": 4, "source": "override"}}})
    assert changed["bindings"] == {"x": {"value": 4, "source": "override"}, "y": 3}
    assert base["bindings"]["x"]["dist"] == "normal"


@pytest.mark.parametrize("expression", ["__import__('os')", "a.b", "a[0]", "a if b else c", "2 * a", "a ** b", "sum(a)", "grow(a)", "+a", "a > b"])
def test_closed_grammar(expression):
    with pytest.raises(BurrError):
        parse(expression)


def test_recursion_and_builtins(recurrence):
    model = recurrence.model()
    rows = model.run()
    assert rows["cash"] == pytest.approx([1650, 3423.75, 5286.1875])
    assert rows["change"] == pytest.approx(rows["profit"])
    assert rows["small"] == [1650, 2000, 2000]
    assert rows["large"] == pytest.approx([2000, 3423.75, 5286.1875])
    multiple = model.value(exit_multiple=5)
    expected = sum(v / 1.2 ** (t + 1) for t, v in enumerate(rows["profit"])) + rows["profit"][-1] * 5 / 1.2 ** 3
    assert multiple["ev"] == pytest.approx(expected)


def test_vector_period_bit_identical(workspace):
    # Nontrivial floating-point inputs and every lag-free builtin.
    exprs = {"grown": parse("grow(x, g)"), "change": parse("delta(grown, x)"),
             "clipped": parse("clip(abs(change), lo, hi)"), "ratio": parse("minimum(grown, hi) / maximum(grown, lo)")}
    inputs = {"x": 7.123456789, "g": [0.13, -0.002, .371], "lo": 0.123, "hi": 1500.42}
    a = Evaluator(exprs, inputs, 3, topological(exprs)).evaluate()
    b = Evaluator(exprs, inputs, 3, topological(exprs)).evaluate(force_period=True)
    assert {k: [struct.pack("d", x) for x in v] for k, v in a.items()} == {k: [struct.pack("d", x) for x in v] for k, v in b.items()}


def test_lag_broken_cycle_and_instant_cycle():
    good = {"a": parse("lag(b, seed) + x"), "b": parse("a + x")}
    assert Evaluator(good, {"seed": 0, "x": 1}, 3, topological(good)).evaluate()["b"] == [2, 4, 6]
    with pytest.raises(BurrError) as error:
        topological({"a": parse("b + x"), "b": parse("a + x")})
    assert code(error) == "circular_dependency"


@pytest.mark.parametrize("edit, expected", [
    (lambda d: d["bindings"].pop("price"), "unbound_parameter"),
    (lambda d: d["bindings"].update({"orphan": 1}), "orphan_binding"),
    (lambda d: d["bindings"].update({"price": [1, 2]}), "length_mismatch"),
    (lambda d: d["bindings"].update({"price": {"value": 2.5, "unit": "currency_m"}}), "unit_mismatch"),
])
def test_lint_diagnostics(workspace, edit, expected):
    edit_yaml(workspace.params_file, edit)
    with pytest.raises(BurrError) as error:
        Workspace(workspace.company).model()
    assert code(error) == expected


def test_fact_mismatch_and_tolerance(workspace):
    edit_yaml(workspace.params_file, lambda d: d["bindings"].update({"cups0": {"value": 1010}}))
    with pytest.raises(BurrError) as error:
        Workspace(workspace.company).model().validate()
    assert code(error) == "fact_mismatch"
    edit_yaml(workspace.params_file, lambda d: d["bindings"]["cups0"].update({"tolerance": .02}))
    assert Workspace(workspace.company).model().validate()[0]["ok"]


def test_unit_and_ratio_warnings(workspace):
    edit_yaml(workspace.params_file, lambda d: d["bindings"].update({"cup_growth": 2}))
    assert "ratio_magnitude" in [d.code for d in Workspace(workspace.company).model().warnings]
    edit_yaml(workspace.root / "templates/lemonade.yaml", lambda d: d["lines"].update({"profit": "revenue + cost_pct"}))
    with pytest.raises(BurrError) as error:
        Workspace(workspace.company).model()
    assert code(error) == "unit_mismatch"


def test_unknown_unused_and_zero_division(workspace):
    template = workspace.root / "templates/lemonade.yaml"
    edit_yaml(template, lambda d: d["lines"].update({"extra": "missing"}))
    with pytest.raises(BurrError) as error:
        Workspace(workspace.company).model()
    assert code(error) == "unknown_name"
    edit_yaml(template, lambda d: d["lines"].update({"extra": "revenue / 0"}))
    with pytest.raises(BurrError) as error:
        Workspace(workspace.company).model().run()
    assert code(error) == "eval_error"


def test_inheritance_and_world(workspace):
    (workspace.root / "world.yaml").write_text("macro: {value: 0.01, unit: ratio}\n")
    child = {"template": "child", "extends": "lemonade", "parameters": [], "lines": {"cups": "grow(cups0, cup_growth + macro)"}}
    (workspace.root / "templates/child.yaml").write_text(yaml_text(child))
    edit_yaml(workspace.params_file, lambda d: d.update({"template": "child"}))
    assert Workspace(workspace.company).model().run()["cups"][0] == pytest.approx(1110)
    child["parameters"] = [{"name": "price", "unit": "currency_m"}]
    (workspace.root / "templates/child.yaml").write_text(yaml_text(child))
    with pytest.raises(BurrError) as error:
        Workspace(workspace.company).model()
    assert code(error) == "unit_mismatch"


def test_decomposition(workspace):
    with (workspace.company / "actuals.csv").open("a") as stream:
        stream.write("2026,online,1000\n2026,offline,1500\n")
    edit_yaml(workspace.root / "templates/lemonade.yaml", lambda d: d.update({"decompositions": {"revenue": ["online", "offline"]}}))
    assert Workspace(workspace.company).model().validate()[-1]["sum"] == 2500


def test_checks_and_valuation_domain(workspace):
    params = read_yaml(workspace.params_file)
    params["bindings"]["cost_pct"] = -1
    with pytest.raises(BurrError) as error:
        workspace.model(params=params).run()
    assert code(error) == "check_failed"
    params["bindings"]["cost_pct"] = .4
    params["valuation"]["terminal_growth"] = .2
    with pytest.raises(BurrError) as error:
        workspace.model(params=params).value()
    assert code(error) == "eval_error"


def test_series_valuation(workspace):
    params = read_yaml(workspace.params_file)
    params["valuation"].update({"wacc": [.1, .2, .3], "terminal_growth": {"start": 0, "end": .03}})
    model = workspace.model(params=params)
    fcf = model.run()["profit"]
    expected = fcf[0] / 1.1 + fcf[1] / 1.32 + fcf[2] / 1.716 + fcf[2] * 1.03 / .27 / 1.716
    assert model.value()["ev"] == pytest.approx(expected)


def test_recurrence_unit_inference(recurrence):
    assert recurrence.model().units["cash"] == "currency"
    edit_yaml(recurrence.root / "templates/lemonade.yaml", lambda d: d["lines"].update({"cash": "lag(cash, cash0) + cost_pct"}))
    with pytest.raises(BurrError) as error:
        Workspace(recurrence.company).model()
    assert code(error) == "unit_mismatch"


def test_strict_units_and_orphan_value_keys(workspace):
    edit_yaml(workspace.root / "templates/lemonade.yaml", lambda d: d["parameters"][0].pop("unit"))
    assert "missing_unit" in [d.code for d in Workspace(workspace.company).model(strict=True).warnings]
    with pytest.raises(BurrError):
        resolve({"value": 2, "sd": 1}, [2027])


def test_currency_zero_floor_and_bounds(workspace):
    edit_yaml(workspace.root / "templates/lemonade.yaml", lambda d: d["lines"].update({
        "tax_base": "maximum(profit, 0)", "bounded": "clip(profit, 0, revenue)",
        "change_from_zero": "delta(revenue, 0)",
    }))
    model = Workspace(workspace.company).model()
    assert model.units["tax_base"] == "currency"
    assert model.units["bounded"] == "currency"
    assert model.units["change_from_zero"] == "currency"
    assert model.run()["tax_base"] == model.run()["profit"]
