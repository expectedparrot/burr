"""Read-only agent routing from model, journal, and artifact evidence."""

import hashlib
import json
import shlex
import sys
from pathlib import Path

from . import operations as ops
from .errors import BurrError, require
from .storage import atomic_write, read_yaml, json_text


DELIVERABLES = {"dashboard": ("dashboard", "html"), "csv": ("export", "csv"), "excel": ("emit", "xlsx")}


def guide():
    return {"ok": True, "protocol_version": "1", "guide": Path(__file__).with_name("agent_guide.md").read_text()}


def fingerprints(workspace):
    return {name: workspace.fingerprint(name) for name in ["base", *workspace.scenarios()]}


def receipt_path(output):
    return Path(str(output) + ".burr.json")


def write_receipt(workspace, output, command, scenario):
    """Called only after a successful CLI export, which already writes artifacts."""
    path = Path(output).resolve()
    receipt = {"protocol_version": "1", "company": str(workspace.company.resolve()),
               "command": command, "scenario": scenario, "output": str(path),
               "fingerprints": fingerprints(workspace),
               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    target = receipt_path(path)
    atomic_write(target, json_text(receipt))
    return str(target)


def artifact_status(workspace, path, command, scenario, current):
    result = {"output": str(path), "receipt": str(receipt_path(path)), "current": False}
    if not path.is_file():
        return {**result, "reason": "missing_output"}
    try:
        receipt = json.loads(receipt_path(path).read_text())
        expected = {"protocol_version": "1", "company": str(workspace.company.resolve()),
                    "command": command, "scenario": scenario, "output": str(path), "fingerprints": current,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if receipt != expected:
            return {**result, "reason": "stale_or_modified_output"}
    except (OSError, ValueError):
        return {**result, "reason": "missing_or_invalid_receipt"}
    return {**result, "current": True, "reason": "verified_receipt"}


def next_step(workspace, *, scenario="base", patch=None, question=None, finding=None,
              deliverable="dashboard", output=None):
    """Compute the next action; never infer that a read-only command was run."""
    require(deliverable in DELIVERABLES, "usage_error", "unknown deliverable", exit_code=2)
    for key, text in (("question", question), ("finding", finding)):
        require(text is None or text.strip(), "usage_error", f"{key} must not be blank", exit_code=2)
    company = str(workspace.company.resolve())
    root = str(workspace.root.resolve())
    command, extension = DELIVERABLES[deliverable]
    # The directory name is validated by Workspace/model before any action executes.
    path = Path(output) if output else workspace.root / "artifacts" / f"{workspace.company.name}-{scenario}.{extension}"
    path = path.resolve()
    from .cli import output_path
    output_path(workspace, path)
    require(path.suffix.lower() == f".{extension}", "usage_error",
            f"{deliverable} output must end in .{extension}", exit_code=2)
    patch_path = str(Path(patch).resolve()) if patch else None

    def argv(name, *arguments):
        return [sys.executable, "-m", "burr", "--json", "-C", root, "-s", scenario, name, company, *map(str, arguments)]

    def action(name, reason, *arguments, writes=(), expected=None):
        args = argv(name, *arguments)
        return {"command": name, "argv": args, "shell": shlex.join(args), "cwd": root,
                "reason": reason, "mutates": bool(writes), "writes": list(writes),
                "expected": expected, "requires_network": False}

    resume = argv("next", "--deliverable", deliverable, "--output", path)
    for flag, value in (("--patch", patch_path), ("--question", question), ("--finding", finding)):
        if value is not None:
            resume.append(f"{flag}={value}")
    result = {"ok": True, "protocol_version": "1", "company": company, "workspace": root,
              "scenario": scenario, "deliverable": deliverable, "resume_argv": resume,
              "state": "", "complete": False, "action": None, "next_steps": [],
              "required_inputs": [], "diagnostics": [], "warnings": [], "evidence": {}}

    def finish(state, message, selected=None, required=()):
        result.update(state=state, message=message, action=selected, required_inputs=list(required),
                      next_steps=[selected] if selected else [], complete=state == "complete")
        return result

    try:
        validation = ops.coherent(workspace)
        if scenario not in ["base", *workspace.scenarios()]:
            return finish("needs_input", f"Unknown scenario {scenario!r}. Select one of: base, {', '.join(workspace.scenarios())}.",
                          required=[{"name": "scenario", "reason": "Pass -s with an existing scenario name."}])
        model = workspace.model(scenario)
        current = fingerprints(workspace)
    except BurrError as exc:
        result["diagnostics"] = [d.to_dict() for d in exc.diagnostics]
        return finish("repair", "Repair the reported model diagnostics, then rerun next.",
                      action("test", "Inspect all scenario diagnostics; fix the referenced definitions.",
                             expected="Every scenario passes lint, fact validation, and model checks."))
    result["fingerprint"] = current[scenario]
    result["warnings"] = [w for row in validation["scenarios"] for w in row["warnings"]]
    result["evidence"]["validation"] = {"ok": True, "scenarios": list(current)}
    result["evidence"]["assumptions_file"] = str(workspace.params_file.resolve())
    result["evidence"]["assumptions"] = model.params["bindings"]
    if not model.params.get("valuation"):
        return finish("needs_input", "The valuation workflow requires cash-flow, discount-rate, and share assumptions. Operating run/plot remain available.",
                      required=[{"name": "valuation", "reason": "Supply a supported valuation mapping with a rationale and consistent units."}])
    result["evidence"]["comparison"] = [{"scenario": name, **workspace.model(name).value()} for name in current]
    journal = ops.journal(workspace)["entries"]
    # Journal filenames sort lexically in the low-level API; exp-1000 must
    # follow exp-999 when selecting the most recent successful append.
    for entry in journal:
        require(entry["id"].startswith("exp-") and entry["id"][4:].isdigit(),
                "eval_error", "invalid journal experiment identifier")
    journal.sort(key=lambda entry: int(entry["id"][4:]))
    relevant = [entry for entry in journal if entry.get("scenario", "base") == scenario]
    if question is not None:
        relevant = [entry for entry in relevant if entry["question"] == question]
    if patch_path:
        envelope = read_yaml(patch_path)
        relevant = [entry for entry in relevant if entry["patch"] == envelope]
        try:
            trial = ops.try_patch(workspace, envelope, scenario)
        except BurrError as exc:
            result["diagnostics"] = [d.to_dict() for d in exc.diagnostics]
            return finish("repair_patch", "Repair the proposed patch and rerun next; no changes were written.",
                          action("try", "Inspect patch diagnostics.", patch_path, expected="A valid in-memory trial."))
        result["evidence"]["trial"] = trial
    else:
        envelope = relevant[-1]["patch"] if relevant else None

    result["evidence"]["journal"] = [{"id": e["id"], "question": e["question"], "finding": e["finding"],
                                       "stale": e["stale"]} for e in relevant]
    # Most recent matching record defines this workflow. Unrelated historic stale
    # entries do not block a new, explicitly selected question or patch.
    selected = relevant[-1] if relevant else None
    if selected is not None:
        try:
            replay = ops.replay(workspace, selected["id"])
            result["evidence"]["replay"] = replay
        except BurrError as exc:
            result["diagnostics"] = [d.to_dict() for d in exc.diagnostics]
            result["evidence"]["suggested_patch"] = selected["patch"]
            return finish("review_stale", "The selected journal experiment cannot be replayed. Repair or replace its patch; preserve the old record.",
                          required=[{"name": "patch", "reason": "Write a revised patch and pass --patch PATH with the question you intend to pursue."}])
        if selected["stale"] or replay["status"] != "HOLDS":
            result["evidence"]["suggested_patch"] = selected["patch"]
            result["evidence"]["trial"] = replay["current"]
            # Replay is read-only; explicitly append fresh evidence after review.
            selected = None
            result["warnings"].append({"code": "stale_evidence", "message": "Replay does not refresh the old journal fingerprint; review the current result and append a new finding."})
    if selected is not None and finding is not None and finding != selected["finding"]:
        selected = None
    if selected is None:
        required = []
        if not patch_path:
            required.append({"name": "patch", "reason": "Translate the principal's belief into a YAML patch with a rationale; pass its path as --patch."})
        if question is None:
            required.append({"name": "question", "reason": "State the principal's question with --question; do not invent their objective."})
        if finding is None:
            required.append({"name": "finding", "reason": "Inspect the trial/replay results, then supply your interpretation with --finding."})
        if required:
            return finish("needs_input", "Inspect the evidence and supply the missing inputs, then rerun next. --json controls output; the patch is YAML.", required=required)
        return finish("record", "The proposed patch is valid. Append the question and reviewed finding to the journal.",
                      action("record", "Preserve current machine-computed evidence without applying the patch.",
                             patch_path, f"--question={question}", f"--finding={finding}",
                             writes=[str(workspace.company / "experiments" / "exp-NNN.yaml")],
                             expected="A new matching journal entry with the current fingerprint."))

    result["evidence"]["selected_experiment"] = selected["id"]
    result["evidence"]["finding_warnings"] = selected.get("warnings", [])
    result["warnings"].extend(selected.get("warnings", []))
    if selected.get("warnings"):
        return finish("needs_input", "Review the recorded finding warnings before presenting this evidence. Append a corrected finding if necessary.",
                      required=[{"name": "reviewed_finding", "reason": "Use record with corrected claims; next will select the newest matching entry."}])
    artifact = artifact_status(workspace, path, command, scenario, current)
    result["evidence"]["artifact"] = artifact
    if not artifact["current"]:
        return finish("export", "Current experiment evidence is available. Generate the requested deliverable from the saved scenario.",
                      action(command, artifact["reason"], "-o", path, "--receipt",
                             writes=[str(path), str(receipt_path(path))],
                             expected="An output file and receipt matching the current model and file contents."))
    return finish("complete", "Model checks pass, the selected experiment is current and replays, and the requested deliverable has a valid receipt. Present the finding, assumptions, and artifact to the principal; assess their question explicitly.")
