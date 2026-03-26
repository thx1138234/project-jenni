"""
ingestion/990/field_map.py
--------------------------
Explicit field mappings from each data source to the form990_filings schema.

Two sources feed the same table:
  - IRSx (TEOS portal, FY2019+): schema/990_schema.sql via parser.py
  - ProPublica API (FY2012–FY2018): ingestion/990/propublica_loader.py

Both must produce identical column names, data types, and NULL semantics.

Part VIII — Revenue line structure (IRS Form 990):
  Line 1  contributions and grants
  Line 2  program service revenue
  Line 3  investment income (dividends, interest, similar amounts)
  Line 4  net gain/loss from sales of assets
  Line 5  royalties
  Line 6  net rental income/loss
  Line 7  net fundraising events income/loss
  Line 8  net gaming income/loss
  Line 9  net income/loss from sales of inventory
  Line 11 other revenue
  Line 12 total revenue

Our schema maps:
  total_revenue           = line 12 total
  contributions_grants    = line 1 total
  program_service_revenue = line 2 total
  investment_income       = line 3 total (interest, dividends, tax-exempt bond interest)
  net_gain_investments    = line 4 total
  other_revenue           = lines 5+6+7+8+9+11 combined
                            (royalties, rent, fundraising, gaming, inventory, misc)
"""

# ---------------------------------------------------------------------------
# IRSx field mapping (reference — parser.py implements these directly)
# ---------------------------------------------------------------------------
# IRSx schedule key (IRS990) → schema column
# Composite fields (Grp) require _grp() helper: d.get(key) → int via TotalAmt or EOYAmt

IRSX_DIRECT = {
    # Part I — Organizational Summary (form_type extracted via f.get_type(), not a schedule key)
    "TotalEmployeeCnt":                 "total_employee_count",
    # Part VIII
    "CYTotalRevenueAmt":                "total_revenue",
    "TotalContributionsAmt":            "contributions_grants",
    "TotalProgramServiceRevenueAmt":    "program_service_revenue",
    "CYOtherRevenueAmt":                "other_revenue",
    # Part IX
    "CYTotalExpensesAmt":               "total_expenses",
    "TotalProgramServiceExpensesAmt":   "total_program_expenses",
    # Part X
    "TotalAssetsBOYAmt":                "total_assets_boy",
    "TotalAssetsEOYAmt":                "total_assets_eoy",
    "TotalLiabilitiesBOYAmt":           "total_liabilities_boy",
    "TotalLiabilitiesEOYAmt":           "total_liabilities_eoy",
    "NetAssetsOrFundBalancesBOYAmt":    "net_assets_boy",
    "NetAssetsOrFundBalancesEOYAmt":    "net_assets_eoy",
    # Part XI
    "NetUnrlzdGainsLossesInvstAmt":     "net_unrealized_gains",
    "OtherChangesInNetAssetsAmt":       "other_changes_net_assets",
    "ReconcilationRevenueExpnssAmt":    "reconciliation_surplus",
}

# IRSx Grp keys → (schedule_key, sub_key, schema_column)
IRSX_GRP = [
    # Part VIII
    ("InvestmentIncomeGrp",              "TotalRevenueColumnAmt", "investment_income"),
    ("NetGainOrLossInvestmentsGrp",      "TotalRevenueColumnAmt", "net_gain_investments"),
    # Part IX
    ("CompCurrentOfcrDirectorsGrp",      "TotalAmt",              "salaries_comp"),
    ("OtherSalariesAndWagesGrp",         "TotalAmt",              "other_salaries_wages"),
    ("PensionPlanContributionsGrp",      "TotalAmt",              "pension_contributions"),
    ("OtherEmployeeBenefitsGrp",         "TotalAmt",              "other_employee_benefits"),
    ("PayrollTaxesGrp",                  "TotalAmt",              "payroll_taxes"),
    ("DepreciationDepletionGrp",         "TotalAmt",              "depreciation"),
    ("InterestGrp",                      "TotalAmt",              "interest_expense"),
    ("OccupancyGrp",                     "TotalAmt",              "occupancy"),
    ("TotalFunctionalExpensesGrp",       "TotalAmt",              "total_functional_expenses"),
    # Part X
    ("CashNonInterestBearingGrp",        "EOYAmt",                "cash_and_equivalents"),
    ("InvestmentsPubTradedSecGrp",       "EOYAmt",                "investments_securities"),
    ("LandBldgEquipBasisNetGrp",         "EOYAmt",                "land_bldg_equip_net"),
]

# IRSx fallback for salaries_comp when Grp field is absent
IRSX_SALARIES_FALLBACK = "CYSalariesCompEmpBnftPaidAmt"


# ---------------------------------------------------------------------------
# ProPublica API field mapping
# ---------------------------------------------------------------------------
# Source: /api/v2/organizations/{EIN}.json → filings_with_data[n]
# All fields are present in every filings_with_data entry (0 when not reported).
#
# ProPublica exposes a subset of 990 line items.
# NULL in the schema means the field is not available from this source.

# Direct 1:1 mappings: ProPublica key → schema column
PROPUBLICA_DIRECT = {
    "totrevenue":       "total_revenue",
    "totcntrbgfts":     "contributions_grants",
    "totprgmrevnue":    "program_service_revenue",
    "netgnls":          "net_gain_investments",
    "totfuncexpns":     "total_functional_expenses",
    "compnsatncurrofcr":"salaries_comp",
    "othrsalwages":     "other_salaries_wages",
    "payrolltx":        "payroll_taxes",
    "totassetsend":     "total_assets_eoy",
    "totliabend":       "total_liabilities_eoy",
    "totnetassetend":   "net_assets_eoy",
}

# Composite fields — schema column built by summing multiple ProPublica keys.
#
# investment_income (Part VIII line 3 total):
#   invstmntinc      — interest, dividends, and similar investment income
#   txexmptbndsproceeds — interest on tax-exempt bonds (line 3b sub-item)
#
# other_revenue (Part VIII lines 5+6+7+8+9+11):
#   royaltsinc       — line 5: net royalties
#   netrntlinc       — line 6c: net rental income/loss
#   netincfndrsng    — line 7c: net fundraising events income/loss
#   netincgaming     — line 8c: net gaming income/loss
#   netincsales      — line 9c: net income/loss from sales of inventory
#   miscrevtot11e    — line 11e: other revenue subtotal
#
# Verified: for all 5 validation institutions across FY2012–FY2019,
# contributions + program_service + investment_income + net_gain + other_revenue
# == totrevenue (zero residual).
PROPUBLICA_COMPOSITE = {
    "investment_income": ["invstmntinc", "txexmptbndsproceeds"],
    "other_revenue":     ["royaltsinc", "netrntlinc", "netincfndrsng",
                          "netincgaming", "netincsales", "miscrevtot11e"],
}

# Schema columns that are NOT available from ProPublica (will be NULL):
PROPUBLICA_NULL_COLUMNS = [
    "total_expenses",           # CYTotalExpensesAmt — Part I line 17 not exposed
    "total_program_expenses",   # TotalProgramServiceExpensesAmt — not exposed
    "pension_contributions",    # PensionPlanContributionsGrp — not exposed
    "other_employee_benefits",  # OtherEmployeeBenefitsGrp — not exposed
    "depreciation",             # DepreciationDepletionGrp — not exposed
    "interest_expense",         # InterestGrp — not exposed
    "occupancy",                # OccupancyGrp — not exposed
    "total_assets_boy",         # TotalAssetsBOYAmt — not exposed
    "total_liabilities_boy",    # TotalLiabilitiesBOYAmt — not exposed
    "net_assets_boy",           # NetAssetsOrFundBalancesBOYAmt — not exposed
    "cash_and_equivalents",     # CashNonInterestBearingGrp — not exposed
    "investments_securities",   # InvestmentsPubTradedSecGrp — not exposed
    "land_bldg_equip_net",      # LandBldgEquipBasisNetGrp — not exposed
    "net_unrealized_gains",     # NetUnrlzdGainsLossesInvstAmt — not exposed
    "other_changes_net_assets", # OtherChangesInNetAssetsAmt — not exposed
    "reconciliation_surplus",   # ReconcilationRevenueExpnssAmt — not exposed
]
