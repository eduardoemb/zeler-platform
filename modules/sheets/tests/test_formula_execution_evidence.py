from __future__ import annotations

from importlib import import_module

summarize = import_module("modules.sheets.tests.formula_execution_evidence").summarize


def test_only_passing_executed_cases_count_as_local_evidence() -> None:
    report = summarize(
        {"A", "B", "C"},
        {"positive": [("A", "returned")], "absence": [("B", "unavailable")]},
        {"positive": "passed", "absence": "failed"},
    )
    assert report["formulas"]["A"] == [{"test": "positive", "outcome": "returned"}]
    assert report["formulas"]["B"] == []
    assert report["missing"] == ["B", "C"]
    assert report["sheets_verified"] is False
    assert report["correctness_verified"] is False


def test_unknown_formula_is_not_silently_added_to_catalog() -> None:
    report = summarize({"A"}, {"test": [("OTHER", "returned")]}, {"test": "passed"})
    assert report["unknown"] == ["OTHER"]
    assert report["missing"] == ["A"]
