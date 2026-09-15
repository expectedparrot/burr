"""Exercise the agent loop through the public CLI, including freshness failures."""

import json
from pathlib import Path
import subprocess

import pytest

from burr.cli import main
from burr.storage import yaml_text
from conftest import edit_yaml


def invoke(capsys, *args):
    status = main(["--json", *map(str, args)])
    captured = capsys.readouterr()
    assert not captured.err
    return status, json.loads(captured.out)


def inspect(capsys, workspace, *args):
    code, result = invoke(capsys, "-C", workspace.root, "next", workspace.company, *args)
    assert code == 0 and result["ok"]
    return result


def execute(action):
    process = subprocess.run(action["argv"], cwd=action["cwd"], text=True, capture_output=True)
    assert process.returncode == 0, process.stdout + process.stderr
    return json.loads(process.stdout)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def proposal(workspace):
    path = workspace.root / "a patch with spaces.yaml"
    path.write_text(yaml_text({"bindings": {"price": {"value": 3, "rationale": "Convenience premium."}}}))
    return path


@pytest.mark.parametrize("deliverable", ["dashboard", "csv", "excel"])
def test_golden_path_follows_returned_argv_and_detects_tampering(workspace, capsys, deliverable):
    patch = proposal(workspace)
    before = snapshot(workspace.root)
    first = inspect(capsys, workspace)
    assert first["state"] == "needs_input" and first["action"] is None
    assert {r["name"] for r in first["required_inputs"]} == {"patch", "question", "finding"}
    trial = inspect(capsys, workspace, "--patch", patch, "--question", "Price premium?")
    assert trial["evidence"]["trial"]["gap"] > 0
    assert [r["name"] for r in trial["required_inputs"]] == ["finding"]
    assert snapshot(workspace.root) == before
    options = ["--patch", patch, "--question", "Price premium?", "--finding", "Value rises; demand held fixed.",
               "--deliverable", deliverable]
    step = inspect(capsys, workspace, *options)
    assert step["state"] == "record" and step["action"]["mutates"]
    assert step["action"]["argv"][0].startswith("/")
    recorded = execute(step["action"])
    assert recorded["experiment"]["id"] == "exp-001"
    assert (workspace.params_file).read_bytes() == before["companies/stand/params.yaml"]
    # resume_argv carries both task selection and deliverable across steps.
    step = execute({"argv": step["resume_argv"], "cwd": "/private/tmp"})
    assert step["state"] == "export"
    artifact = execute(step["action"])
    assert Path(artifact["receipt"]).is_file()
    complete = execute({"argv": step["resume_argv"], "cwd": "/private/tmp"})
    assert complete["state"] == "complete" and complete["complete"]
    assert complete["action"] is None and complete["next_steps"] == []
    before = snapshot(workspace.root)
    assert inspect(capsys, workspace, *options) == complete
    assert snapshot(workspace.root) == before
    Path(artifact["output"]).write_bytes(b"changed after export")
    step = inspect(capsys, workspace, *options)
    assert step["state"] == "export"
    assert step["evidence"]["artifact"]["reason"] == "stale_or_modified_output"


def test_model_repair_and_patch_repair_are_actionable(workspace, capsys):
    patch = proposal(workspace)
    patch.write_text("bindings:\n  price: -1\n")
    step = inspect(capsys, workspace, "--patch", patch)
    assert step["state"] == "repair_patch" and step["diagnostics"]
    assert step["action"]["command"] == "try"
    edit_yaml(workspace.params_file, lambda d: d["bindings"].update(price=-1))
    step = inspect(capsys, workspace)
    assert step["state"] == "repair" and step["diagnostics"]
    assert step["action"]["command"] == "test"


def test_stale_record_replays_then_requires_fresh_evidence(workspace, capsys):
    patch = proposal(workspace)
    options = ["--patch", patch, "--question", "Price?", "--finding", "Value rises."]
    execute(inspect(capsys, workspace, *options)["action"])
    old_entry = (workspace.company / "experiments/exp-001.yaml").read_bytes()
    edit_yaml(workspace.params_file, lambda d: d["bindings"].update(cup_growth=.02))
    before = snapshot(workspace.root)
    step = inspect(capsys, workspace)
    assert step["state"] == "needs_input" and step["evidence"]["replay"]["status"] == "DRIFTED"
    assert step["evidence"]["suggested_patch"]
    assert snapshot(workspace.root) == before
    step = inspect(capsys, workspace, *options)
    assert step["state"] == "record"
    execute(step["action"])
    step = inspect(capsys, workspace, *options)
    assert step["state"] == "export" and step["evidence"]["selected_experiment"] == "exp-002"
    assert (workspace.company / "experiments/exp-001.yaml").read_bytes() == old_entry


def test_receipt_invalidation_new_question_and_corrected_finding(workspace, capsys):
    patch = proposal(workspace)
    options = ["--patch", patch, "--question", "Price?", "--finding", "Value rises."]
    execute(inspect(capsys, workspace, *options)["action"])
    exported = execute(inspect(capsys, workspace, *options)["action"])
    Path(exported["receipt"]).write_text("not JSON")
    assert inspect(capsys, workspace, *options)["state"] == "export"
    assert inspect(capsys, workspace, "--question", "A different question?")["state"] == "needs_input"
    corrected = options[:-1] + ["Value rises with volume fixed."]
    assert inspect(capsys, workspace, *corrected)["state"] == "record"
    # A valid change to a different scenario also invalidates the manifest.
    execute(inspect(capsys, workspace, *options)["action"])
    edit_yaml(workspace.params_file, lambda d: d["scenarios"]["bear"]["bindings"].update(price=2))
    step = inspect(capsys, workspace, *options)
    assert not step["complete"]


def test_guide_without_workspace_and_existing_commands_remain_read_only(workspace, capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    status, result = invoke(capsys, "guide")
    assert status == 0 and "Golden path" in result["guide"]
    assert main(["guide"]) == 0
    assert "Golden path" in capsys.readouterr().out
    patch = proposal(workspace)
    before = snapshot(workspace.root)
    assert invoke(capsys, "-C", workspace.root, "try", "stand", patch)[0] == 0
    assert snapshot(workspace.root) == before
    assert inspect(capsys, workspace, "-s", "missing")["state"] == "needs_input"
    edit_yaml(workspace.params_file, lambda d: d.pop("valuation"))
    step = inspect(capsys, workspace)
    assert step["state"] == "needs_input" and step["required_inputs"][0]["name"] == "valuation"


def test_next_rejects_source_output_and_malformed_inputs(workspace, capsys):
    assert invoke(capsys, "-C", workspace.root, "next", "stand", "--output", workspace.params_file)[0] == 1
    assert invoke(capsys, "-C", workspace.root, "next", "stand", "--question", " ")[0] == 2
    path = workspace.root / "broken.yaml"
    path.write_text("bindings: [")
    assert invoke(capsys, "-C", workspace.root, "next", "stand", "--patch", path)[0] == 2
    # Direct exports are unchanged unless --receipt is requested.
    path = workspace.root / "output.csv"
    status, result = invoke(capsys, "-C", workspace.root, "export", "stand", "-o", path)
    assert status == 0 and "receipt" not in result
    assert not Path(str(path) + ".burr.json").exists()


def test_stale_but_holding_result_still_needs_review(workspace, capsys):
    patch = proposal(workspace)
    options = ["--patch", patch, "--question", "Price?", "--finding", "Value rises."]
    execute(inspect(capsys, workspace, *options)["action"])
    edit_yaml(workspace.params_file, lambda d: d["bindings"]["cups0"].update(rationale="Same count, reviewed source."))
    result = inspect(capsys, workspace)
    assert result["state"] == "needs_input" and not result["complete"]
    assert result["evidence"]["replay"]["status"] == "HOLDS"
    assert any(w["code"] == "stale_evidence" for w in result["warnings"])


def test_unreplayable_patch_can_be_replaced(workspace, capsys):
    patch = proposal(workspace)
    options = ["--patch", patch, "--question", "Price?", "--finding", "Value rises."]
    execute(inspect(capsys, workspace, *options)["action"])
    edit_yaml(workspace.root / "templates/lemonade.yaml", lambda d: d["checks"].append("price <= 2.75"))
    result = inspect(capsys, workspace)
    assert result["state"] == "review_stale" and result["action"] is None
    assert result["required_inputs"][0]["name"] == "patch"
    patch.write_text(yaml_text({"bindings": {"price": {"value": 2.6, "rationale": "A smaller premium."}}}))
    result = inspect(capsys, workspace, *options)
    assert result["state"] == "record"
    execute(result["action"])
    assert inspect(capsys, workspace, *options)["state"] == "export"


def test_selected_scenario_and_finding_warning_recovery(workspace, capsys):
    patch = proposal(workspace)
    options = ["-s", "bear", "--patch", patch, "--question", "Price?", "--finding", "gap: 999999"]
    result = inspect(capsys, workspace, *options)
    assert result["action"]["argv"][result["action"]["argv"].index("-s") + 1] == "bear"
    execute(result["action"])
    assert inspect(capsys, workspace, *options)["state"] == "needs_input"
    options[-1] = "Value rises with volume and costs held fixed."
    execute(inspect(capsys, workspace, *options)["action"])
    step = inspect(capsys, workspace, *options)
    assert step["state"] == "export"
    assert step["evidence"]["selected_experiment"] == "exp-002"


def test_latest_record_order_after_one_thousand_experiments(workspace, capsys):
    from burr.storage import read_yaml
    patch = proposal(workspace)
    step = inspect(capsys, workspace, "--patch", patch, "--question", "Price?", "--finding", "Value rises.")
    execute(step["action"])
    original = read_yaml(workspace.company / "experiments/exp-001.yaml")
    for number in (999, 1000):
        entry = {**original, "id": f"exp-{number}"}
        (workspace.company / "experiments" / f"exp-{number}.yaml").write_text(yaml_text(entry))
    assert inspect(capsys, workspace)["evidence"]["selected_experiment"] == "exp-1000"


def test_action_preserves_option_like_questions_and_shell_characters(workspace, capsys):
    patch = proposal(workspace)
    question = "--price 'premium' $(do-not-run)"
    finding = "--higher value\nwith volume fixed"
    step = inspect(capsys, workspace, "--patch", patch, f"--question={question}", f"--finding={finding}")
    recorded = execute(step["action"])["experiment"]
    assert (recorded["question"], recorded["finding"]) == (question, finding)
    resumed = execute({"argv": step["resume_argv"], "cwd": step["workspace"]})
    assert resumed["state"] == "export"
