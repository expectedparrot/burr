"""Strict scoring behavior for the paired agent pilot."""

import pytest

from benchmarks.damodaran.agent_pilot.grade import score_metrics


def test_exact_and_small_rounding_errors_pass():
    result = score_metrics({"cashflow": [100., 200.00000001]}, {"cashflow": [100., 200.]})
    assert result["ok"] and result["passed"] == result["total"] == 2


@pytest.mark.parametrize("actual", [None, {}, {"cashflow": []}, {"cashflow": [1, 2, 3]},
                                    {"cashflow": [float("nan"), 2]}, {"cashflow": [True, 2]},
                                    {"cashflow": [1, 2], "extra": [1]}])
def test_malformed_submissions_do_not_pass(actual):
    assert not score_metrics(actual, {"cashflow": [1, 2]})["ok"]


def test_partial_credit_retains_wrong_cell():
    result = score_metrics({"cashflow": [100, 205]}, {"cashflow": [100, 200]})
    assert not result["ok"]
    assert result["passed"] == 1 and result["total"] == 2
    assert result["checks"][1] == {
        "metric": "cashflow", "index": 1, "actual": 205, "expected": 200, "ok": False}
