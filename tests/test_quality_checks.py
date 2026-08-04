import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from quality_checks import run_quality_checks, CATEGORY_BY_TYPE


def _one_good_row(item_type="asset", item_category="cash_reserves", **overrides):
    row = {
        "reporting_date": "2026-01-01",
        "item_category": item_category,
        "item_type": item_type,
        "balance_aud": 1_000_000.0,
        "injected_scenario": "baseline_healthy",
    }
    row.update(overrides)
    return row


def _full_day(reporting_date="2026-01-01"):
    rows = []
    for item_type, cats in CATEGORY_BY_TYPE.items():
        for cat in cats:
            rows.append(_one_good_row(item_type=item_type, item_category=cat, reporting_date=reporting_date))
    return rows


def test_complete_valid_day_passes():
    df = pd.DataFrame(_full_day())
    report = run_quality_checks(df)
    assert report.passed, report.summary()


def test_missing_column_fails():
    df = pd.DataFrame(_full_day()).drop(columns=["balance_aud"])
    report = run_quality_checks(df)
    assert not report.passed
    assert any(i.check == "schema" for i in report.issues)


def test_invalid_item_type_fails():
    rows = _full_day()
    rows[0]["item_type"] = "not_a_real_type"
    df = pd.DataFrame(rows)
    report = run_quality_checks(df)
    assert not report.passed
    assert any(i.check == "domain" for i in report.issues)


def test_invalid_category_for_type_fails():
    rows = _full_day()
    rows[0]["item_category"] = "totally_made_up_category"
    df = pd.DataFrame(rows)
    report = run_quality_checks(df)
    assert not report.passed
    assert any(i.check == "domain" for i in report.issues)


def test_negative_balance_fails():
    rows = _full_day()
    rows[0]["balance_aud"] = -5_000_000.0
    df = pd.DataFrame(rows)
    report = run_quality_checks(df)
    assert not report.passed
    assert any(i.check == "range" for i in report.issues)


def test_implausibly_large_balance_fails():
    rows = _full_day()
    rows[0]["balance_aud"] = 999_000_000_000.0
    df = pd.DataFrame(rows)
    report = run_quality_checks(df)
    assert not report.passed
    assert any(i.check == "range" for i in report.issues)


def test_duplicate_line_item_fails():
    rows = _full_day()
    rows.append(_one_good_row())  # duplicate (date, category, type)
    df = pd.DataFrame(rows)
    report = run_quality_checks(df)
    assert not report.passed
    assert any(i.check == "duplicates" for i in report.issues)


def test_incomplete_day_fails():
    rows = _full_day()[:-1]  # drop one required line item
    df = pd.DataFrame(rows)
    report = run_quality_checks(df)
    assert not report.passed
    assert any(i.check == "completeness" for i in report.issues)
