"""Hand-authored Burr equivalents. This module never reads oracle outputs.

Preprocessing expands time profiles. WACC remains linked to model formulas. All operating amounts,
including the three-stage terminal capex endpoint, are calculated by Burr DSL.
"""

from pathlib import Path

from burr import ENGINE_VERSION, SCHEMA_VERSION
from burr.model import Workspace
from burr.operations import coherent
from burr.storage import yaml_text

from .catalog import MODELS, case_inputs


def ramp(start, end, n=5):
    """Exclude the starting year and include the final year, like the source."""
    return [start + (end - start) * i / n for i in range(1, n + 1)]


def definition(name, inputs):
    p = inputs
    units = {}
    bindings = {}

    def bind(key, value, unit="ratio"):
        bindings[key] = value
        units[key] = unit

    def raw(key, unit="ratio"):
        bind(key, p[key], unit)

    if name == "stable":
        for key in ("ebit0", "depreciation0", "working_capital_change0"):
            raw(key, "currency")
        for key in ("tax_rate", "capex_depreciation_ratio", "debt_weight", "beta",
                    "riskfree", "risk_premium", "debt_cost", "stable_growth"):
            raw(key)
        lines = {
            "nopat_current": "ebit0 * (1 - tax_rate)",
            "net_capex_current": "(capex_depreciation_ratio - 1) * depreciation0",
            "working_capital_change_current": "working_capital_change0",
            "fcff_current": "nopat_current - net_capex_current - working_capital_change_current",
            "fcff": "fcff_current * grow(1, stable_growth)",
            "cost_of_equity": "riskfree + beta * risk_premium",
            "after_tax_debt_cost": "debt_cost * (1 - tax_rate)",
            "wacc": "cost_of_equity * (1 - debt_weight) + after_tax_debt_cost * debt_weight",
        }
        n, shares, cash = 1, 1, 0
    elif name == "two_stage":
        if p["high_years"] != 5:
            raise ValueError("The reviewed two-stage cell map requires five high-growth years")
        n = 6  # Include the first stable year explicitly; see README for equivalence.
        for key in ("ebit0", "capex0", "depreciation0", "revenue0", "working_capital0"):
            raw(key, "currency")
        for key in ("tax_rate", "stable_growth", "stable_roc", "riskfree", "risk_premium",
                    "beta", "debt_cost"):
            raw(key)
        # C67*C68 simplifies to reinvestment / prior book capital. No Excel output is read.
        growth = (p["capex0"] - p["depreciation0"] + p["working_capital_change0"]) / (
            p["prior_book_debt"] + p["prior_book_equity"])
        debt_weight = p["debt"] / (p["debt"] + p["share_price"] * p["shares"])
        bind("high_growth", growth)
        bind("debt_weight", debt_weight)
        bind("growth_profile", [growth] * 5 + [p["stable_growth"]])
        bind("stable_weight", [0] * 5 + [1])
        lines = {
            "revenue": "grow(revenue0, growth_profile)",
            "ebit": "grow(ebit0, growth_profile)",
            "nopat": "ebit * (1 - tax_rate)",
            "working_capital_ratio": "maximum(working_capital0 / revenue0, 0)",
            "working_capital_change": "delta(revenue, revenue0) * working_capital_ratio",
            "depreciation": "grow(depreciation0, growth_profile)",
            "high_capex": "grow(capex0, growth_profile)",
            "net_capex": "(1 - stable_weight) * (high_capex - depreciation) + stable_weight * (nopat * stable_growth / stable_roc - working_capital_change)",
            "fcff": "nopat - net_capex - working_capital_change",
            "growth_assumption": "high_growth",
            "cost_of_equity": "riskfree + beta * risk_premium",
            "after_tax_debt_cost": "debt_cost * (1 - tax_rate)",
            "debt_ratio": "debt_weight",
            "wacc": "cost_of_equity * (1 - debt_weight) + after_tax_debt_cost * debt_weight",
            "discount_factor": "grow(1, wacc)",
            "pv_fcff": "fcff / discount_factor",
        }
        shares, cash = p["shares"], p["cash"] - p["debt"] - p["options"]
    elif name == "three_stage":
        n = 10
        for key in ("revenue0", "capex0", "depreciation0"):
            raw(key, "currency")
        for key in ("high_growth", "capex_growth", "stable_growth", "stable_margin", "stable_roc",
                    "working_capital_ratio", "tax_rate", "riskfree", "risk_premium"):
            raw(key)
        for key, start, end in (
            ("revenue_growth_profile", p["high_growth"], p["stable_growth"]),
            ("depreciation_growth_profile", p["capex_growth"], p["stable_growth"]),
            ("beta_profile", p["high_beta"], p["stable_beta"]),
            ("debt_cost_profile", p["high_debt_cost"], p["stable_debt_cost"]),
            ("debt_weight_profile", p["high_debt_weight"], p["stable_debt_weight"]),
        ):
            bind(key, [start] * 5 + ramp(start, end))
        bind("margin_profile", ramp(p["ebit0"] / p["revenue0"], p["high_margin"]) +
             ramp(p["high_margin"], p["stable_margin"]))
        bind("capex_growth_profile", [p["capex_growth"]] * 5 + [0] * 5)
        bind("transition_weight", [0] * 5 + ramp(0, 1))
        bind("transition_years", 5)
        lines = {
            "revenue_growth": "revenue_growth_profile",
            "depreciation_growth": "depreciation_growth_profile",
            "revenue": "grow(revenue0, revenue_growth_profile)",
            "ebit": "revenue * margin_profile",
            "nopat": "ebit * (1 - tax_rate)",
            "depreciation": "grow(depreciation0, depreciation_growth_profile)",
            "working_capital_change": "delta(revenue, revenue0) * working_capital_ratio",
            # The source's years 6-9 capex depend on the year-10 amount. Burr has
            # no forward references; express the endpoint algebra from raw inputs.
            "revenue_step": "(high_growth - stable_growth) / transition_years",
            "depreciation_step": "(capex_growth - stable_growth) / transition_years",
            "revenue5": "revenue0" + " * (1 + high_growth)" * 5,
            "depreciation5": "depreciation0" + " * (1 + capex_growth)" * 5,
        }
        for prefix, first in (("revenue", "high_growth"), ("depreciation", "capex_growth")):
            for year in range(6, 11):
                previous = first if year == 6 else f"{prefix}_growth{year - 1}"
                lines[f"{prefix}_growth{year}"] = f"{previous} - {prefix}_step"
                lines[f"{prefix}{year}"] = f"{prefix}{year - 1} * (1 + {prefix}_growth{year})"
        lines.update({
            "terminal_nopat": "revenue10 * stable_margin * (1 - tax_rate)",
            "terminal_working_capital_change": "(revenue10 - revenue9) * working_capital_ratio",
            "terminal_capex": "terminal_nopat * stable_growth / stable_roc - terminal_working_capital_change + depreciation10",
            "capex": "(1 - transition_weight) * grow(capex0, capex_growth_profile) + transition_weight * terminal_capex",
            "fcff": "nopat + depreciation - capex - working_capital_change",
            "cost_of_equity": "riskfree + beta_profile * risk_premium",
            "after_tax_debt_cost": "debt_cost_profile * (1 - tax_rate)",
            "debt_weight": "debt_weight_profile",
            "wacc": "cost_of_equity * (1 - debt_weight_profile) + after_tax_debt_cost * debt_weight_profile",
            "discount_factor": "grow(1, wacc)",
            "pv_fcff": "fcff / discount_factor",
        })
        shares, cash = p["shares"], p["cash"] - p["debt"] - p["options"]
    else:
        raise ValueError(f"Unknown model: {name}")

    source = MODELS[name]

    def annotated(key, value, section):
        cell = source["inputs"].get(key)
        return {"value": value,
                "source": f"{source['filename']}!{source['sheet']}" + (f"!{cell}" if cell else "; input-only adapter"),
                "rationale": ("Historical workbook illustration, not current company guidance. " +
                              ("Direct source assumption." if cell else
                               f"Derived {section} from source inputs or structural year weights; see models.py."))}

    template = {"template": name, "doc": f"Independent Burr reconstruction of {source['filename']}.",
                "parameters": [{"name": k, "unit": units[k]} for k in bindings],
                "lines": lines, "checks": ["wacc > stable_growth", "fcff >= 0"]}
    params = {"entity": name, "template": name, "base_year": 0, "periods": f"1..{n}",
              "bindings": {k: annotated(k, v, "binding") for k, v in bindings.items()},
              "valuation": {"fcf": "fcff", **{k: annotated(k, v, "valuation") for k, v in {
                  "shares": shares,
                  "net_cash": cash}.items()}}}
    for key, ref in (("wacc", "wacc"), ("terminal_growth", "stable_growth")):
        params["valuation"][key] = {"ref": ref, "source": f"Burr model: {ref}",
            "rationale": "Follow the current scenario instead of copying a computed valuation input."}
    return template, params


def write_workspace(root, inputs):
    """Generate a new workspace. Never overwrite an existing experiment journal."""
    root = Path(root)
    if root.exists():
        raise FileExistsError(f"Use a new workspace directory: {root}")
    (root / "templates").mkdir(parents=True)
    (root / "burr.lock").write_text(yaml_text({"engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION}))
    for name, spec in MODELS.items():
        template, params = definition(name, inputs[name])
        params["scenarios"] = {}
        for scenario in spec["variants"]:
            _, trial = definition(name, case_inputs(name, inputs[name], scenario))
            params["scenarios"][scenario] = {
                "thesis": f"Benchmark perturbation {scenario}: {spec['variants'][scenario]}. Other source inputs and workbook switches held fixed.",
                "bindings": trial["bindings"], "valuation": trial["valuation"],
            }
        company = root / "companies" / name
        company.mkdir(parents=True)
        (company / "params.yaml").write_text(yaml_text(params))
        # Source examples are frozen assumptions, not independently reviewed facts.
        (company / "actuals.csv").write_text("period,line,value\n")
        (root / "templates" / f"{name}.yaml").write_text(yaml_text(template))
        coherent(Workspace(company))
    return root


def outputs(model, name, inputs):
    """Select semantically matched outputs; no workbook expected values enter here."""
    result, value = model.run(), model.value()
    selected = {}
    scalar_lines = {"high_growth": "growth_assumption", "debt_weight": "debt_ratio"}
    for key, cells in MODELS[name]["outputs"].items():
        if key in result:
            selected[key] = result[key][:len(cells)]
        elif name == "two_stage" and key in scalar_lines:
            selected[key] = result[scalar_lines[key]][:1]
    selected["ev"] = [value["ev"]]
    if name != "stable":
        selected["equity_before_options"] = [value["equity"] + inputs["options"]]
        selected["per_share"] = [value["per_share"]]
        growth = inputs["stable_growth"]
        terminal = result["fcff"][-1] / (result["wacc"][-1] - growth)
        if name == "three_stage":
            terminal *= 1 + growth
            pv = result["pv_fcff"][:]
            pv[-1] += terminal / result["discount_factor"][-1]
            selected["pv_cashflow_and_terminal"] = pv
        else:
            selected["pv_terminal"] = [terminal / result["discount_factor"][-2]]
        selected["terminal_value"] = [terminal]
    return selected
