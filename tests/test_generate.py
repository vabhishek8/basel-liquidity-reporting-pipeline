import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from generate_balance_sheet import generate_history, _fixed_baseline_items
from quality_checks import CATEGORY_BY_TYPE

EXPECTED_LINE_ITEMS_PER_DAY = sum(len(v) for v in CATEGORY_BY_TYPE.values())


def test_every_day_has_a_complete_balance_sheet():
    items = generate_history(date(2026, 1, 1), 10, seed=1)
    per_date = {}
    for i in items:
        per_date.setdefault(i.reporting_date, []).append(i)
    for d, rows in per_date.items():
        assert len(rows) == EXPECTED_LINE_ITEMS_PER_DAY, f"{d} has {len(rows)} rows"


def test_no_negative_balances():
    items = generate_history(date(2026, 1, 1), 120, seed=42)
    negatives = [i for i in items if i.balance_aud < 0]
    assert not negatives, f"{len(negatives)} negative balances, e.g. {negatives[:3]}"


def test_seed_is_reproducible():
    a = generate_history(date(2026, 1, 1), 20, seed=7)
    b = generate_history(date(2026, 1, 1), 20, seed=7)
    assert [(i.item_category, i.balance_aud) for i in a] == [(i.item_category, i.balance_aud) for i in b]


def test_different_seeds_produce_different_baseline_days():
    a = generate_history(date(2026, 1, 1), 5, seed=1)
    b = generate_history(date(2026, 1, 1), 5, seed=2)
    assert [i.balance_aud for i in a] != [i.balance_aud for i in b]


def test_injected_scenarios_are_tagged():
    items = generate_history(date(2026, 1, 1), 100, seed=42)
    scenarios = {i.injected_scenario for i in items}
    assert {"baseline_healthy", "deposit_run", "wholesale_reliance", "l2b_heavy"} <= scenarios


def test_fixed_baseline_is_deterministic():
    a = _fixed_baseline_items(date(2026, 1, 1), "x")
    b = _fixed_baseline_items(date(2026, 1, 1), "x")
    assert [(i.item_category, i.balance_aud) for i in a] == [(i.item_category, i.balance_aud) for i in b]
