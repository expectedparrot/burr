"""Workspace loading, validation, evaluation, and valuation."""

import ast
import copy
import csv
import re
from pathlib import Path

from . import ENGINE_VERSION, SCHEMA_VERSION
from .errors import BurrError, Diagnostic, require
from .expressions import COMPARE, Evaluator, dependencies, infer_unit, parse, topological
from .storage import IDENTIFIER, digest, identifier, merge, read_yaml
from .values import UNITS, number, periods, resolve, series


def version_tuple(value):
    require(isinstance(value, (str, int, float)) and re.fullmatch(r"\d+(?:\.\d+){0,2}", str(value)),
            "version_mismatch", f"invalid version {value!r}")
    parts = tuple(map(int, str(value).split(".")))
    return parts + (0,) * (3 - len(parts))


def find_workspace(company):
    path = Path(company)
    if path.is_file():
        require(path.name == "params.yaml", "usage_error", "company file must be params.yaml", exit_code=2)
        path = path.parent
    candidates = [path.resolve()]
    for ancestor in [Path.cwd(), *Path.cwd().parents]:
        if (ancestor / "burr.lock").is_file():
            candidates.append(ancestor / "companies" / company)
            break
    for candidate in candidates:
        if (candidate / "params.yaml").is_file():
            for root in [candidate, *candidate.parents]:
                if (root / "burr.lock").is_file():
                    require(candidate.resolve().parent == (root / "companies").resolve(),
                            "usage_error", "company must be directly inside workspace/companies", exit_code=2)
                    return root, candidate
    raise BurrError("usage_error", f"cannot locate workspace/company {company!r}", exit_code=2)


class Workspace:
    def __init__(self, company):
        self.root, self.company = find_workspace(company)
        self.params_file = self.company / "params.yaml"
        pin = read_yaml(self.root / "burr.lock")
        for key, supported in (("engine_version", ENGINE_VERSION), ("schema_version", SCHEMA_VERSION)):
            require(key in pin and version_tuple(pin[key]) <= version_tuple(supported),
                    "version_mismatch", f"workspace requires {key} {pin.get(key)}; installed {supported}",
                    file="burr.lock", hint="upgrade burr to the workspace's pinned version")
        self.params = read_yaml(self.params_file)
        self.world = read_yaml(self.root / "world.yaml") if (self.root / "world.yaml").exists() else {}
        if set(self.world) == {"series"}:
            self.world = self.world["series"]
        require(isinstance(self.world, dict), "eval_error", "world must be a mapping of named value forms")
        self.actuals = self._actuals()
        self.template_overrides = {}

    def relative(self, path):
        return str(Path(path).relative_to(self.root))

    def _actuals(self):
        path = self.company / "actuals.csv"
        try:
            with path.open(newline="") as stream:
                reader = csv.DictReader(stream)
                require(reader.fieldnames == ["period", "line", "value"], "usage_error",
                        "actuals.csv requires columns period,line,value", file=self.relative(path), exit_code=2)
                rows, seen = [], set()
                for row in reader:
                    require(None not in row and all(row.values()), "usage_error", "malformed actuals row", file=self.relative(path), exit_code=2)
                    period, value = int(row["period"]), number(float(row["value"]))
                    require(IDENTIFIER.fullmatch(row["line"]), "unknown_name", "invalid actuals line", file=self.relative(path), key=row["line"])
                    key = (period, row["line"])
                    require(key not in seen, "fact_mismatch", "duplicate actuals observation", file=self.relative(path), key=str(key))
                    seen.add(key)
                    rows.append({"period": period, "line": row["line"], "value": value})
                return sorted(rows, key=lambda r: (r["period"], r["line"]))
        except (OSError, ValueError, csv.Error) as exc:
            raise BurrError("usage_error", f"cannot read actuals: {exc}", file=self.relative(path), exit_code=2) from exc

    def template(self, name, chain=()):
        identifier(name)
        require(name not in chain, "circular_dependency", f"template inheritance cycle: {' → '.join((*chain, name))}")
        raw = copy.deepcopy(self.template_overrides[name]) if name in self.template_overrides else read_yaml(self.root / "templates" / f"{name}.yaml")
        path = f"templates/{name}.yaml"
        require(raw.get("template") == name, "unknown_name", "template id does not match filename", file=path)
        allowed = {"template", "doc", "extends", "parameters", "lines", "checks", "decompositions"}
        require(not set(raw) - allowed, "patch_conflict", "template contains unsupported fields", file=path)
        parameters = raw.get("parameters", [])
        require(isinstance(parameters, list), "eval_error", "parameters must be a list", file=path)
        own = {}
        for param in parameters:
            param = {"name": param} if isinstance(param, str) else param
            require(isinstance(param, dict) and set(param) <= {"name", "unit", "doc"},
                    "eval_error", "parameter declarations accept name, unit, doc only", file=path)
            key = identifier(param.get("name"))
            require(key not in own, "patch_conflict", "duplicate parameter", file=path, key=key)
            if "unit" in param:
                require(param["unit"] in UNITS, "unit_mismatch", "unknown parameter unit", file=path, key=key)
            own[key] = param
        lines = raw.get("lines", {})
        checks = raw.get("checks", [])
        require(isinstance(lines, dict) and isinstance(checks, list), "eval_error", "lines must be a mapping and checks a list", file=path)
        if "extends" in raw:
            parent = self.template(raw["extends"], (*chain, name))
            for key, param in own.items():
                require(key not in parent["parameters"] or parent["parameters"][key].get("unit") == param.get("unit", parent["parameters"][key].get("unit")),
                        "unit_mismatch", "inherited parameter unit cannot change", file=path, key=key)
            inherited = copy.deepcopy(parent["parameters"])
            for key, param in own.items():
                inherited[key] = {**inherited.get(key, {}), **param}
            own = inherited
            lines = {**parent["lines"], **lines}
            checks = list(dict.fromkeys(parent["checks"] + checks))
            decompositions = {**parent.get("decompositions", {}), **raw.get("decompositions", {})}
        else:
            decompositions = raw.get("decompositions", {})
        return {"template": name, "doc": raw.get("doc", ""), "parameters": own, "lines": lines,
                "checks": checks, "decompositions": decompositions}

    def scenarios(self):
        inline = self.params.get("scenarios", {})
        require(isinstance(inline, dict), "patch_conflict", "scenarios must be a mapping")
        result = copy.deepcopy(inline)
        for path in sorted((self.company / "scenarios").glob("*.yaml")):
            if path.stem == getattr(self, "_external_scenario_override", None):
                continue
            require(path.stem not in result, "patch_conflict", f"scenario {path.stem!r} defined inline and in a file")
            result[path.stem] = read_yaml(path)
        for name, patch in result.items():
            identifier(name)
            require(name != "base", "patch_conflict", "base is a reserved scenario name")
            require(isinstance(patch, dict) and isinstance(patch.get("thesis"), str) and patch["thesis"].strip(),
                    "patch_conflict", f"scenario {name!r} requires a thesis")
            require(set(patch) <= {"thesis", "bindings", "valuation", "op", "name"}, "patch_conflict", "scenarios may only override bindings and valuation")
            require(patch.get("op", "add_scenario") == "add_scenario" and patch.get("name", name) == name,
                    "patch_conflict", "scenario envelope must match its filename and add_scenario operation")
        return dict(sorted(result.items()))

    def model(self, scenario="base", *, params=None, rng=None, strict=False):
        document = copy.deepcopy(self.params if params is None else params)
        if scenario != "base":
            choices = self.scenarios()
            # In-memory patches may add an inline scenario.
            if params is not None:
                choices.update(params.get("scenarios", {}))
            require(scenario in choices, "unknown_scenario", f"unknown scenario {scenario!r}")
            patch = {k: v for k, v in choices[scenario].items() if k in {"bindings", "valuation"}}
            document = merge(document, patch)
        return Model(self, document, scenario, rng=rng, strict=strict)

    def fingerprint(self, scenario="base"):
        model = self.model(scenario)
        # Include resolved logic and environment so changes to either invalidate evidence.
        return digest({"params": model.params, "template": model.template, "actuals": self.actuals,
                       "world": self.world, "engine": ENGINE_VERSION, "schema": SCHEMA_VERSION})


class Model:
    def __init__(self, workspace, params, scenario, *, rng=None, strict=False):
        self.workspace, self.params, self.scenario = workspace, params, scenario
        self.file = workspace.relative(workspace.params_file)
        require(set(params) <= {"entity", "template", "periods", "base_year", "bindings", "valuation", "scenarios"},
                "patch_conflict", "params contains unsupported fields", file=self.file)
        self.entity = identifier(params.get("entity"))
        self.years = periods(params.get("periods"))
        require(isinstance(params.get("base_year"), int) and params["base_year"] == self.years[0] - 1,
                "eval_error", "base_year must immediately precede the forecast", file=self.file)
        self.template = workspace.template(params.get("template"))
        self.template_file = f"templates/{self.template['template']}.yaml"
        self.warnings = []
        self.inputs, self.units, self.expressions = {}, {}, {}
        bindings = params.get("bindings", {})
        require(isinstance(bindings, dict), "eval_error", "bindings must be a mapping", file=self.file)
        parameters, lines = self.template["parameters"], self.template["lines"]
        require(lines, "eval_error", "template must define at least one line", file=self.template_file)
        diagnostics = []

        def diag(code, message, key, *, warning=False, template=False, hint=None):
            d = Diagnostic(code, message, {"file": self.template_file if template else self.file, "key": key},
                           hint or "correct the referenced definition", "warning" if warning else "error")
            (self.warnings if warning else diagnostics).append(d)

        for name in set(parameters) | set(lines) | set(bindings) | set(workspace.world):
            if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
                diag("unknown_name", f"invalid identifier {name!r}", str(name))
        for name in sorted(set(parameters) & set(lines)):
            diag("patch_conflict", "parameters and lines share one namespace", name)
        for name in sorted(set(workspace.world) & (set(bindings) | set(lines))):
            diag("patch_conflict", "entity definitions cannot shadow world series", name)
        for name in sorted(set(parameters) - set(bindings) - set(workspace.world)):
            diag("unbound_parameter", f"missing binding for template parameter {name!r}", name, hint=f"add bindings.{name}")
        for name in sorted(set(bindings) - set(parameters)):
            diag("orphan_binding", f"binding {name!r} is not a template parameter", name)
        for name, expression in sorted(lines.items()):
            try:
                self.expressions[name] = parse(expression)
            except BurrError as exc:
                for d in exc.diagnostics:
                    d.where = {"file": self.template_file, "key": name}
                diagnostics.extend(exc.diagnostics)
        referenced = {n for expr in self.expressions.values() for n, _ in dependencies(expr)}
        available = set(parameters) | set(lines) | set(workspace.world)
        for name in sorted(referenced - available):
            diag("unknown_name", f"unknown expression name {name!r}", name, template=True)
        for name in sorted(set(parameters) - referenced):
            diag("unused_parameter", f"parameter {name!r} is never used by a line", name, template=True)
        for name, form in sorted({**workspace.world, **bindings}.items()):
            if name not in parameters and name not in referenced:
                continue
            try:
                self.inputs[name] = resolve(form, self.years, rng)
                unit = parameters.get(name, {}).get("unit")
                binding_unit = form.get("unit") if isinstance(form, dict) else None
                require(not (unit and binding_unit and unit != binding_unit), "unit_mismatch", "binding unit differs from template declaration")
                self.units[name] = unit or binding_unit
                if self.units[name] in {"ratio", "per_period_ratio"} and any(abs(v) > 1.5 for v in series(self.inputs[name], len(self.years))):
                    diag("ratio_magnitude", "ratio magnitude exceeds 1.5; check percent vs basis points", name, warning=True)
                if strict and self.units[name] is None:
                    diag("missing_unit", "parameter has no declared unit", name, warning=True)
            except BurrError as exc:
                for d in exc.diagnostics:
                    d.where = {"file": self.file if name in bindings else "world.yaml", "key": name}
                diagnostics.extend(exc.diagnostics)
        self.checks = []
        for source in self.template["checks"]:
            try:
                node = parse(source, check=True)
                require(not {n for n, _ in dependencies(node)} - available, "unknown_name", f"unknown name in check {source!r}")
                self.checks.append((source, node))
            except BurrError as exc:
                for d in exc.diagnostics:
                    d.where = {"file": self.template_file, "key": "checks"}
                diagnostics.extend(exc.diagnostics)
        if diagnostics:
            raise BurrError.many(diagnostics)
        try:
            self.order = topological(self.expressions)
        except BurrError as exc:
            exc.diagnostics[0].where["file"] = self.template_file
            raise
        # Iterate through lag-connected units to a fixed point.
        for _ in range(len(lines) + 1):
            changed = False
            for name in self.order:
                try:
                    unit = infer_unit(self.expressions[name], self.units.get)
                except BurrError as exc:
                    exc.diagnostics[0].where = {"file": self.template_file, "key": name}
                    raise
                if unit is not None and self.units.get(name) != unit:
                    self.units[name] = unit
                    changed = True
            if not changed:
                break
        self.valuation = {}
        raw_valuation = params.get("valuation", {})
        require(isinstance(raw_valuation, dict), "eval_error", "valuation must be a mapping", file=self.file)
        require(not set(raw_valuation) - {"fcf", "wacc", "terminal_growth", "net_cash", "shares"},
                "orphan_binding", "unknown valuation parameter", file=self.file)
        for name, form in sorted(raw_valuation.items()):
            if name == "fcf":
                require(form in lines, "unknown_name", f"unknown FCF line {form!r}", file=self.file, key="valuation.fcf")
                continue
            try:
                self.valuation[name] = resolve(form, self.years, rng)
                unit = form.get("unit") if isinstance(form, dict) else None
                if name in {"wacc", "terminal_growth"}:
                    require(unit is None or unit in {"ratio", "per_period_ratio"}, "unit_mismatch", f"{name} requires a ratio unit")
            except BurrError as exc:
                exc.diagnostics[0].where = {"file": self.file, "key": f"valuation.{name}"}
                raise
        self.evaluator = Evaluator(self.expressions, self.inputs, len(self.years), self.order)
        self.results = None

    def validate(self):
        rows, diagnostics = [], []
        facts = {(r["period"], r["line"]): r["value"] for r in self.workspace.actuals}
        for name in sorted(self.params["bindings"]):
            key = (self.params["base_year"], name[:-1])
            if not name.endswith("0") or key not in facts:
                continue
            form = self.params["bindings"][name]
            tolerance = number(form.get("tolerance", 0.005)) if isinstance(form, dict) else 0.005
            values = series(self.inputs[name], len(self.years))
            actual = facts[key]
            ok = all(abs(v - actual) <= max(abs(actual) * tolerance, 1e-12) for v in values)
            row = {"key": name, "period": key[0], "opinion": values[0], "actual": actual, "tolerance": tolerance, "ok": ok}
            rows.append(row)
            if not ok:
                diagnostics.append(Diagnostic("fact_mismatch", f"{name}={values[0]:g} differs from reported {actual:g}",
                                              {"file": self.file, "key": name}, "align the base-year binding with actuals"))
        decompositions = self.template.get("decompositions", {})
        require(isinstance(decompositions, dict), "eval_error", "decompositions must map totals to lists of segment lines")
        for total, parts in sorted(decompositions.items()):
            require(isinstance(parts, list) and parts and all(isinstance(p, str) for p in parts), "eval_error", "decomposition requires segment names")
            for year in sorted({r["period"] for r in self.workspace.actuals}):
                if (year, total) not in facts:
                    continue
                if not any((year, p) in facts for p in parts):
                    continue
                missing = [p for p in parts if (year, p) not in facts]
                subtotal = sum(facts.get((year, p), 0) for p in parts)
                actual = facts[year, total]
                ok = not missing and abs(subtotal - actual) <= max(abs(actual) * 0.01, 1e-12)
                rows.append({"key": total, "period": year, "segments": parts, "sum": subtotal, "actual": actual, "ok": ok})
                if not ok:
                    diagnostics.append(Diagnostic("fact_mismatch", f"{year} {total}: segment sum {subtotal:g}, reported {actual:g}; missing {missing}",
                                                  {"file": "actuals.csv", "key": total}, "verify the reported decomposition"))
        if diagnostics:
            raise BurrError.many(diagnostics)
        return rows

    def run(self, *, force_period=False):
        if self.results is None:
            try:
                self.results = self.evaluator.evaluate(force_period=force_period)
            except BurrError as exc:
                exc.diagnostics[0].where["file"] = self.template_file
                raise
            self.check()
        return self.results

    def check(self):
        if self.results is None:
            self.results = self.evaluator.evaluate()
        rows = []
        for source, node in self.checks:
            for t, year in enumerate(self.years):
                try:
                    left, right = self.evaluator.at(node.left, t), self.evaluator.at(node.comparators[0], t)
                except (ArithmeticError, ValueError, RecursionError) as exc:
                    raise BurrError("eval_error", f"check {source}: {exc}", file=self.template_file, key="checks") from exc
                ok = COMPARE[type(node.ops[0])](left, right)
                rows.append({"check": source, "period": year, "left": left, "right": right, "ok": ok})
                require(ok, "check_failed", f"check {source!r} failed in {year}: left={left:g}, right={right:g}",
                        file=self.template_file, key="checks", hint="revise assumptions or explicitly fork the template")
        return rows

    def rows(self):
        return [{"entity": self.entity, "scenario": self.scenario, "period": year, "line": name,
                 "value": values[t], "provenance": f"templates/{self.template['template']}.yaml:lines.{name}"}
                for name, values in sorted(self.run().items()) for t, year in enumerate(self.years)]

    def value(self, exit_multiple=None):
        results = self.run()
        config = self.params.get("valuation", {})
        require("fcf" in config and "wacc" in self.valuation and "shares" in self.valuation,
                "unbound_parameter", "valuation requires fcf, wacc, and shares", file=self.file, key="valuation")
        n = len(self.years)
        wacc = series(self.valuation["wacc"], n)
        growth = series(self.valuation.get("terminal_growth", 0.0), n)[-1]
        shares = series(self.valuation["shares"], n)[0]
        cash = series(self.valuation.get("net_cash", 0.0), n)[0]
        require(shares > 0, "eval_error", "shares must be positive", file=self.file, key="valuation.shares")
        require(all(w > -1 for w in wacc), "eval_error", "WACC must exceed -1", file=self.file, key="valuation.wacc")
        discount, present = 1.0, 0.0
        for fcf, rate in zip(results[config["fcf"]], wacc):
            discount *= 1.0 + rate
            present += fcf / discount
        if exit_multiple is None:
            require(wacc[-1] > growth and growth > -1, "eval_error", "terminal WACC must exceed terminal growth, and growth must exceed -1",
                    file=self.file, key="valuation.terminal_growth")
            terminal = results[config["fcf"]][-1] * (1.0 + growth) / (wacc[-1] - growth)
        else:
            require("ebitda" in results and number(exit_multiple) >= 0, "eval_error", "exit multiple requires an ebitda line and a nonnegative multiple")
            terminal = results["ebitda"][-1] * exit_multiple
        terminal_pv = terminal / discount
        ev = number(present + terminal_pv)
        equity = number(ev + cash)
        return {"ok": True, "ev": ev, "equity": equity, "per_share": number(equity / shares),
                "terminal_weight": number(terminal_pv / ev) if ev else 0.0}
