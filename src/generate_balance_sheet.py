"""
Synthetic daily balance-sheet generator for a single illustrative
Australian bank, sized to demonstrate Basel III LCR and NSFR reporting.

No real balance-sheet data exists in or is derived from this project.
Every line item is synthesized. A handful of specific reporting dates are
engineered with fixed, hand-calculable balances and tagged with a known
`injected_scenario` label, ground truth that the gold-layer calculation
in src/gold.py never reads, in the same spirit as the ground-truth
injection pattern used in the companion AML-monitoring project.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path

from factors import ASSET_CATEGORIES, INFLOW_CATEGORIES, LIABILITY_CATEGORIES, OFF_BALANCE_CATEGORIES

RNG_SEED = 42
BASELINE_DAYS = 120


@dataclass
class LineItem:
    reporting_date: str
    item_category: str
    item_type: str  # "asset" | "inflow" | "liability" | "off_balance"
    balance_aud: float
    injected_scenario: str


def _baseline_day(rng: random.Random, d: date, scale: float = 1.0) -> list[LineItem]:
    """A healthy, randomly-jittered day around a target profile sized so
    LCR lands roughly 125-150% and NSFR roughly 110-125%."""
    def j(x, spread=0.06):
        return round(x * scale * (1 + rng.uniform(-spread, spread)), 2)

    items: list[LineItem] = []

    asset_targets = {
        "cash_reserves": 180_000_000,
        "ags_semis": 420_000_000,
        "l2a_securities": 150_000_000,
        "l2b_corporate_bonds": 60_000_000,
        "l2b_equities": 20_000_000,
        "residential_mortgages": 2_400_000_000,
        "retail_loans_other": 300_000_000,
        "wholesale_loans_lt1y": 220_000_000,
        "wholesale_loans_gt1y": 480_000_000,
        "other_assets": 140_000_000,
    }
    for cat, target in asset_targets.items():
        items.append(LineItem(d.isoformat(), cat, "asset", j(target), "baseline_healthy"))

    inflow_targets = {
        "inflows_retail_30d": 90_000_000,
        "inflows_wholesale_30d": 60_000_000,
    }
    for cat, target in inflow_targets.items():
        items.append(LineItem(d.isoformat(), cat, "inflow", j(target), "baseline_healthy"))

    liability_targets = {
        "retail_deposits_stable": 1_500_000_000,
        "retail_deposits_less_stable": 500_000_000,
        "sme_deposits_stable": 300_000_000,
        "operational_deposits": 180_000_000,
        "nonfin_corporate_funding_lt1y": 220_000_000,
        "financial_institution_funding_lt1y": 150_000_000,
        "secured_funding_l1": 100_000_000,
        "secured_funding_l2a": 60_000_000,
        "secured_funding_other": 40_000_000,
        "wholesale_debt_gt1y": 500_000_000,
        "tier1_tier2_capital": 350_000_000,
        "other_liabilities": 90_000_000,
    }
    for cat, target in liability_targets.items():
        items.append(LineItem(d.isoformat(), cat, "liability", j(target), "baseline_healthy"))

    off_balance_targets = {
        "committed_credit_facilities_corp": 260_000_000,
        "committed_liquidity_facilities_fi": 80_000_000,
    }
    for cat, target in off_balance_targets.items():
        items.append(LineItem(d.isoformat(), cat, "off_balance", j(target), "baseline_healthy"))

    return items


def _scenario_deposit_run(d: date) -> list[LineItem]:
    """20% of stable and less-stable retail deposits are withdrawn in
    cash within the reporting window; the bank pays out the withdrawal
    from cash reserves first, then liquidates government securities for
    any shortfall. Fixed dollar amounts, no randomization, so the
    expected LCR/NSFR can be hand-calculated exactly for tests."""
    items = _fixed_baseline_items(d, scenario="deposit_run")
    by_cat = {(i.item_category, i.item_type): i for i in items}

    stable = by_cat[("retail_deposits_stable", "liability")]
    less_stable = by_cat[("retail_deposits_less_stable", "liability")]
    cash = by_cat[("cash_reserves", "asset")]
    ags = by_cat[("ags_semis", "asset")]

    total_deposits = stable.balance_aud + less_stable.balance_aud
    withdrawal = round(0.20 * total_deposits, 2)
    stable_share = stable.balance_aud / total_deposits

    stable.balance_aud -= round(withdrawal * stable_share, 2)
    less_stable.balance_aud -= round(withdrawal * (1 - stable_share), 2)

    if withdrawal <= cash.balance_aud:
        cash.balance_aud -= withdrawal
    else:
        remainder = withdrawal - cash.balance_aud
        cash.balance_aud = 0.0
        ags.balance_aud -= remainder

    return list(by_cat.values())


def _scenario_wholesale_reliance(d: date) -> list[LineItem]:
    """The bank funds a larger share of its balance sheet with short-term
    interbank/FI money, doubling reliance on funding that carries 100%
    LCR runoff and 0% NSFR ASF credit."""
    items = _fixed_baseline_items(d, scenario="wholesale_reliance")
    by_cat = {(i.item_category, i.item_type): i for i in items}

    extra_fi_funding = by_cat[("financial_institution_funding_lt1y", "liability")].balance_aud * 1.8
    by_cat[("financial_institution_funding_lt1y", "liability")].balance_aud += round(extra_fi_funding, 2)
    # The extra funding is invested into wholesale loans, so the balance
    # sheet still balances; RSF on those loans is 50%, well short of the
    # 0% ASF credit on the funding that raised it.
    by_cat[("wholesale_loans_lt1y", "asset")].balance_aud += round(extra_fi_funding, 2)
    return list(by_cat.values())


def _scenario_l2b_heavy(d: date) -> list[LineItem]:
    """HQLA composition skewed so Level 2B alone breaches its 15%
    sub-cap while total Level 1 + Level 2 is still under the 40% cap on
    Level 2. This is the scenario that distinguishes a correct sequential
    HQLA-capping waterfall from a naive single 40% cap; see
    tests/test_gold.py::test_hqla_waterfall_not_naive_single_cap."""
    items = _fixed_baseline_items(d, scenario="l2b_heavy")
    by_cat = {(i.item_category, i.item_type): i for i in items}

    by_cat[("l2a_securities", "asset")].balance_aud = 60_000_000
    by_cat[("l2b_corporate_bonds", "asset")].balance_aud = 250_000_000
    by_cat[("l2b_equities", "asset")].balance_aud = 100_000_000
    return list(by_cat.values())


def _fixed_baseline_items(d: date, scenario: str) -> list[LineItem]:
    """A fixed (non-randomized) baseline day, used as the base that
    engineered scenarios perturb, so scenario tests are exactly
    reproducible."""
    rng = random.Random(0)
    items = _baseline_day(rng, d, scale=1.0)
    for i in items:
        i.injected_scenario = scenario
    return items


def generate_history(start: date, days: int, seed: int = RNG_SEED) -> list[LineItem]:
    rng = random.Random(seed)
    all_items: list[LineItem] = []
    scenario_offsets = {35: _scenario_deposit_run, 70: _scenario_wholesale_reliance, 95: _scenario_l2b_heavy}

    for offset in range(days):
        d = start + timedelta(days=offset)
        if offset in scenario_offsets:
            all_items.extend(scenario_offsets[offset](d))
        else:
            all_items.extend(_baseline_day(rng, d))

    return all_items


def write_bronze(items: list[LineItem], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    out_path = out_dir / f"balance_sheet_{stamp}.jsonl"
    with out_path.open("w") as f:
        for item in items:
            f.write(json.dumps(asdict(item)) + "\n")
    return out_path


if __name__ == "__main__":
    import sys

    daily_seed = int(date.today().strftime("%Y%m%d"))
    start_date = date.today() - timedelta(days=BASELINE_DAYS - 1)
    items = generate_history(start_date, BASELINE_DAYS, seed=daily_seed)
    out = write_bronze(items, Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/bronze"))
    print(f"Wrote {len(items)} line items across {BASELINE_DAYS} days to {out}")
