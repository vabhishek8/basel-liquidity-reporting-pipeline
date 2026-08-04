import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from generate_balance_sheet import _fixed_baseline_items
from transform import build_silver, write_silver
import dataclasses


def _baseline_df():
    items = _fixed_baseline_items(__import__("datetime").date(2026, 1, 1), "baseline_healthy")
    return pd.DataFrame([dataclasses.asdict(i) for i in items])


def test_build_silver_types():
    silver = build_silver(_baseline_df())
    assert silver["balance_aud"].dtype.kind == "f"
    assert silver["item_category"].dtype == object
    assert not silver["injected_scenario"].isna().any()


def test_write_silver_rejects_bad_data(tmp_path):
    bad = _baseline_df()
    bad.loc[0, "balance_aud"] = -1.0
    with pytest.raises(ValueError):
        write_silver(bad, tmp_path)


def test_write_silver_roundtrip(tmp_path):
    out = write_silver(_baseline_df(), tmp_path)
    assert out.exists()
    reloaded = pd.read_parquet(out)
    assert len(reloaded) == 26  # 10 assets + 2 inflows + 12 liabilities + 2 off-balance

