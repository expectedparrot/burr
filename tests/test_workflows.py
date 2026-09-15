import copy
import json

import pytest

from burr.errors import BurrError
from burr.model import Workspace
from burr import operations as ops
from burr.storage import read_yaml, yaml_text
from conftest import edit_yaml


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_try_attribution_and_no_writes(workspace):
    before = snapshot(workspace.root)
    result = ops.try_patch(workspace, {"bindings": {"price": 3, "cost_pct": .5}})
    assert result["gap"] == pytest.approx(sum(row["delta"] for row in result["attribution"]) + result["interactions"])
    assert result["interactions"] != 0
    assert snapshot(workspace.root) == before


def test_explain_conserves_gap(workspace):
    result = ops.explain(workspace, "base", "bear")
    assert result["gap"] < 0
    assert result["gap"] == pytest.approx(sum(row["delta"] for row in result["attribution"]) + result["interactions"])
    assert [abs(r["delta"]) for r in result["attribution"]] == sorted([abs(r["delta"]) for r in result["attribution"]], reverse=True)


@pytest.mark.parametrize("patch", [
    {"op": "set_binding", "name": "cups0", "value": 2000},
    {"op": "set_binding", "name": "price", "value": [1, 2]},
    {"op": "set_binding", "name": "cost_pct", "value": -1},
    {"op": "set_valuation", "name": "shares", "value": 0},
    {"op": "set_valuation", "name": "wacc", "value": 0},
    {"op": "add_scenario", "name": "bear", "thesis": "duplicate", "bindings": {}},
    {"op": "add_check", "check": "revenue < 0"},
    {"op": "fork_template", "name": "bad", "lines": {"revenue": "profit", "profit": "revenue"}},
])
def test_invalid_patch_is_atomic(workspace, patch):
    before = snapshot(workspace.root)
    with pytest.raises(BurrError):
        ops.apply_patch(workspace, patch)
    assert snapshot(workspace.root) == before


def test_durable_patches(workspace):
    patch = {"op": "add_scenario", "name": "bull", "thesis": "Better pricing", "bindings": {"price": 3}}
    ops.apply_patch(workspace, patch)
    fresh = Workspace(workspace.company)
    assert fresh.model("bull").value()["per_share"] > fresh.model().value()["per_share"]
    assert fresh.params["bindings"]["price"] == 2.5
    ops.apply_patch(fresh, {"op": "set_valuation", "name": "net_cash", "value": 100})
    fresh = Workspace(workspace.company)
    assert fresh.model().value()["equity"] - fresh.model().value()["ev"] == 100
    ops.apply_patch(fresh, {"op": "add_check", "check": "profit >= 0"})
    assert "profit >= 0" in Workspace(workspace.company).model().template["checks"]


def test_named_scenario_patch_and_external_scenario(workspace):
    external = workspace.company / "scenarios/upside.yaml"
    external.write_text(yaml_text({"thesis": "Demand", "bindings": {"price": 3}}))
    fresh = Workspace(workspace.company)
    ops.apply_patch(fresh, {"op": "set_binding", "name": "price", "value": 3.5}, "upside")
    assert read_yaml(external)["bindings"]["price"] == 3.5
    assert "upside" not in read_yaml(workspace.params_file)["scenarios"]
    ops.apply_patch(Workspace(workspace.company), {"op": "set_binding", "name": "price", "value": 2}, "bear")
    assert Workspace(workspace.company).model("bear").inputs["price"] == 2


def test_fork_and_rollback(workspace, monkeypatch):
    patch = {"op": "fork_template", "name": "premium", "lines": {"profit": "revenue * (1 - cost_pct) * (1 - cost_pct)"}}
    before = snapshot(workspace.root)
    original = ops.atomic_write
    count = 0

    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(ops, "atomic_write", fail_second)
    with pytest.raises(OSError):
        ops.apply_patch(workspace, patch)
    assert snapshot(workspace.root) == before
    monkeypatch.setattr(ops, "atomic_write", original)
    ops.apply_patch(workspace, patch)
    assert Workspace(workspace.company).params["template"] == "premium"
    assert (workspace.root / "templates/lemonade.yaml").read_bytes() == before["templates/lemonade.yaml"]


def test_mc_seed_and_valuation_distribution(workspace):
    edit_yaml(workspace.params_file, lambda d: d["valuation"].update({"wacc": {"dist": "uniform", "low": .15, "high": .25}}))
    workspace = Workspace(workspace.company)
    first = ops.monte_carlo(workspace, "base", 40, 42, full=True)
    assert first == ops.monte_carlo(workspace, "base", 40, 42, full=True)
    assert first != ops.monte_carlo(workspace, "base", 40, 43, full=True)
    assert sum(r["count"] for r in first["histogram"]) == 40
    assert "draws" not in ops.monte_carlo(workspace, "base", 2, 42)


def test_sensitivity_and_graph(workspace):
    result = ops.sensitivity(workspace, "base", "price=2:3:.5", "wacc=.1:.2:.05")
    assert len(result["grid"]) == 3 and len(result["grid"][0]) == 3
    assert result["grid"][0][0] < result["grid"][0][1]
    assert result["grid"][0][0] > result["grid"][1][0]
    tree = ops.trace(workspace.model(), "revenue")["tree"]
    assert tree["name"] == "revenue"
    assert any(r["name"] == "price" for r in tree["dependencies"])


def test_journal_staleness_replay_and_filters(workspace):
    patch = {"bindings": {"price": {"value": 3, "rationale": "pricing power"}}}
    result = ops.record(workspace, patch, "base", "Can price rise?", "Pricing lifts value", "price,bull")
    assert result["experiment"]["id"] == "exp-001"
    original = (workspace.company / "experiments/exp-001.yaml").read_bytes()
    assert not ops.journal(workspace)["entries"][0]["stale"]
    assert len(ops.journal(workspace, param="price", tag="bull")["entries"]) == 1
    assert not ops.journal(workspace, param="cost_pct")["entries"]
    assert ops.replay(workspace, "exp-001")["status"] == "HOLDS"
    ops.apply_patch(workspace, {"op": "set_binding", "name": "cost_pct", "value": .5})
    fresh = Workspace(workspace.company)
    assert ops.journal(fresh, stale=True)["entries"][0]["stale"]
    assert ops.replay(fresh, "exp-001")["status"] == "DRIFTED"
    assert (workspace.company / "experiments/exp-001.yaml").read_bytes() == original
    assert len(ops.show(fresh, "base", "price")["experiments"]) == 1
    ops.record(fresh, patch, "base", "Again?", "gap: -999", "")
    assert (workspace.company / "experiments/exp-002.yaml").exists()
    assert ops.journal(fresh)["entries"][1]["warnings"][0]["code"] == "finding_mismatch"


def test_logic_changes_stale_evidence(workspace):
    ops.record(workspace, {"bindings": {"price": 3}}, "base", "Price?", "Higher", "")
    edit_yaml(workspace.root / "templates/lemonade.yaml", lambda d: d["lines"].update({"profit": "revenue * (1 - cost_pct) * (1 - cost_pct)"}))
    assert ops.journal(Workspace(workspace.company))["entries"][0]["stale"]


def test_recorded_scenario_can_replay_after_application(workspace):
    patch = {"op": "add_scenario", "name": "upside", "thesis": "Pricing", "bindings": {"price": 3}}
    ops.record(workspace, patch, "base", "Price?", "Higher", "")
    ops.apply_patch(workspace, patch)
    assert ops.replay(Workspace(workspace.company), "exp-001")["status"] == "HOLDS"


def test_calibration_proposes_without_writes(workspace):
    before = snapshot(workspace.root)
    result = ops.calibrate(workspace, "base")
    assert result["patch"]["bindings"]["cups0"]["value"] == 1000
    assert result["patch"]["bindings"]["price"]["value"] == 2.5
    assert result["patch"]["bindings"]["cup_growth"]["value"] == pytest.approx(1 / 9)
    assert all(v["source"] == "derived from actuals" for v in result["patch"]["bindings"].values())
    assert snapshot(workspace.root) == before


def test_calibration_inverts_cost_ratio(workspace):
    with (workspace.company / "actuals.csv").open("a") as stream:
        stream.write("2026,profit,1500\n")
    proposal = ops.calibrate(Workspace(workspace.company), "base")
    assert proposal["patch"]["bindings"]["cost_pct"]["value"] == pytest.approx(.4)
