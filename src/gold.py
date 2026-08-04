"""
Gold layer: LCR and NSFR calculation engine.

The HQLA capping logic is the part of this file worth reading first. The
Level 2 cap in BCBS238 par 51 is specified as two nested caps, not one:
Level 2B assets cannot exceed 15% of total HQLA, and total Level 2 (2A+2B
combined) cannot exceed 40% of total HQLA. Applying only the 40% total
cap and skipping the 15% Level 2B sub-cap materially overstates HQLA
whenever Level 2B is large relative to Level 2A. See
NAIVE_HQLA_SQL below and tests/test_gold.py::test_hqla_waterfall
for the regression test that guards against reintroducing this bug.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from factors import (
    ASSET_CATEGORIES,
    INFLOW_CATEGORIES,
    LIABILITY_CATEGORIES,
    OFF_BALANCE_CATEGORIES,
    INFLOW_CAP_RATIO,
    LEVEL_2B_TO_LEVEL_1_RATIO,
    LEVEL_2_TO_LEVEL_1_RATIO,
)


def _category_factor_table() -> pd.DataFrame:
    """Flatten the four category dicts in factors.py into one lookup
    table that the SQL below joins the balance sheet against."""
    rows = []
    for cat, spec in ASSET_CATEGORIES.items():
        rows.append({
            "item_category": cat, "item_type": "asset",
            "haircut": spec["haircut"], "hqla_level": spec["hqla_level"],
            "rsf_factor": spec["rsf_factor"], "runoff_rate": None,
            "asf_factor": None, "inflow_rate": None,
        })
    for cat, spec in INFLOW_CATEGORIES.items():
        rows.append({
            "item_category": cat, "item_type": "inflow",
            "haircut": None, "hqla_level": None, "rsf_factor": None,
            "runoff_rate": None, "asf_factor": None, "inflow_rate": spec["inflow_rate"],
        })
    for cat, spec in LIABILITY_CATEGORIES.items():
        rows.append({
            "item_category": cat, "item_type": "liability",
            "haircut": None, "hqla_level": None, "rsf_factor": None,
            "runoff_rate": spec["runoff_rate"], "asf_factor": spec["asf_factor"], "inflow_rate": None,
        })
    for cat, spec in OFF_BALANCE_CATEGORIES.items():
        rows.append({
            "item_category": cat, "item_type": "off_balance",
            "haircut": None, "hqla_level": None, "rsf_factor": spec["rsf_factor"],
            "runoff_rate": spec["runoff_rate"], "asf_factor": None, "inflow_rate": None,
        })
    return pd.DataFrame(rows)


# Per-date component aggregation shared by both the correct and naive
# calculations below: everything except the HQLA capping waterfall
# itself, which differs between the two.
_COMPONENTS_CTE = """
with joined as (
    select b.*, f.haircut, f.hqla_level, f.rsf_factor, f.runoff_rate, f.asf_factor, f.inflow_rate
    from silver b
    join factors f using (item_category, item_type)
),
components as (
    select
        reporting_date,
        sum(case when hqla_level = 'L1' then balance_aud * (1 - haircut) else 0 end) as level1_hqla,
        sum(case when hqla_level = 'L2A' then balance_aud * (1 - haircut) else 0 end) as raw_level2a,
        sum(case when hqla_level = 'L2B' then balance_aud * (1 - haircut) else 0 end) as raw_level2b,
        sum(case when item_type = 'liability' then balance_aud * runoff_rate else 0 end)
          + sum(case when item_type = 'off_balance' then balance_aud * runoff_rate else 0 end) as total_outflows,
        sum(case when item_type = 'inflow' then balance_aud * inflow_rate else 0 end) as raw_inflows,
        sum(case when item_type = 'liability' then balance_aud * asf_factor else 0 end) as asf,
        sum(case when item_type = 'asset' then balance_aud * rsf_factor else 0 end)
          + sum(case when item_type = 'off_balance' then balance_aud * rsf_factor else 0 end) as rsf
    from joined
    group by reporting_date
)
"""

LIQUIDITY_SQL = _COMPONENTS_CTE + f"""
select
    reporting_date,
    level1_hqla,
    raw_level2a,
    raw_level2b,
    -- Step 1: cap Level 2B on its own, relative to Level 1 (BCBS238 par 51,
    -- Level 2B <= 15% of total HQLA, expressed as a ratio to Level 1 to
    -- avoid a circular definition of "total HQLA").
    least(raw_level2b, level1_hqla * {LEVEL_2B_TO_LEVEL_1_RATIO}) as adjusted_level2b,
    -- Step 2: cap combined Level 2 (2A + already-capped 2B), relative to
    -- Level 1 (Level 2 total <= 40% of total HQLA).
    least(
        raw_level2a + least(raw_level2b, level1_hqla * {LEVEL_2B_TO_LEVEL_1_RATIO}),
        level1_hqla * {LEVEL_2_TO_LEVEL_1_RATIO}
    ) as adjusted_level2,
    level1_hqla + least(
        raw_level2a + least(raw_level2b, level1_hqla * {LEVEL_2B_TO_LEVEL_1_RATIO}),
        level1_hqla * {LEVEL_2_TO_LEVEL_1_RATIO}
    ) as total_hqla,
    total_outflows,
    raw_inflows,
    least(raw_inflows, total_outflows * {INFLOW_CAP_RATIO}) as capped_inflows,
    total_outflows - least(raw_inflows, total_outflows * {INFLOW_CAP_RATIO}) as net_cash_outflow,
    (level1_hqla + least(
        raw_level2a + least(raw_level2b, level1_hqla * {LEVEL_2B_TO_LEVEL_1_RATIO}),
        level1_hqla * {LEVEL_2_TO_LEVEL_1_RATIO}
    )) / nullif(total_outflows - least(raw_inflows, total_outflows * {INFLOW_CAP_RATIO}), 0) as lcr,
    asf,
    rsf,
    asf / nullif(rsf, 0) as nsfr
from components
order by reporting_date
"""

# The bug this project's README documents: a single 40% cap applied to
# raw Level 2A + Level 2B, with no separate 15% sub-cap on Level 2B.
# Kept here deliberately (not deleted) as the fixture the regression
# test in tests/test_gold.py compares against.
NAIVE_HQLA_SQL = _COMPONENTS_CTE + f"""
select
    reporting_date,
    level1_hqla,
    least(raw_level2a + raw_level2b, level1_hqla * {LEVEL_2_TO_LEVEL_1_RATIO}) as naive_adjusted_level2,
    level1_hqla + least(raw_level2a + raw_level2b, level1_hqla * {LEVEL_2_TO_LEVEL_1_RATIO}) as naive_total_hqla
from components
order by reporting_date
"""


def build_gold(silver: pd.DataFrame) -> pd.DataFrame:
    factors = _category_factor_table()
    con = duckdb.connect()
    con.register("silver", silver)
    con.register("factors", factors)
    result = con.execute(LIQUIDITY_SQL).df()
    con.close()
    return result


def build_naive_hqla(silver: pd.DataFrame) -> pd.DataFrame:
    """Exposed for the regression test only, see NAIVE_HQLA_SQL docstring."""
    factors = _category_factor_table()
    con = duckdb.connect()
    con.register("silver", silver)
    con.register("factors", factors)
    result = con.execute(NAIVE_HQLA_SQL).df()
    con.close()
    return result


def write_gold(silver: pd.DataFrame, out_dir: Path) -> Path:
    gold = build_gold(silver)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "liquidity_ratios.parquet"
    gold.to_parquet(out_path, index=False)
    return out_path


if __name__ == "__main__":
    import sys

    silver_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/silver/balance_sheet.parquet")
    gold_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/gold")
    silver = pd.read_parquet(silver_path)
    out = write_gold(silver, gold_dir)
    print(f"Wrote liquidity ratios for {silver['reporting_date'].nunique()} dates to {out}")
