"""Scenario interrogation, validated patches, exploration, and experiment journal."""

import copy
import datetime
import math
import random
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .errors import BurrError, require
from .expressions import dependencies
from .model import Workspace
from .storage import atomic_write, identifier, json_text, merge, read_yaml, yaml_text
from .values import number, series


def coherent(workspace):
    results, diagnostics = [], []
    for scenario in ["base", *workspace.scenarios()]:
        try:
            model = workspace.model(scenario)
            validation = model.validate()
            checks = model.check()
            if model.params.get("valuation"):
                model.value()
            results.append({"scenario": scenario, "ok": True, "validation": validation, "checks": checks,
                            "warnings": [d.to_dict() for d in model.warnings]})
        except BurrError as exc:
            for d in exc.diagnostics:
                d.where["scenario"] = scenario
            diagnostics.extend(exc.diagnostics)
    if diagnostics:
        raise BurrError.many(diagnostics)
    return {"ok": True, "scenarios": results}


def differences(a, b):
    changes = []
    for section in ("bindings", "valuation"):
        for key in sorted(set(a.get(section, {})) | set(b.get(section, {}))):
            if json_text(a.get(section, {}).get(key)) != json_text(b.get(section, {}).get(key)):
                changes.append((section, key))
    return changes


def attribution(workspace, a, b, scenario="base"):
    base = workspace.model(params=a).value()["per_share"]
    target = workspace.model(params=b).value()["per_share"]
    rows = []
    for section, key in differences(a, b):
        trial = copy.deepcopy(a)
        trial.setdefault(section, {})[key] = copy.deepcopy(b[section][key])
        delta = workspace.model(params=trial).value()["per_share"] - base
        form = b[section][key]
        metadata = {k: v for k, v in form.items() if k in {"rationale", "source", "confidence", "as_of", "unit"}} if isinstance(form, dict) else {}
        rows.append({"key": key, "section": section, "delta": delta, "metadata": metadata})
    rows.sort(key=lambda r: (-abs(r["delta"]), r["section"], r["key"]))
    return base, target, rows, (target - base) - sum(r["delta"] for r in rows)


def explain(workspace, frm, to):
    a, b = workspace.model(frm).params, workspace.model(to).params
    base, target, rows, residual = attribution(workspace, a, b)
    return {"ok": True, "from": frm, "to": to, "gap": target - base,
            "attribution": rows, "interactions": residual}


def normalize_patch(envelope, *, durable=False):
    require(isinstance(envelope, dict), "patch_conflict", "patch must be a mapping")
    op = envelope.get("op")
    if op is None:
        require(not durable and set(envelope) <= {"bindings", "valuation", "thesis"}, "patch_conflict", "durable patches require an operation envelope")
        require(any(k in envelope for k in ("bindings", "valuation")), "patch_conflict", "empty patch")
        patch = {k: v for k, v in envelope.items() if k in {"bindings", "valuation"}}
    elif op == "add_scenario":
        require(set(envelope) <= {"op", "name", "thesis", "bindings", "valuation"}, "patch_conflict", "unsupported scenario envelope fields")
        identifier(envelope.get("name"))
        require(envelope["name"] != "base", "patch_conflict", "base is reserved")
        require(isinstance(envelope.get("thesis"), str) and envelope["thesis"].strip(), "patch_conflict", "scenario requires a written thesis")
        patch = {k: v for k, v in envelope.items() if k in {"bindings", "valuation"}}
    elif op in {"set_binding", "set_valuation"}:
        section = "bindings" if op == "set_binding" else "valuation"
        require(set(envelope) <= {"op", "name", "value", section, "thesis"}, "patch_conflict", "unsupported set envelope fields")
        if section in envelope:
            require("name" not in envelope and "value" not in envelope, "patch_conflict", "use either name/value or a section mapping")
            patch = {section: envelope[section]}
        else:
            identifier(envelope.get("name"))
            require("value" in envelope, "patch_conflict", "set operation requires value")
            patch = {section: {envelope["name"]: envelope["value"]}}
    elif op in {"add_check", "fork_template"}:
        return {}
    else:
        raise BurrError("patch_conflict", f"unknown patch operation {op!r}")
    require(all(isinstance(v, dict) for v in patch.values()), "patch_conflict", "patch bindings and valuation must be mappings")
    return patch


def prepare(workspace, envelope, scenario="base", *, durable=False):
    patch = normalize_patch(envelope, durable=durable)
    staged = copy.deepcopy(workspace)
    op = envelope.get("op")
    files = {}
    if op == "add_scenario":
        name = envelope["name"]
        if durable:
            require(name not in workspace.scenarios(), "patch_conflict", f"scenario {name!r} already exists")
            staged.params.setdefault("scenarios", {})[name] = {"thesis": envelope["thesis"], **patch}
            trial = staged.model(name)
            files[workspace.params_file] = yaml_text(staged.params)
        else:
            trial = staged.model(params=merge(workspace.params, patch))
    elif op in {"add_check", "fork_template"}:
        allowed = {"op", "check", "thesis"} if op == "add_check" else {"op", "name", "template", "lines", "parameters", "checks", "doc", "thesis"}
        require(set(envelope) <= allowed, "patch_conflict", "unsupported template envelope fields")
        source_name = envelope.get("template", workspace.params["template"])
        resolved = workspace.template(source_name)
        name = source_name if op == "add_check" else identifier(envelope.get("name"))
        raw = {**resolved, "parameters": list(resolved["parameters"].values()), "template": name}
        if op == "add_check":
            require(isinstance(envelope.get("check"), str), "patch_conflict", "add_check requires check")
            raw["checks"] = list(dict.fromkeys(raw["checks"] + [envelope["check"]]))
        else:
            require(not durable or not (workspace.root / "templates" / f"{name}.yaml").exists(), "patch_conflict", f"template {name!r} already exists")
            require(isinstance(envelope.get("lines", {}), dict), "patch_conflict", "line edits must be a mapping")
            raw["lines"].update(envelope.get("lines", {}))
            if "parameters" in envelope:
                edits = envelope["parameters"]
                require(isinstance(edits, list), "patch_conflict", "parameter edits must be a list")
                params = resolved["parameters"]
                for edit in edits:
                    edit = {"name": edit} if isinstance(edit, str) else edit
                    require(isinstance(edit, dict) and "name" in edit, "patch_conflict", "invalid parameter edit")
                    params[edit["name"]] = edit
                raw["parameters"] = list(params.values())
            if "checks" in envelope:
                raw["checks"] = envelope["checks"]
            raw["doc"] = envelope.get("doc", raw["doc"])
            staged.params["template"] = name
            files[workspace.params_file] = yaml_text(staged.params)
        staged.template_overrides[name] = raw
        files[workspace.root / "templates" / f"{name}.yaml"] = yaml_text(raw)
        trial = staged.model(scenario)
    else:
        if durable and scenario != "base":
            require(scenario in workspace.scenarios(), "unknown_scenario", f"unknown scenario {scenario!r}")
            original = workspace.scenarios()[scenario]
            updated = merge(original, patch)
            if scenario in staged.params.get("scenarios", {}):
                staged.params["scenarios"][scenario] = updated
                files[workspace.params_file] = yaml_text(staged.params)
            else:
                # Make the proposed external scenario visible to staged validation.
                staged.params.setdefault("scenarios", {})[scenario] = updated
                staged._external_scenario_override = scenario
                files[workspace.company / "scenarios" / f"{scenario}.yaml"] = yaml_text(updated)
            trial = staged.model(scenario)
        elif durable:
            staged.params = merge(staged.params, patch)
            trial = staged.model(scenario)
            files[workspace.params_file] = yaml_text(staged.params)
        else:
            trial_params = merge(workspace.model(scenario).params, patch)
            staged.params = trial_params
            trial = staged.model(params=trial_params)
    trial.validate()
    trial.run()
    if trial.params.get("valuation"):
        trial.value()
    if durable:
        coherent(staged)
        # A shared check must also be valid for other companies using that logic.
        if op == "add_check":
            for params_path in sorted((workspace.root / "companies").glob("*/params.yaml")):
                if params_path == workspace.params_file:
                    continue
                other = Workspace(params_path.parent)
                other.template_overrides = staged.template_overrides
                coherent(other)
    return staged, trial, files


def try_patch(workspace, envelope, scenario="base"):
    staged, trial, _ = prepare(workspace, envelope, scenario)
    original = workspace.model(scenario)
    if envelope.get("op") in {"fork_template", "add_check"}:
        base, target = original.value()["per_share"], trial.value()["per_share"]
        rows = []
        for name in sorted(envelope.get("lines", {})):
            partial = copy.deepcopy(envelope)
            partial["lines"] = {name: envelope["lines"][name]}
            _, isolated, _ = prepare(workspace, partial, scenario)
            rows.append({"key": name, "section": "lines", "delta": isolated.value()["per_share"] - base})
        rows.sort(key=lambda r: (-abs(r["delta"]), r["key"]))
        residual = target - base - sum(r["delta"] for r in rows)
    else:
        base, target, rows, residual = attribution(workspace, original.params, trial.params)
    return {"ok": True, "base_per_share": base, "trial_per_share": target,
            "gap": target - base, "attribution": rows, "interactions": residual}


def commit_files(files):
    """Writer holds burr.lock; rollback all replacements if any write fails."""
    originals = {path: path.read_bytes() if path.exists() else None for path in files}
    written = []
    try:
        for path, content in files.items():
            atomic_write(path, content)
            written.append(path)
    except BaseException:
        for path in reversed(written):
            if originals[path] is None:
                path.unlink()
            else:
                atomic_write(path, originals[path])
        raise


def apply_patch(workspace, envelope, scenario="base"):
    _, trial, files = prepare(workspace, envelope, scenario, durable=True)
    commit_files(files)
    return {"ok": True, "op": envelope["op"], "scenario": trial.scenario,
            "files": sorted(workspace.relative(path) for path in files)}


def graph(model, formulas=False):
    nodes = []
    for name in sorted(set(model.inputs) | set(model.expressions)):
        node = {"id": name, "kind": "line" if name in model.expressions else "binding"}
        if formulas and name in model.expressions:
            node["formula"] = model.template["lines"][name]
        nodes.append(node)
    edges = [{"from": dep, "to": name, "lagged": delayed}
             for name, expr in sorted(model.expressions.items()) for dep, delayed in sorted(dependencies(expr))]
    return {"ok": True, "nodes": nodes, "edges": edges}


def trace(model, line):
    model.run()
    require(line in model.expressions or line in model.inputs, "unknown_name", f"unknown line {line!r}")

    def visit(name, ancestors):
        if name in model.inputs:
            form = model.params.get("bindings", {}).get(name, model.workspace.world.get(name))
            return {"name": name, "kind": "binding", "values": series(model.inputs[name], len(model.years)),
                    "form": form, "rationale": form.get("rationale", "") if isinstance(form, dict) else ""}
        node = {"name": name, "kind": "line", "formula": model.template["lines"][name], "values": model.results[name]}
        if name in ancestors:
            node["recurrence"] = True
            return node
        node["dependencies"] = [{**visit(dep, ancestors | {name}), "lagged": lagged}
                                for dep, lagged in sorted(dependencies(model.expressions[name]))]
        return node

    return {"ok": True, "periods": model.years, "tree": visit(line, set())}


def axis(spec, model):
    try:
        key, span = spec.split("=")
        lo, hi, step = map(Decimal, span.split(":"))
        require(all(v.is_finite() for v in (lo, hi, step)) and step > 0 and hi >= lo,
                "usage_error", "sensitivity needs finite lo <= hi and positive step", exit_code=2)
        count = int((hi - lo) / step) + 1
        require(count <= 1000, "usage_error", "sensitivity axis exceeds 1000 points", exit_code=2)
        values = [float(lo + step * i) for i in range(count)]
    except (ValueError, InvalidOperation) as exc:
        raise BurrError("usage_error", "axis syntax: key=lo:hi:step", exit_code=2) from exc
    if "." in key:
        section, name = key.split(".", 1)
    else:
        name = key
        choices = [s for s in ("bindings", "valuation") if name in model.params.get(s, {})]
        require(len(choices) == 1, "unknown_name", f"unknown or ambiguous sensitivity key {key!r}; qualify with bindings. or valuation.")
        section = choices[0]
    require(section in {"bindings", "valuation"} and name in model.params.get(section, {}) and name != "fcf",
            "unknown_name", f"unknown numeric sensitivity key {key!r}")
    return section, name, values


def sensitivity(workspace, scenario, x, y):
    model = workspace.model(scenario)
    sx, kx, xs = axis(x, model)
    sy, ky, ys = axis(y, model)
    require((sx, kx) != (sy, ky), "usage_error", "sensitivity axes must differ", exit_code=2)
    require(len(xs) * len(ys) <= 10000, "usage_error", "sensitivity grid exceeds 10000 points", exit_code=2)
    rows = []
    for yv in ys:
        row = []
        for xv in xs:
            params = copy.deepcopy(model.params)
            params[sx][kx], params[sy][ky] = xv, yv
            row.append(workspace.model(params=params).value()["per_share"])
        rows.append(row)
    return {"ok": True, "x": {"key": f"{sx}.{kx}", "values": xs}, "y": {"key": f"{sy}.{ky}", "values": ys}, "grid": rows}


def monte_carlo(workspace, scenario, draws, seed, full=False):
    require(0 < draws <= 1000000, "usage_error", "draws must be between 1 and 1000000", exit_code=2)
    rng, values = random.Random(seed), []
    for i in range(draws):
        try:
            values.append(workspace.model(scenario, rng=rng).value()["per_share"])
        except BurrError as exc:
            for diagnostic in exc.diagnostics:
                diagnostic.where["draw"] = i + 1
            raise
    ordered = sorted(values)

    def quantile(q):
        index = q * (len(ordered) - 1)
        lo, hi = math.floor(index), math.ceil(index)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)

    low, high = ordered[0], ordered[-1]
    bins = 1 if low == high else min(20, max(1, int(math.sqrt(draws))))
    counts = [0] * bins
    for value in values:
        index = 0 if low == high else min(bins - 1, int((value - low) / (high - low) * bins))
        counts[index] += 1
    histogram = [{"lo": low + (high - low) * i / bins, "hi": low + (high - low) * (i + 1) / bins,
                  "count": count} for i, count in enumerate(counts)]
    result = {"ok": True, "seed": seed, "n": draws, "percentiles": {f"p{p}": quantile(p / 100) for p in (5, 25, 50, 75, 95)},
              "histogram": histogram}
    if full:
        result["draws"] = values
    return result


def touched(patch):
    keys = set()
    for section in ("bindings", "valuation", "lines"):
        if isinstance(patch.get(section), dict):
            keys.update(patch[section])
    if patch.get("op") in {"set_binding", "set_valuation"} and "name" in patch:
        keys.add(patch["name"])
    return keys


def journal(workspace, *, param=None, tag=None, stale=False):
    rows, fingerprints = [], {}
    for path in sorted((workspace.company / "experiments").glob("exp-*.yaml")):
        entry = read_yaml(path)
        require(entry.get("id") == path.stem and "patch" in entry and "results" in entry, "eval_error", "malformed experiment entry", file=workspace.relative(path))
        scenario = entry.get("scenario", "base")
        if scenario not in fingerprints:
            try:
                fingerprints[scenario] = workspace.fingerprint(scenario)
            except BurrError:
                fingerprints[scenario] = None
        entry["stale"] = entry.get("fingerprint") != fingerprints[scenario]
        if param and param not in touched(entry["patch"]):
            continue
        if tag and tag not in entry.get("tags", []):
            continue
        if stale and not entry["stale"]:
            continue
        rows.append(entry)
    return {"ok": True, "entries": rows}


def record(workspace, envelope, scenario, question, finding, tags):
    require(question.strip() and finding.strip(), "usage_error", "question and finding must not be blank", exit_code=2)
    results = try_patch(workspace, envelope, scenario)
    existing = [int(p.stem[4:]) for p in (workspace.company / "experiments").glob("exp-*.yaml") if p.stem[4:].isdigit()]
    exp_id = f"exp-{max(existing, default=0) + 1:03d}"
    entry = {"id": exp_id, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
             "question": question, "scenario": scenario, "patch": envelope, "results": results,
             "finding": finding, "tags": sorted(set(t.strip() for t in tags.split(",") if t.strip())),
             "fingerprint": workspace.fingerprint(scenario)}
    # Flag explicit 'gap: N' / 'per_share: N' assertions, avoiding guesses about prose.
    warnings = []
    for key, claim in re.findall(r"\b(gap|trial_per_share|base_per_share)\s*[:=]\s*(-?\d+(?:\.\d+)?)", finding):
        if not math.isclose(float(claim), results[key], rel_tol=0.005, abs_tol=0.01):
            warnings.append({"code": "finding_mismatch", "severity": "warning", "message": f"finding claims {key}={claim}; attached result is {results[key]:g}"})
    if warnings:
        entry["warnings"] = warnings
    atomic_write(workspace.company / "experiments" / f"{exp_id}.yaml", yaml_text(entry), exclusive=True)
    return {"ok": True, "experiment": entry}


def replay(workspace, exp_id):
    require(re.fullmatch(r"exp-\d{3,}", exp_id), "usage_error", "experiment id must be exp-NNN", exit_code=2)
    entry = read_yaml(workspace.company / "experiments" / f"{exp_id}.yaml")
    current = try_patch(workspace, entry["patch"], entry.get("scenario", "base"))
    prior = entry["results"]
    keys = ("base_per_share", "trial_per_share", "gap")
    holds = all(math.isclose(prior[k], current[k], rel_tol=1e-9, abs_tol=1e-9) for k in keys)
    before = {(r.get("section", "bindings"), r["key"]): r["delta"] for r in prior["attribution"]}
    after = {(r.get("section", "bindings"), r["key"]): r["delta"] for r in current["attribution"]}
    holds = holds and before.keys() == after.keys() and all(math.isclose(before[k], after[k], rel_tol=1e-9, abs_tol=1e-9) for k in before)
    return {"ok": True, "id": exp_id, "status": "HOLDS" if holds else "DRIFTED", "recorded": prior, "current": current}


def show(workspace, scenario, binding):
    model = workspace.model(scenario)
    section = "bindings"
    if binding.startswith("valuation."):
        section, binding = binding.split(".", 1)
    require(binding in model.params.get(section, {}), "unknown_name", f"unknown {section} key {binding!r}")
    overrides = [{"scenario": name, "thesis": patch["thesis"], "form": patch[section][binding]}
                 for name, patch in workspace.scenarios().items() if binding in patch.get(section, {})]
    return {"ok": True, "binding": binding, "section": section, "form": model.params[section][binding],
            "value": (model.inputs if section == "bindings" else model.valuation).get(binding),
            "scenarios": overrides, "experiments": journal(workspace, param=binding)["entries"]}


def calibrate(workspace, scenario):
    model = workspace.model(scenario)
    facts = {(r["period"], r["line"]): r["value"] for r in workspace.actuals}
    year = model.params["base_year"]
    proposed, derived, ratios = {}, [], []
    by_line = {}
    for row in workspace.actuals:
        by_line.setdefault(row["line"], []).append(row)
    for line, observations in sorted(by_line.items()):
        for before, after in zip(observations, observations[1:]):
            if before["value"] and after["period"] == before["period"] + 1:
                derived.append({"line": line, "period": after["period"], "growth": after["value"] / before["value"] - 1})
    import ast

    def linear(node, parameter, period):
        """Recover a*p+b from facts alone; refuse nonlinear/unobserved terms."""
        if isinstance(node, ast.Constant):
            return 0.0, float(node.value)
        if isinstance(node, ast.Name):
            if node.id == parameter:
                return 1.0, 0.0
            if (period, node.id) in facts:
                return 0.0, facts[period, node.id]
            raise ValueError("unobserved driver")
        if isinstance(node, ast.UnaryOp):
            a, b = linear(node.operand, parameter, period)
            return -a, -b
        if isinstance(node, ast.BinOp):
            a, b = linear(node.left, parameter, period)
            c, d = linear(node.right, parameter, period)
            if isinstance(node.op, ast.Add):
                return a + c, b + d
            if isinstance(node.op, ast.Sub):
                return a - c, b - d
            if isinstance(node.op, ast.Mult) and not a * c:
                return a * d + b * c, b * d
            if isinstance(node.op, ast.Div) and c == 0 and d:
                return a / d, b / d
        raise ValueError("not a linear historical equation")

    for name in sorted(model.template["parameters"]):
        value = None
        if name.endswith("0") and (year, name[:-1]) in facts:
            value = facts[year, name[:-1]]
        # Invert direct reported driver equations; no business-specific ratio names.
        for line, expression in model.expressions.items():
            if (year, line) not in facts:
                continue
            if isinstance(expression, ast.Call) and expression.func.id == "grow" and isinstance(expression.args[1], ast.Name) and expression.args[1].id == name:
                if (year - 1, line) in facts and facts[year - 1, line]:
                    value = facts[year, line] / facts[year - 1, line] - 1
            for historical_year in sorted({r["period"] for r in workspace.actuals}):
                if (historical_year, line) not in facts:
                    continue
                try:
                    coefficient, intercept = linear(expression, name, historical_year)
                    if coefficient:
                        observed = number((facts[historical_year, line] - intercept) / coefficient)
                        ratios.append({"parameter": name, "line": line, "period": historical_year, "value": observed})
                        if historical_year == year:
                            value = observed
                except ValueError:
                    continue
        if value is not None:
            original = model.params["bindings"].get(name)
            proposal = {"value": value, "source": "derived from actuals", "as_of": str(year)}
            if isinstance(original, dict):
                for meta in ("rationale", "unit", "confidence"):
                    if meta in original:
                        proposal[meta] = original[meta]
            proposed[name] = proposal
    return {"ok": True, "patch": {"op": "set_binding", "bindings": proposed}, "historical_growth": derived, "historical_ratios": ratios}
