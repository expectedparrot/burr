"""Strict metric coverage, numerical agreement, and scenario-response grading."""

import math

from burr.model import Workspace

from .catalog import MODELS, case_inputs, variants
from .models import outputs
from .oracle import digest

REL_TOL, ABS_TOL = 1e-9, 1e-7


def compare(actual, expected, label):
    """Missing/extra metrics and truncated vectors are failures, not skipped cells."""
    if set(actual) != set(expected):
        raise ValueError(f"Metric coverage mismatch for {label}: actual={sorted(actual)}, expected={sorted(expected)}")
    checks = []
    for metric, values in expected.items():
        if len(actual[metric]) != len(values):
            raise ValueError(f"Metric length mismatch: {label}/{metric}")
        for i, (got, wanted) in enumerate(zip(actual[metric], values)):
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                       for v in (got, wanted)):
                raise ValueError(f"Non-finite/non-numeric metric: {label}/{metric}[{i}]")
            checks.append({"metric": metric, "index": i, "actual": got, "expected": wanted,
                           "absolute_error": abs(got - wanted),
                           "ok": math.isclose(got, wanted, rel_tol=REL_TOL, abs_tol=ABS_TOL)})
    return checks


def evaluate(workspace, inputs, reference, manifest):
    if reference["schema_version"] != 1 or reference["catalog_digest"] != digest(MODELS):
        raise ValueError("Reference schema/catalog mismatch; review and recapture explicitly")
    wanted = {f"{name}--{s}" for name in MODELS for s in variants(name)}
    if set(reference["cases"]) != wanted:
        raise ValueError("Reference case coverage mismatch")
    cases, actuals = {}, {}
    for name, spec in MODELS.items():
        ws = Workspace(workspace / "companies" / name)
        for scenario in variants(name):
            key = f"{name}--{scenario}"
            expected = reference["cases"][key]
            raw = case_inputs(name, inputs[name], scenario)
            if expected["input_digest"] != digest(raw):
                raise ValueError(f"Reference input mismatch: {key}")
            if expected["source_sha256"] != manifest["sources"][name]["sha256"]:
                raise ValueError(f"Reference source mismatch: {key}")
            if set(expected["outputs"]) != set(spec["outputs"]) or any(
                len(expected["outputs"][k]) != len(cells) for k, cells in spec["outputs"].items()
            ):
                raise ValueError(f"Reference metric coverage mismatch: {key}")
            actuals[key] = outputs(ws.model(scenario), name, raw)
            checks = compare(actuals[key], expected["outputs"], key)
            cases[key] = {"checks": checks, "ok": all(c["ok"] for c in checks)}
    # Check changes as well as absolute values: a model ignoring the perturbation fails.
    for name in MODELS:
        base_key = f"{name}--base"
        for scenario in MODELS[name]["variants"]:
            key = f"{name}--{scenario}"
            changes = {k: [v - b for v, b in zip(values, actuals[base_key][k])]
                       for k, values in actuals[key].items()}
            expected_changes = {
                k: [v - b for v, b in zip(values, reference["cases"][base_key]["outputs"][k])]
                for k, values in reference["cases"][key]["outputs"].items()}
            checks = compare(changes, expected_changes, key + "/delta")
            cases[key]["delta_checks"] = checks
            cases[key]["ok"] &= all(c["ok"] for c in checks)
    checks = [c for case in cases.values() for c in case["checks"] + case.get("delta_checks", [])]
    return {"ok": all(c["ok"] for c in checks), "cases": cases,
            "case_count": len(cases), "check_count": len(checks),
            "failed_checks": sum(not c["ok"] for c in checks),
            "max_absolute_error": max(c["absolute_error"] for c in checks),
            "tolerances": {"relative": REL_TOL, "absolute": ABS_TOL},
            "oracle": reference["oracle"], "catalog_digest": reference["catalog_digest"]}
