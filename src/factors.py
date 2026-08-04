"""
Regulatory factor tables for Basel III LCR and NSFR calculations.

Simplified for a synthetic, single-entity Australian retail/wholesale bank,
structurally consistent with APRA Prudential Standard APS 210 (Liquidity)
and the underlying BCBS LCR (BCBS238) and NSFR (BCBS295) standards. These
factors are illustrative, not a production regulatory reference: APRA's
actual runoff/ASF/RSF factors carry additional counterparty and product
nuance not modelled here. Do not use this for an actual regulatory return.

Every category below maps to one bronze line-item row per reporting date.
"""

# ---------------------------------------------------------------------------
# LCR: High-Quality Liquid Assets (HQLA)
# ---------------------------------------------------------------------------
# haircut: fraction deducted from face value to get the "adjusted" HQLA value
# hqla_level: "L1" (no cap), "L2A" (sub-cap via 40% total-Level-2 rule),
#             "L2B" (sub-cap via both the 15% Level-2B rule and the 40% rule)
# rsf_factor: NSFR Required Stable Funding weight for holding this asset

ASSET_CATEGORIES = {
    "cash_reserves": {
        "label": "Cash & RBA exchange settlement balances",
        "hqla_level": "L1", "haircut": 0.00, "rsf_factor": 0.00,
    },
    "ags_semis": {
        "label": "Commonwealth & semi-government securities",
        "hqla_level": "L1", "haircut": 0.00, "rsf_factor": 0.05,
    },
    "l2a_securities": {
        "label": "Level 2A securities (AAA covered bonds, PSE, GSE)",
        "hqla_level": "L2A", "haircut": 0.15, "rsf_factor": 0.15,
    },
    "l2b_corporate_bonds": {
        "label": "Level 2B corporate bonds (A+ to BBB-)",
        "hqla_level": "L2B", "haircut": 0.50, "rsf_factor": 0.50,
    },
    "l2b_equities": {
        "label": "Level 2B major-index listed equities",
        "hqla_level": "L2B", "haircut": 0.50, "rsf_factor": 0.50,
    },
    "residential_mortgages": {
        "label": "Performing residential mortgages",
        "hqla_level": None, "haircut": 0.00, "rsf_factor": 0.65,
    },
    "retail_loans_other": {
        "label": "Other retail & SME loans",
        "hqla_level": None, "haircut": 0.00, "rsf_factor": 0.85,
    },
    "wholesale_loans_lt1y": {
        "label": "Wholesale/corporate loans, <1y residual maturity",
        "hqla_level": None, "haircut": 0.00, "rsf_factor": 0.50,
    },
    "wholesale_loans_gt1y": {
        "label": "Wholesale/corporate loans, >=1y residual maturity",
        "hqla_level": None, "haircut": 0.00, "rsf_factor": 0.85,
    },
    "other_assets": {
        "label": "Other assets (fixed assets, goodwill, prepayments)",
        "hqla_level": None, "haircut": 0.00, "rsf_factor": 1.00,
    },
}

# Contractual amounts due within 30 days, reported as their own lines
# (this is how LCR returns actually report inflows: as a distinct
# "amounts receivable in the next 30 days" schedule, not derived from
# the stock loan balance).
INFLOW_CATEGORIES = {
    "inflows_retail_30d": {
        "label": "Retail/SME repayments contractually due <=30d",
        "inflow_rate": 0.50,
    },
    "inflows_wholesale_30d": {
        "label": "Wholesale loan/security repayments contractually due <=30d",
        "inflow_rate": 1.00,
    },
}

# ---------------------------------------------------------------------------
# LCR outflows (runoff_rate) and NSFR Available Stable Funding (asf_factor)
# ---------------------------------------------------------------------------
LIABILITY_CATEGORIES = {
    "retail_deposits_stable": {
        "label": "Retail deposits, insured & transactional (stable)",
        "runoff_rate": 0.05, "asf_factor": 0.95,
    },
    "retail_deposits_less_stable": {
        "label": "Retail deposits, less stable",
        "runoff_rate": 0.10, "asf_factor": 0.90,
    },
    "sme_deposits_stable": {
        "label": "SME/small-business deposits (stable)",
        "runoff_rate": 0.05, "asf_factor": 0.95,
    },
    "operational_deposits": {
        "label": "Wholesale operational deposits (clearing/custody)",
        "runoff_rate": 0.25, "asf_factor": 0.50,
    },
    "nonfin_corporate_funding_lt1y": {
        "label": "Non-financial corporate wholesale funding, <1y",
        "runoff_rate": 0.40, "asf_factor": 0.50,
    },
    "financial_institution_funding_lt1y": {
        "label": "Funding from banks & other financial institutions, <1y",
        "runoff_rate": 1.00, "asf_factor": 0.00,
    },
    "secured_funding_l1": {
        "label": "Secured funding (repo) backed by Level 1 collateral",
        "runoff_rate": 0.00, "asf_factor": 0.00,
    },
    "secured_funding_l2a": {
        "label": "Secured funding (repo) backed by Level 2A collateral",
        "runoff_rate": 0.15, "asf_factor": 0.00,
    },
    "secured_funding_other": {
        "label": "Secured funding (repo) backed by non-HQLA collateral",
        "runoff_rate": 0.50, "asf_factor": 0.00,
    },
    "wholesale_debt_gt1y": {
        "label": "Term wholesale debt, >=1y residual maturity",
        "runoff_rate": 0.00, "asf_factor": 1.00,
    },
    "tier1_tier2_capital": {
        "label": "Tier 1 & Tier 2 regulatory capital",
        "runoff_rate": 0.00, "asf_factor": 1.00,
    },
    "other_liabilities": {
        "label": "Other liabilities & provisions",
        "runoff_rate": 0.00, "asf_factor": 0.00,
    },
}

# Off-balance-sheet commitments: runoff applies to the undrawn amount.
OFF_BALANCE_CATEGORIES = {
    "committed_credit_facilities_corp": {
        "label": "Undrawn committed credit facilities to corporates",
        "runoff_rate": 0.10, "rsf_factor": 0.05,
    },
    "committed_liquidity_facilities_fi": {
        "label": "Undrawn committed liquidity facilities to other FIs",
        "runoff_rate": 0.30, "rsf_factor": 0.05,
    },
}

# LCR inflow cap: total inflows cannot offset more than this fraction of
# total outflows (BCBS238 par 143 / APS 210).
INFLOW_CAP_RATIO = 0.75

# Level 2 asset caps, expressed the way BCBS238 par 51 actually specifies
# them: as ratios to Adjusted Level 1, to keep the calculation sequential
# and non-circular (see src/gold.py for why this order of operations is
# not optional).
LEVEL_2B_TO_LEVEL_1_RATIO = 15 / 85   # Level 2B <= 15% of total HQLA
LEVEL_2_TO_LEVEL_1_RATIO = 2 / 3      # Level 1+2 total: Level 2 <= 40% of total HQLA

REGULATORY_MINIMUM = 1.00   # 100%, APRA APS 210 / BCBS238 & BCBS295 floor
