"""
Golden-calculation tests for the LCR/NSFR engine.

Unlike the companion AML project (a statistical detector, tested on
recall/false-positive rate against injected ground truth), this is a
deterministic regulatory formula: correctness means "matches a
hand-calculated expected value exactly," not "detects most cases."
"""

import dataclasses
import datetime
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from generate_balance_sheet import _fixed_baseline_items, _scenario_deposit_run, _scenario_l2b_heavy
from quality_checks import CATEGORY_BY_TYPE
from transform import build_silver
from gold import build_gold, build_naive_hqla
from factors import REGULATORY_MINIMUM


def _items_to_silver(items):
    df = pd.DataFrame([dataclasses.asdict(i) for i in items])
    return build_silver(df)


def _toy_fixture():
    """A minimal, hand-verifiable balance sheet. Every category not
    mentioned is set to zero so the expected LCR/NSFR can be computed by
    hand exactly (see the docstring math in each assertion below)."""
    balances = {cat: 0.0 for cats in CATEGORY_BY_TYPE.values() for cat in cats}
    balances.update({
        "cash_reserves": 100.0,
        "ags_semis": 200.0,
        "l2a_securities": 100.0,
        "l2b_corporate_bonds": 40.0,
        "wholesale_loans_gt1y": 800.0,
        "inflows_wholesale_30d": 40.0,
        "retail_deposits_stable": 1000.0,
        "wholesale_debt_gt1y": 800.0,
    })
    rows = []
    for item_type, cats in CATEGORY_BY_TYPE.items():
        for cat in cats:
            rows.append({
                "reporting_date": "2026-01-01",
                "item_category": cat,
                "item_type": item_type,
                "balance_aud": balances[cat],
                "injected_scenario": "toy_fixture",
            })
    return build_silver(pd.DataFrame(rows))


def test_lcr_matches_hand_calculation():
    """
    Level 1 HQLA = 100 + 200 = 300 (no haircut).
    Level 2A after 15% haircut = 100 * 0.85 = 85.
    Level 2B after 50% haircut = 40 * 0.50 = 20.
    Level 2B sub-cap = 15/85 * 300 = 52.94..., 20 < cap, unconstrained.
    Level 2 combined = 85 + 20 = 105; total cap = 2/3 * 300 = 200, unconstrained.
    Total HQLA = 300 + 105 = 405.

    Outflows = 1000 * 5% (retail_deposits_stable) + 800 * 0% (wholesale_debt_gt1y, >=1y) = 50.
    Raw inflows = 40 * 100% (inflows_wholesale_30d) = 40.
    Inflow cap = 75% * 50 = 37.5, so capped inflows = 37.5.
    Net cash outflow = 50 - 37.5 = 12.5.
    LCR = 405 / 12.5 = 32.4 (3240%).
    """
    gold = build_gold(_toy_fixture())
    row = gold.iloc[0]
    assert row["total_hqla"] == pytest.approx(405.0, abs=1e-6)
    assert row["net_cash_outflow"] == pytest.approx(12.5, abs=1e-6)
    assert row["lcr"] == pytest.approx(32.4, abs=1e-6)


def test_nsfr_matches_hand_calculation():
    """
    ASF = 1000 * 95% (retail_deposits_stable) + 800 * 100% (wholesale_debt_gt1y) = 1750.
    RSF = 100*0% + 200*5% + 100*15% + 40*50% + 800*85% = 0+10+15+20+680 = 725.
    NSFR = 1750 / 725 = 2.413793... (241.38%).
    """
    gold = build_gold(_toy_fixture())
    row = gold.iloc[0]
    assert row["asf"] == pytest.approx(1750.0, abs=1e-6)
    assert row["rsf"] == pytest.approx(725.0, abs=1e-6)
    assert row["nsfr"] == pytest.approx(1750.0 / 725.0, rel=1e-9)


def test_baseline_day_is_above_regulatory_minimum():
    silver = _items_to_silver(_fixed_baseline_items(datetime.date(2026, 1, 1), "baseline_healthy"))
    row = build_gold(silver).iloc[0]
    assert row["lcr"] >= REGULATORY_MINIMUM
    assert row["nsfr"] >= REGULATORY_MINIMUM


def test_deposit_run_breaches_lcr_but_not_nsfr():
    """A 30-day cash-flow shock (LCR) should bite much harder than a
    1-year structural funding shock (NSFR) for the same event, this is
    the actual regulatory intent of running two ratios with different
    horizons, not a quirk of this implementation."""
    silver = _items_to_silver(_scenario_deposit_run(datetime.date(2026, 1, 1)))
    row = build_gold(silver).iloc[0]
    assert row["lcr"] < REGULATORY_MINIMUM, f"expected an LCR breach, got {row['lcr']:.4f}"
    assert row["nsfr"] >= REGULATORY_MINIMUM, f"NSFR should stay healthy, got {row['nsfr']:.4f}"


def test_hqla_waterfall_not_naive_single_cap():
    """
    Regression guard for the bug documented in src/gold.py and the
    README: a naive single 40%-of-total cap on Level 2 assets, without
    first sub-capping Level 2B at 15% of total HQLA, overstates HQLA
    whenever Level 2B is large relative to Level 2A. On the l2b_heavy
    scenario this naive approach overstates total HQLA by roughly $65M
    (about 8%), which would overstate LCR by a proportional amount.
    """
    silver = _items_to_silver(_scenario_l2b_heavy(datetime.date(2026, 1, 1)))
    correct = build_gold(silver).iloc[0]
    naive = build_naive_hqla(silver).iloc[0]

    overstatement = naive["naive_total_hqla"] - correct["total_hqla"]
    assert overstatement > 50_000_000, (
        f"expected the naive cap to overstate HQLA by >$50M on a Level-2B-heavy "
        f"portfolio, got ${overstatement:,.0f}"
    )
    assert correct["total_hqla"] < naive["naive_total_hqla"]


def test_lcr_and_nsfr_bounded_and_positive():
    silver = _items_to_silver(_fixed_baseline_items(datetime.date(2026, 1, 1), "baseline_healthy"))
    row = build_gold(silver).iloc[0]
    assert row["lcr"] > 0
    assert row["nsfr"] > 0
    assert row["total_hqla"] > 0
    assert row["net_cash_outflow"] > 0
