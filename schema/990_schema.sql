-- 990_schema.sql
-- IRS Form 990 — Parts VIII, IX, X, XI financial data.
--
-- One row per filing (unique object_id from TEOS index).
-- Join key to institution_master: ein (9-digit string, no hyphens).
-- fiscal_year_end joins to IPEDS: fiscal_year_end = survey_year + 1.
-- All monetary values in nominal dollars as filed. NULL = not reported.
-- NULL ≠ 0: institutions report $0 explicitly; NULL means field was absent.
--
-- Source: IRS TEOS portal (2019+) via IRSx; ProPublica API (2012–2018).
-- Validation: IRSx parse and ProPublica API must agree on total_revenue.

CREATE TABLE IF NOT EXISTS form990_filings (
    object_id               TEXT    PRIMARY KEY,  -- TEOS OBJECT_ID (e.g. "202301329349306830")
    ein                     TEXT    NOT NULL,      -- 9-digit EIN, zero-padded, no hyphens
    fiscal_year_end         INTEGER,               -- calendar year FY ends (e.g. 2023 for June 2023)
    org_name                TEXT,                  -- institution name as filed

    -- Part VIII — Statement of Revenue
    total_revenue           INTEGER,               -- CYTotalRevenueAmt (Part I line 12 / Part VIII total)
    contributions_grants    INTEGER,               -- TotalContributionsAmt
    program_service_revenue INTEGER,               -- TotalProgramServiceRevenueAmt
    investment_income       INTEGER,               -- InvestmentIncomeGrp.TotalRevenueColumnAmt
    net_gain_investments    INTEGER,               -- NetGainOrLossInvestmentsGrp.TotalRevenueColumnAmt
    other_revenue           INTEGER,               -- CYOtherRevenueAmt

    -- Part IX — Statement of Functional Expenses
    total_expenses          INTEGER,               -- CYTotalExpensesAmt (Part I line 17)
    total_program_expenses  INTEGER,               -- TotalProgramServiceExpensesAmt
    salaries_comp           INTEGER,               -- CompCurrentOfcrDirectorsGrp.TotalAmt (officer/director)
    other_salaries_wages    INTEGER,               -- OtherSalariesAndWagesGrp.TotalAmt
    pension_contributions   INTEGER,               -- PensionPlanContributionsGrp.TotalAmt
    other_employee_benefits INTEGER,               -- OtherEmployeeBenefitsGrp.TotalAmt
    payroll_taxes           INTEGER,               -- PayrollTaxesGrp.TotalAmt
    depreciation            INTEGER,               -- DepreciationDepletionGrp.TotalAmt
    interest_expense        INTEGER,               -- InterestGrp.TotalAmt
    occupancy               INTEGER,               -- OccupancyGrp.TotalAmt
    total_functional_expenses INTEGER,             -- TotalFunctionalExpensesGrp.TotalAmt

    -- Part X — Balance Sheet
    total_assets_boy        INTEGER,               -- TotalAssetsBOYAmt
    total_assets_eoy        INTEGER,               -- TotalAssetsEOYAmt
    total_liabilities_boy   INTEGER,               -- TotalLiabilitiesBOYAmt
    total_liabilities_eoy   INTEGER,               -- TotalLiabilitiesEOYAmt
    net_assets_boy          INTEGER,               -- NetAssetsOrFundBalancesBOYAmt
    net_assets_eoy          INTEGER,               -- NetAssetsOrFundBalancesEOYAmt
    cash_and_equivalents    INTEGER,               -- CashNonInterestBearingGrp.EOYAmt
    investments_securities  INTEGER,               -- InvestmentsPubTradedSecGrp.EOYAmt
    land_bldg_equip_net     INTEGER,               -- LandBldgEquipBasisNetGrp.EOYAmt

    -- Part XI — Reconciliation of Net Assets
    net_unrealized_gains    INTEGER,               -- NetUnrlzdGainsLossesInvstAmt
    other_changes_net_assets INTEGER,              -- OtherChangesInNetAssetsAmt
    reconciliation_surplus  INTEGER,               -- ReconcilationRevenueExpnssAmt (revenue - expenses)

    -- Metadata
    data_source             TEXT    DEFAULT 'irsx', -- 'irsx' or 'propublica'
    loaded_at               TEXT    DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_990_ein            ON form990_filings (ein);
CREATE INDEX IF NOT EXISTS idx_990_fiscal_year    ON form990_filings (fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_990_ein_year       ON form990_filings (ein, fiscal_year_end);
