"""Bronze -> silver: parse, type, and quality-gate the balance sheet."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quality_checks import run_quality_checks


def load_latest_bronze(bronze_dir: Path) -> pd.DataFrame:
    files = sorted(bronze_dir.glob("balance_sheet_*.jsonl"))
    if not files:
        raise FileNotFoundError(f"No bronze files found in {bronze_dir}")
    return pd.read_json(files[-1], lines=True)


def build_silver(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["reporting_date"] = pd.to_datetime(df["reporting_date"]).dt.date
    df["balance_aud"] = df["balance_aud"].astype(float)
    df["item_category"] = df["item_category"].astype(str)
    df["item_type"] = df["item_type"].astype(str)
    df["injected_scenario"] = df["injected_scenario"].fillna("baseline_healthy").astype(str)
    return df.sort_values(["reporting_date", "item_type", "item_category"]).reset_index(drop=True)


def write_silver(df: pd.DataFrame, out_dir: Path) -> Path:
    report = run_quality_checks(df)
    if not report.passed:
        raise ValueError(report.summary())

    silver = build_silver(df)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "balance_sheet.parquet"
    silver.to_parquet(out_path, index=False)
    return out_path


if __name__ == "__main__":
    import sys

    bronze_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/bronze")
    silver_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/silver")
    raw = load_latest_bronze(bronze_dir)
    out = write_silver(raw, silver_dir)
    print(f"Wrote {len(raw)} rows to {out}")
