import json
import re
import xml.etree.ElementTree as ET

import pytest

from burr.cli import main
from burr.model import Workspace
from burr.plots import emit_plot, plot_data, render
from burr.storage import read_yaml
from conftest import edit_yaml


NS = {"s": "http://www.w3.org/2000/svg"}


def test_axes_zero_negative_and_large_counts():
    from burr.plots import axis_bounds, formatted
    for values in ([0], [42], [-42], [-10, 20], [100000, 900000], [.00001, .00002]):
        low, high, step = axis_bounds(values)
        assert low <= min(0, *values) and high >= max(0, *values)
        assert high > low and step > 0
    assert formatted(800000, "count") == "800,000"
    assert formatted(.187, "ratio") == "18.7%"


def test_reported_and_forecast_named_actuals_remain_separate(workspace):
    edit_yaml(workspace.params_file, lambda d: d["scenarios"].update({"actuals": {"thesis": "A named forecast", "bindings": {"price": 3}}}))
    workspace = Workspace(workspace.company)
    data = plot_data(workspace, kind="series", lines="revenue", scenario="actuals")
    root = ET.fromstring(render(data, ".svg"))
    assert root.find('.//s:g[@data-series="reported"]', NS) is not None
    assert root.find('.//s:g[@data-series="forecast:actuals"]', NS) is not None


def test_series_preserve_engine_values_actuals_units_and_evidence(workspace):
    data = plot_data(workspace, kind="series", lines="revenue,cups", all_scenarios=True)
    assert len(data["panels"]) == 2
    assert [p["unit"] for p in data["panels"]] == ["currency", "count"]
    for panel in data["panels"]:
        for row in panel["rows"]:
            if row["kind"] == "reported":
                assert {k: row[k] for k in ("period", "line", "value")} in workspace.actuals
                assert row["provenance"].endswith("actuals.csv")
            else:
                model = workspace.model(row["scenario"])
                assert row["value"] == model.run()[panel["line"]][model.years.index(row["period"])]
                assert row["provenance"].startswith("templates/")
    assert data["fingerprints"]["base"] == workspace.fingerprint()
    assert data["scenario_theses"]["bear"] == workspace.scenarios()["bear"]["thesis"]


def test_operating_plots_do_not_require_valuation(workspace):
    edit_yaml(workspace.params_file, lambda d: d.pop("valuation"))
    workspace = Workspace(workspace.company)
    for kind in ("series", "scenarios", "drivers"):
        data = plot_data(workspace, kind=kind, lines="revenue")
        assert data["ok"]
        assert "per_share" not in json.dumps(data)


def test_extra_actuals_and_missing_years_are_not_imputed(workspace):
    path = workspace.company / "actuals.csv"
    with path.open("a") as stream:
        stream.write("2023,reported_extra,-2\n2025,reported_extra,4\n")
    workspace = Workspace(workspace.company)
    data = plot_data(workspace, kind="series", lines="reported_extra", actuals_only=True)
    assert [r["period"] for r in data["panels"][0]["rows"]] == [2023, 2025]
    svg = ET.fromstring(render(data, ".svg"))
    group = svg.find('.//s:g[@data-series="reported"]', NS)
    assert len(group.findall("s:circle", NS)) == 2
    assert not group.findall("s:line", NS)
    assert "Unit unspecified" in render(data, ".html")


def test_scenario_bars_include_negative_values_and_selected_period(workspace):
    edit_yaml(workspace.params_file, lambda d: d["scenarios"]["bear"]["bindings"].update({"cost_pct": 1.2}))
    workspace = Workspace(workspace.company)
    data = plot_data(workspace, kind="scenarios", lines="profit", period=2028)
    rows = data["panels"][0]["rows"]
    assert {r["period"] for r in rows} == {2028}
    assert rows[0]["value"] > 0 > rows[1]["value"]
    root = ET.fromstring(render(data, ".svg"))
    bars = root.findall(".//s:g/s:rect", NS)
    assert all(float(bar.attrib["height"]) >= 0 for bar in bars)


def test_driver_ancestors_formulas_and_lag_edges(recurrence):
    data = plot_data(recurrence, kind="drivers", lines="cash", period=2028)
    panel = data["panels"][0]
    ids = {n["id"] for n in panel["nodes"]}
    assert {"cash", "cash0", "profit", "revenue", "price"} <= ids
    assert "limited" not in ids and "cap" not in ids
    assert {"from": "cash", "to": "cash", "lagged": True} in panel["edges"]
    assert next(n for n in panel["nodes"] if n["id"] == "cash")["formula"] == "lag(cash, cash0) + profit"
    root = ET.fromstring(render(data, ".svg"))
    assert any(p.attrib.get("stroke-dasharray") for p in root.findall(".//s:path", NS))


def test_deterministic_files_and_embedded_data(workspace, tmp_path):
    for kind in ("series", "scenarios", "drivers"):
        for ext in (".html", ".svg"):
            path = tmp_path / (kind + ext)
            data = emit_plot(workspace, path, kind=kind, lines="revenue")
            first = path.read_bytes()
            emit_plot(workspace, path, kind=kind, lines="revenue")
            assert path.read_bytes() == first
            if ext == ".svg":
                embedded = json.loads(ET.fromstring(first).find("s:metadata", NS).text)
            else:
                embedded = json.loads(re.search(r'id="plot-data">(.*?)</script>', first.decode(), re.S).group(1))
            assert embedded["panels"] == data["panels"]
            assert embedded["fingerprints"] == data["fingerprints"]


def test_untrusted_labels_are_escaped_and_currency_is_literal(workspace):
    note = '</script><script>alert("x")</script> $12.70 **currency**'
    data = plot_data(workspace, kind="series", lines="revenue", title=note, note=note)
    html = render(data, ".html")
    assert '<script>alert(' not in html
    assert '$12.70 **currency**' in html
    encoded = re.search(r'id="plot-data">(.*?)</script>', html, re.S).group(1)
    assert json.loads(encoded)["note"] == note
    ET.fromstring(render(data, ".svg"))


@pytest.mark.parametrize("options,code", [
    (["--lines", "missing"], 1), (["--lines", ","], 2),
    (["--kind", "drivers", "--lines", "revenue,cups"], 2),
    (["--kind", "scenarios", "--lines", "revenue", "--period", "1990"], 2),
    (["--lines", "revenue", "--period", "2028"], 2),
    (["--lines", "revenue", "--actuals-only", "--all-scenarios"], 2),
])
def test_bad_options_are_structured_and_preserve_output(workspace, capsys, tmp_path, options, code):
    output = tmp_path / "chart.svg"
    output.write_text("previous chart")
    status = main(["plot", str(workspace.company), *options, "-o", str(output), "--json"])
    assert status == code
    assert not json.loads(capsys.readouterr().out)["ok"]
    assert output.read_text() == "previous chart"


def test_cli_json_global_options_and_source_protection(workspace, capsys):
    argv = ["plot", "stand", "--lines", "revenue", "-C", str(workspace.root), "--json", "-s", "bear"]
    assert main([*argv, "-o", "artifacts/chart.html"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["output"] == "artifacts/chart.html"
    assert {r["scenario"] for r in result["panels"][0]["rows"]} == {"actuals", "bear"}
    before = read_yaml(workspace.params_file)
    assert main([*argv, "-o", str(workspace.params_file)]) == 1
    assert json.loads(capsys.readouterr().out)["diagnostics"][0]["code"] == "patch_conflict"
    assert read_yaml(workspace.params_file) == before
