"""Accounting and valuation checks for the sourced Starbucks teaching example."""

import csv
from pathlib import Path

import pytest

from burr.model import Workspace
from burr.operations import coherent


ROOT = Path(__file__).resolve().parents[1] / "examples/starbucks"


def test_reported_revenue_and_capital_bridge():
    rows = list(csv.DictReader((ROOT / "sources/reported.csv").open()))
    facts = {(int(row["period"]), row["line"]): float(row["value"]) for row in rows}
    assert len(facts) == len(rows)
    for year in (2024, 2025):
        assert sum(facts[year, line] for line in (
            "company_revenue", "licensed_revenue", "other_revenue"
        )) == pytest.approx(facts[year, "revenue"])
    workspace = Workspace(ROOT / "companies/starbucks")
    valuation = workspace.params["valuation"]
    capital = sum(facts[2025, line] * sign for line, sign in (
        ("cash", 1), ("short_term_investments", 1), ("current_debt", -1),
        ("long_term_debt", -1), ("noncontrolling_interests", -1),
    ))
    assert valuation["net_cash"]["value"] == pytest.approx(capital)
    assert valuation["shares"]["value"] == facts[2025, "shares_outstanding"]


def test_scenarios_and_independent_base_dcf():
    workspace = Workspace(ROOT / "companies/starbucks")
    assert coherent(workspace)["ok"]
    company, licensed, other, previous = 30744.8, 4350.4, 2089.2, 37184.4
    cashflows = []
    for year in range(5):
        company *= 1.02 * (1.01 + year * .005) * 1.02
        licensed *= 1.04
        other *= 1.04
        revenue = company + licensed + other
        cashflows.append(revenue * ((.10 + .01 * year) * .75 + .047 - (.065 - .00125 * year))
                         - .02 * (revenue - previous))
        previous = revenue
    terminal = cashflows[-1] * 1.025 / (.09 - .025)
    ev = sum(cf / 1.09 ** t for t, cf in enumerate(cashflows, 1)) + terminal / 1.09 ** 5
    assert workspace.model().value()["per_share"] == pytest.approx((ev - 12615.2) / 1136.9)
    prices = [workspace.model(s).value()["per_share"] for s in ("bear", "base", "bull")]
    assert prices == sorted(prices)
