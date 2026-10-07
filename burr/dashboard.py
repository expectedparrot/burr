"""Portable, offline scenario dashboards with an explicit browser experiment log."""

import ast
import json
import math
import re
from html import escape
from pathlib import Path

from .errors import require
from .storage import atomic_write


def expression(node):
    """Serialize the already validated closed grammar, never executable source."""
    if isinstance(node, ast.Constant):
        return ["constant", node.value]
    if isinstance(node, ast.Name):
        return ["name", node.id]
    if isinstance(node, ast.UnaryOp):
        return ["neg", expression(node.operand)]
    if isinstance(node, ast.BinOp):
        return [type(node.op).__name__, expression(node.left), expression(node.right)]
    if isinstance(node, ast.Compare):
        return [type(node.ops[0]).__name__, expression(node.left), expression(node.comparators[0])]
    return [node.func.id, *map(expression, node.args)]


def dashboard_data(workspace, scenario="base", sliders=(), title=None):
    model = workspace.model(scenario)
    facts = model.validate()
    baseline = {"lines": model.run(), "value": model.value()}
    locked = {r["key"] for r in facts if "opinion" in r}
    controls = []
    for section, values in (("bindings", model.inputs), ("valuation", model.valuation)):
        for name, value in sorted(values.items()):
            if section == "valuation" and name in model.valuation_refs:
                continue  # Edit the source assumption, never a detached computed copy.
            if section == "bindings" and (name not in model.params["bindings"] or name in locked):
                continue
            unit = model.units.get(name) if section == "bindings" else (
                "ratio" if name in {"wacc", "terminal_growth"} else "count" if name == "shares" else None)
            form = model.params[section].get(name, {})
            metadata = {k: form[k] for k in ("rationale", "source", "confidence", "as_of") if isinstance(form, dict) and k in form}
            # Operating profiles are explored as a business assumption over the
            # horizon. Retain the old annual controls for precise edits/replay.
            if section == "bindings" and isinstance(value, list):
                span = max(max(map(abs, value)) * .5, .05 if unit in {"ratio", "per_period_ratio"} else 1)
                for transform, suffix, base in (("shift", "", 0), ("level", "~level", value[-1]),
                                                ("target", "~target", value[-1])):
                    controls.append({"key": f"{section}.{name}{suffix}", "section": section, "name": name,
                                     "index": None, "year": None, "transform": transform, "profile": value,
                                     "base": base, "min": base-span, "max": base+span, "step": span/100,
                                     "unit": unit, "metadata": metadata, "enabled": False})
            for index, base in enumerate(value if isinstance(value, list) else [value]):
                year = model.years[index] if isinstance(value, list) else None
                key = f"{section}.{name}" + (f"@{year}" if year is not None else "")
                span = max(abs(base) * .5, .05 if unit in {"ratio", "per_period_ratio"} else 1)
                controls.append({"key": key, "section": section, "name": name,
                                 "index": index if year is not None else None, "year": year,
                                 "transform": "annual" if year is not None else "scalar",
                                 "base": base, "min": base - span, "max": base + span,
                                 "step": span / 100, "unit": unit, "metadata": metadata, "enabled": False})
    by_key = {c["key"]: c for c in controls}
    for spec in sliders:
        try:
            key, bounds = spec.split("=", 1)
            low, high, step = map(float, bounds.split(":"))
        except ValueError:
            require(False, "usage_error", "slider must be NAME=MIN:MAX:STEP (ratios use decimals)", exit_code=2)
        if not key.startswith(("bindings.", "valuation.")):
            key = "bindings." + key
        require(key in by_key, "usage_error", f"not an editable dashboard input: {key}", exit_code=2)
        control = by_key[key]
        require(all(math.isfinite(v) for v in (low, high, step)) and low < high and 0 < step <= high - low
                and low <= control["base"] <= high, "usage_error",
                f"invalid slider bounds for {key}; range must contain its saved value", exit_code=2)
        control.update(min=low, max=high, step=step, enabled=True)
    groups = {}
    for control in controls:
        if control["enabled"]:
            groups.setdefault((control["section"], control["name"]), []).append(control)
    for group in groups.values():
        require(len(group) == 1 or all(c["transform"] == "annual" for c in group), "usage_error",
                "choose one whole-forecast slider or individual years for each assumption", exit_code=2)
    return {"ok": True, "schema": "burr-dashboard-1", "entity": model.entity,
            "title": title or f"{model.entity.replace('_', ' ').title()} · Decision dashboard",
            "scenario": scenario, "fingerprint": workspace.fingerprint(scenario), "years": model.years,
            "inputs": model.inputs, "valuation": model.valuation, "fcf": model.params["valuation"]["fcf"],
            **({"valuation_refs": model.valuation_refs} if model.valuation_refs else {}),
            "expressions": {k: expression(v) for k, v in model.expressions.items()}, "order": model.order,
            "checks": [{"source": s, "expression": expression(n)} for s, n in model.checks],
            "units": model.units, "controls": controls, "baseline": baseline,
            "history": {key: [dict(row) for row in workspace.actuals
                               if row["line"] == key and row["period"] < model.years[0]]
                        for key in model.order},
            "history_source": workspace.relative(workspace.company / "actuals.csv"),
            "locked": sorted(locked)}


def emit_dashboard(workspace, path, *, scenario="base", sliders=(), title=None):
    path = Path(path)
    require(path.suffix.lower() == ".html", "usage_error", "dashboard output must end in .html", exit_code=2)
    data = dashboard_data(workspace, scenario, sliders, title)
    # Escape script terminators and HTML metacharacters in all embedded metadata.
    payload = json.dumps(data, allow_nan=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    assets = Path(__file__).with_name("dashboard_assets")
    parts = {"TITLE": escape(data["title"]), "DATA": payload,
             "ENGINE": (assets / "engine.js").read_text(), "UI": (assets / "ui.js").read_text()}
    html = re.sub(r"\{\{(TITLE|DATA|ENGINE|UI)\}\}", lambda m: parts[m[1]], (assets / "page.html").read_text())
    atomic_write(path, html)
    return {"ok": True, "output": str(path), "fingerprint": data["fingerprint"], "controls": len(data["controls"])}
