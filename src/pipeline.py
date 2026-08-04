"""Orchestrates the full run: generate -> silver -> gold -> dashboard."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from generate_balance_sheet import BASELINE_DAYS, generate_history, write_bronze
from transform import load_latest_bronze, write_silver
from gold import write_gold
import pandas as pd
from dashboard import render

ROOT = Path(__file__).resolve().parent.parent
BRONZE_DIR = ROOT / "data" / "bronze"
SILVER_DIR = ROOT / "data" / "silver"
GOLD_DIR = ROOT / "data" / "gold"
DOCS_PATH = ROOT / "docs" / "index.html"


def run() -> None:
    daily_seed = int(date.today().strftime("%Y%m%d"))
    start_date = date.today() - timedelta(days=BASELINE_DAYS - 1)

    items = generate_history(start_date, BASELINE_DAYS, seed=daily_seed)
    bronze_path = write_bronze(items, BRONZE_DIR)
    print(f"[1/4] bronze: {len(items)} line items -> {bronze_path}")

    raw = load_latest_bronze(BRONZE_DIR)
    silver_path = write_silver(raw, SILVER_DIR)
    print(f"[2/4] silver: quality gate passed -> {silver_path}")

    silver = pd.read_parquet(silver_path)
    gold_path = write_gold(silver, GOLD_DIR)
    print(f"[3/4] gold: liquidity ratios -> {gold_path}")

    gold = pd.read_parquet(gold_path)
    docs_path = render(gold, DOCS_PATH)
    print(f"[4/4] dashboard -> {docs_path}")


if __name__ == "__main__":
    run()
