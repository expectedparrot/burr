"""Reviewed input/output cell contracts for three specific workbook versions.

Only input cells are exposed to the Burr adapter. Reference outputs are read
separately, after LibreOffice recalculates the original spreadsheet formulas.
"""

from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_PAGE = "https://pages.stern.nyu.edu/adamodar/New_Home_Page/spreadsh.htm"
BASE_URL = "https://pages.stern.nyu.edu/adamodar/pc/"

MODELS = {
    "stable": {
        "filename": "fcffst.xls", "sheet": "NewFCFFStableGrowth",
        "inputs": {
            "ebit0": "D21", "tax_rate": "D22", "capex0": "D24",
            "depreciation0": "D25", "working_capital_change0": "D26",
            "capex_depreciation_ratio": "F28", "debt_weight": "D29",
            "beta": "D34", "riskfree": "D35", "risk_premium": "D36",
            "debt_cost": "D38", "stable_growth": "D40",
        },
        "guards": {"F27": "Yes", "F31": "No"},
        "outputs": {
            "nopat_current": ["F51"], "net_capex_current": ["F52"],
            "working_capital_change_current": ["F53"], "fcff_current": ["F54"],
            "cost_of_equity": ["D56"], "after_tax_debt_cost": ["D57"],
            "wacc": ["D58"], "ev": ["F61"],
        },
        "variants": {
            "growth_up": {"stable_growth": .06},
            "growth_down": {"stable_growth": .04},
            "tax_up": {"tax_rate": .40},
            "discount_up": {"riskfree": .08},
            "reinvestment_up": {"capex_depreciation_ratio": 1.5},
            "combined": {"ebit0": 1600, "tax_rate": .40, "riskfree": .08,
                         "stable_growth": .04, "capex_depreciation_ratio": 1.5},
        },
    },
    "two_stage": {
        "filename": "fcff2st.xls", "sheet": "NewFCFF2Stage",
        "inputs": {
            "ebit0": "D20", "capex0": "D22", "depreciation0": "D23",
            "tax_rate": "D24", "revenue0": "D25", "working_capital0": "D26",
            "working_capital_change0": "D27", "cash": "D28", "options": "D29",
            "prior_book_debt": "E30", "prior_book_equity": "E31",
            "share_price": "F36", "shares": "F37", "debt": "F38",
            "high_years": "E43", "beta": "D52", "riskfree": "D53",
            "risk_premium": "D54", "debt_cost": "E56",
            "stable_growth": "E79", "stable_roc": "F101",
        },
        # Deliberately fail closed outside this reviewed branch of the workbook.
        "guards": {"F34": "Yes", "F45": "No", "E49": "No", "F69": "No",
                   "E75": 0, "E76": 0, "E82": "No", "E85": "No",
                   "F89": "Yes", "F95": "Yes", "F99": "No", "F100": "Yes"},
        "outputs": {
            "cost_of_equity": ["D106"], "debt_weight": ["D109"],
            "after_tax_debt_cost": ["D108"], "wacc": ["D110"],
            "high_growth": ["D123"], "working_capital_ratio": ["E131"],
            "nopat": [f"{c}134" for c in "DEFGH"] + ["N134"],
            "net_capex": [f"{c}135" for c in "DEFGH"] + ["N135"],
            "working_capital_change": [f"{c}136" for c in "DEFGH"] + ["N136"],
            "fcff": [f"{c}137" for c in "DEFGH"] + ["N137"],
            "pv_fcff": [f"{c}138" for c in "DEFGH"],
            "terminal_value": ["E147"], "pv_terminal": ["F150"],
            "ev": ["F151"], "equity_before_options": ["F154"],
            "per_share": ["F156"],
        },
        "variants": {
            "growth_up": {"prior_book_equity": 10000},
            "growth_down": {"prior_book_equity": 15000},
            "tax_up": {"tax_rate": .35},
            "discount_up": {"riskfree": .063},
            "reinvestment_up": {"capex0": 2500},
            "terminal_growth_down": {"stable_growth": .05},
            "combined": {"capex0": 2500, "tax_rate": .35, "riskfree": .063,
                         "stable_growth": .05, "stable_roc": .15},
        },
    },
    "three_stage": {
        "filename": "fcff3st.xls", "sheet": "Sheet1",
        "inputs": {
            "revenue0": "D3", "ebit0": "D4", "capex0": "D5",
            "depreciation0": "D6", "debt": "D8", "cash": "D9", "options": "D10",
            "shares": "D11", "high_growth": "E14", "high_margin": "E16",
            "high_debt_weight": "E17", "capex_growth": "E18",
            "working_capital_ratio": "E19", "tax_rate": "E20", "high_beta": "E21",
            "riskfree": "E22", "risk_premium": "E23", "high_debt_cost": "E24",
            "stable_growth": "E26", "stable_margin": "E27", "stable_roc": "E29",
            "stable_debt_weight": "E31", "stable_debt_cost": "E32", "stable_beta": "E33",
        },
        "linked_inputs": {"capex_growth": "high_growth"},
        "guards": {"E28": "Yes"},
        "outputs": {
            "revenue_growth": [f"{c}36" for c in "CDEFGHIJKL"],
            "depreciation_growth": [f"{c}37" for c in "CDEFGHIJKL"],
            "revenue": [f"{c}38" for c in "CDEFGHIJKL"],
            "ebit": [f"{c}42" for c in "CDEFGHIJKL"],
            "nopat": [f"{c}45" for c in "CDEFGHIJKL"],
            "depreciation": [f"{c}46" for c in "CDEFGHIJKL"],
            "capex": [f"{c}47" for c in "CDEFGHIJKL"],
            "working_capital_change": [f"{c}48" for c in "CDEFGHIJKL"],
            "fcff": [f"{c}49" for c in "CDEFGHIJKL"],
            "cost_of_equity": [f"{c}53" for c in "CDEFGHIJKL"],
            "after_tax_debt_cost": [f"{c}55" for c in "CDEFGHIJKL"],
            "debt_weight": [f"{c}56" for c in "CDEFGHIJKL"],
            "wacc": [f"{c}57" for c in "CDEFGHIJKL"],
            "discount_factor": [f"{c}58" for c in "CDEFGHIJKL"],
            "pv_cashflow_and_terminal": [f"{c}60" for c in "CDEFGHIJKL"],
            "terminal_value": ["L50"], "ev": ["C63"],
            "equity_before_options": ["C66"], "per_share": ["C68"],
        },
        "variants": {
            "growth_up": {"high_growth": .35},
            "growth_down": {"high_growth": .25},
            "margin_down": {"high_margin": .25, "stable_margin": .20},
            "discount_up": {"riskfree": .075},
            "reinvestment_up": {"capex0": 300, "stable_roc": .10},
            "terminal_growth_down": {"stable_growth": .05},
            "combined": {"high_growth": .25, "high_margin": .25, "stable_margin": .20,
                         "riskfree": .075, "capex0": 300, "stable_growth": .05},
        },
    },
}


def variants(name):
    return {"base": {}, **MODELS[name]["variants"]}


def case_inputs(name, baseline, scenario):
    result = deepcopy(baseline)
    edits = variants(name)[scenario]
    result.update(edits)
    for linked, source in MODELS[name].get("linked_inputs", {}).items():
        if linked not in edits:
            result[linked] = result[source]
    return result
