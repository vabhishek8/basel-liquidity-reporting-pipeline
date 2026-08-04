"""Static Plotly dashboard for LCR/NSFR trend, HQLA composition, and
regulatory-minimum breach flags."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from factors import REGULATORY_MINIMUM

DARK_BG = "#0a0e14"
SURFACE = "#111722"
TEAL = "#4fd8c4"
AMBER = "#f2a541"
RED = "#e5766b"
TEXT = "#e8edf2"
MUTED = "#7d8a9c"

MANAGEMENT_BUFFER = 1.10  # banks typically target a buffer above the 100% regulatory floor


def _base_layout(title: str) -> dict:
    return dict(
        title=title,
        paper_bgcolor=DARK_BG,
        plot_bgcolor=SURFACE,
        font=dict(color=TEXT, family="Inter, system-ui, sans-serif"),
        margin=dict(l=60, r=30, t=60, b=50),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )


def _ratio_trend_figure(gold: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": False}]])
    fig.add_trace(go.Scatter(
        x=gold["reporting_date"], y=gold["lcr"] * 100, name="LCR %",
        line=dict(color=TEAL, width=2), mode="lines",
    ))
    fig.add_trace(go.Scatter(
        x=gold["reporting_date"], y=gold["nsfr"] * 100, name="NSFR %",
        line=dict(color=AMBER, width=2), mode="lines",
    ))
    fig.add_hline(y=100, line=dict(color=RED, width=1, dash="dash"),
                   annotation_text="100% regulatory minimum", annotation_font_color=RED)
    fig.add_hline(y=MANAGEMENT_BUFFER * 100, line=dict(color=MUTED, width=1, dash="dot"),
                   annotation_text="110% management buffer", annotation_font_color=MUTED)
    fig.update_layout(**_base_layout("LCR & NSFR, daily"))
    fig.update_yaxes(title="Ratio (%)", gridcolor="#1c2530")
    fig.update_xaxes(gridcolor="#1c2530")
    return fig


def _hqla_composition_figure(gold: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=gold["reporting_date"], y=gold["level1_hqla"], name="Level 1",
                              stackgroup="hqla", line=dict(width=0.5, color=TEAL)))
    fig.add_trace(go.Scatter(x=gold["reporting_date"], y=gold["adjusted_level2"], name="Level 2 (adjusted)",
                              stackgroup="hqla", line=dict(width=0.5, color=AMBER)))
    fig.update_layout(**_base_layout("HQLA composition, adjusted for haircuts and caps"))
    fig.update_yaxes(title="AUD", gridcolor="#1c2530")
    fig.update_xaxes(gridcolor="#1c2530")
    return fig


def _breach_table_html(gold: pd.DataFrame) -> str:
    breaches = gold.loc[(gold["lcr"] < REGULATORY_MINIMUM) | (gold["nsfr"] < REGULATORY_MINIMUM)].copy()
    if breaches.empty:
        return "<p style='color:#7d8a9c'>No regulatory-minimum breaches in this reporting window.</p>"
    breaches["lcr_pct"] = (breaches["lcr"] * 100).round(1)
    breaches["nsfr_pct"] = (breaches["nsfr"] * 100).round(1)
    rows = "".join(
        f"<tr><td>{row.reporting_date}</td>"
        f"<td style='color:{RED if row.lcr_pct < 100 else TEXT}'>{row.lcr_pct}</td>"
        f"<td style='color:{RED if row.nsfr_pct < 100 else TEXT}'>{row.nsfr_pct}</td></tr>"
        for row in breaches.itertuples()
    )
    return f"""
    <table style="width:100%;border-collapse:collapse;color:{TEXT};font-family:Inter,system-ui,sans-serif;">
      <thead><tr style="text-align:left;border-bottom:1px solid #1c2530;">
        <th style="padding:8px">Reporting date</th><th style="padding:8px">LCR</th><th style="padding:8px">NSFR</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def render(gold: pd.DataFrame, out_path: Path) -> Path:
    trend_html = _ratio_trend_figure(gold).to_html(full_html=False, include_plotlyjs="cdn")
    hqla_html = _hqla_composition_figure(gold).to_html(full_html=False, include_plotlyjs=False)
    breach_html = _breach_table_html(gold)

    latest = gold.iloc[-1]
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Basel III LCR / NSFR Liquidity Reporting</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ background:{DARK_BG}; color:{TEXT}; font-family: Inter, system-ui, sans-serif; margin:0; padding:32px; }}
  h1 {{ font-size:1.4rem; }}
  .stats {{ display:flex; gap:20px; margin:20px 0 32px; flex-wrap:wrap; }}
  .stat {{ background:{SURFACE}; border:1px solid #1c2530; border-radius:10px; padding:18px 22px; min-width:180px; }}
  .stat .label {{ font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; color:{MUTED}; }}
  .stat .value {{ font-size:1.6rem; font-weight:700; margin-top:4px; }}
  section {{ margin-bottom:36px; }}
  a {{ color:{TEAL}; }}
</style>
</head>
<body>
  <h1>Basel III Liquidity Reporting: LCR &amp; NSFR</h1>
  <p style="color:{MUTED}">Synthetic single-entity balance sheet, generated and scored on a daily schedule. See the repository README for the calculation methodology and its regulatory basis.</p>
  <div class="stats">
    <div class="stat"><div class="label">Latest LCR</div><div class="value" style="color:{TEAL if latest['lcr']>=1 else RED}">{latest['lcr']*100:.1f}%</div></div>
    <div class="stat"><div class="label">Latest NSFR</div><div class="value" style="color:{AMBER if latest['nsfr']>=1 else RED}">{latest['nsfr']*100:.1f}%</div></div>
    <div class="stat"><div class="label">Reporting dates</div><div class="value">{len(gold)}</div></div>
  </div>
  <section>{trend_html}</section>
  <section>{hqla_html}</section>
  <section>
    <h2 style="font-size:1.1rem;">Regulatory-minimum breaches</h2>
    {breach_html}
  </section>
</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path


if __name__ == "__main__":
    import sys

    gold_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/gold/liquidity_ratios.parquet")
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs/index.html")
    gold = pd.read_parquet(gold_path)
    out = render(gold, out_path)
    print(f"Wrote dashboard to {out}")
