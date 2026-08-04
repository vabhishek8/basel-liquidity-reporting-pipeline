"""Bronze -> silver quality gate for the Basel liquidity balance sheet."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from factors import ASSET_CATEGORIES, INFLOW_CATEGORIES, LIABILITY_CATEGORIES, OFF_BALANCE_CATEGORIES

REQUIRED_COLUMNS = {"reporting_date", "item_category", "item_type", "balance_aud", "injected_scenario"}

VALID_ITEM_TYPES = {"asset", "inflow", "liability", "off_balance"}

CATEGORY_BY_TYPE = {
    "asset": set(ASSET_CATEGORIES),
    "inflow": set(INFLOW_CATEGORIES),
    "liability": set(LIABILITY_CATEGORIES),
    "off_balance": set(OFF_BALANCE_CATEGORIES),
}

# A materially negative or implausibly large single line item almost
# certainly indicates an upstream extraction bug, not a real balance.
BALANCE_BOUNDS = (0.0, 50_000_000_000.0)


@dataclass
class QualityIssue:
    check: str
    detail: str
    row_count: int = 0


@dataclass
class QualityReport:
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0

    def add(self, check: str, detail: str, row_count: int = 0) -> None:
        self.issues.append(QualityIssue(check, detail, row_count))

    def summary(self) -> str:
        if self.passed:
            return "Quality gate passed: no issues."
        lines = [f"Quality gate FAILED: {len(self.issues)} issue(s)."]
        for issue in self.issues:
            lines.append(f"  - [{issue.check}] {issue.detail} ({issue.row_count} row(s))")
        return "\n".join(lines)


def run_quality_checks(df: pd.DataFrame) -> QualityReport:
    report = QualityReport()

    missing_cols = REQUIRED_COLUMNS - set(df.columns)
    if missing_cols:
        report.add("schema", f"missing required columns: {sorted(missing_cols)}")
        return report  # further checks assume the schema is present

    null_counts = df[list(REQUIRED_COLUMNS)].isna().sum()
    for col, n in null_counts.items():
        if n > 0:
            report.add("nulls", f"column '{col}' has null values", int(n))

    bad_types = df.loc[~df["item_type"].isin(VALID_ITEM_TYPES)]
    if len(bad_types):
        report.add("domain", f"invalid item_type values: {sorted(bad_types['item_type'].unique())}", len(bad_types))

    for item_type, valid_cats in CATEGORY_BY_TYPE.items():
        subset = df.loc[df["item_type"] == item_type]
        bad_cats = subset.loc[~subset["item_category"].isin(valid_cats)]
        if len(bad_cats):
            report.add(
                "domain",
                f"invalid item_category for item_type='{item_type}': {sorted(bad_cats['item_category'].unique())}",
                len(bad_cats),
            )

    lo, hi = BALANCE_BOUNDS
    out_of_range = df.loc[(df["balance_aud"] < lo) | (df["balance_aud"] > hi)]
    if len(out_of_range):
        report.add("range", f"balance_aud outside plausible bounds [{lo:,.0f}, {hi:,.0f}]", len(out_of_range))

    dupes = df.duplicated(subset=["reporting_date", "item_category", "item_type"], keep=False)
    if dupes.any():
        report.add("duplicates", "duplicate (reporting_date, item_category, item_type) rows", int(dupes.sum()))

    # Every reporting date should carry a complete balance sheet: exactly
    # one row per defined category. A partial day is worse than no day.
    expected_categories = sum(len(v) for v in CATEGORY_BY_TYPE.values())
    per_date_counts = df.groupby("reporting_date").size()
    incomplete_dates = per_date_counts.loc[per_date_counts != expected_categories]
    if len(incomplete_dates):
        report.add(
            "completeness",
            f"reporting dates with != {expected_categories} line items: {list(incomplete_dates.index)}",
            len(incomplete_dates),
        )

    return report
