-- 990_part_ix_schema.sql
-- IRS Form 990 Part IX — Statement of Functional Expenses
--
-- One row per TEOS/IRSx filing. NULL for ProPublica rows by design —
-- ProPublica API does not expose functional column breakdowns.
--
-- Columns B/C/D = Program Services / Management & General / Fundraising.
-- Column A totals live in form990_filings.total_functional_expenses (join on object_id).
--
-- Phase A fields (original — lines 12, 14, 25 + key fee lines):
--   Line 25 — Total functional expenses (cols B, C, D)
--   Line 12 — Advertising and promotion (cols B, C, D)
--   Line 14 — Information technology (cols B, C, D)
--   Line 11e — Professional fundraising service fees (TotalAmt only)
--   Line 11f — Investment management fees (TotalAmt only)
--
-- Phase B fields (all remaining lines 1–24, each with cols B, C, D):
--   Prefixed ln01_ through ln24_ to distinguish from Phase A legacy names.
--   Lines 12, 14, 25 intentionally omitted from Phase B (covered by Phase A).
--   Lines 11e, 11f: TotalAmt in Phase A; B/C/D in Phase B (ln11e_/ln11f_ prefix).
--
-- Calculated ratios stored at load time (require form990_filings join):
--   prog_services_pct      = total_prog_services / total_functional_expenses
--   overhead_ratio         = (total_mgmt_general + total_fundraising) / total_functional_expenses
--   fundraising_efficiency = total_fundraising / contributions_grants

CREATE TABLE IF NOT EXISTS form990_part_ix (
    object_id               TEXT    PRIMARY KEY,  -- FK → form990_filings.object_id
    ein                     TEXT    NOT NULL,
    fiscal_year_end         INTEGER,

    -- ── Phase A: Lines 25, 12, 14, 11e, 11f (legacy column names) ─────────

    -- Line 25 — Total functional expenses by column
    total_prog_services     INTEGER,              -- col B: program services
    total_mgmt_general      INTEGER,              -- col C: management & general
    total_fundraising_exp   INTEGER,              -- col D: fundraising

    -- Line 12 — Advertising and promotion
    advertising_prog        INTEGER,              -- col B
    advertising_mgmt        INTEGER,              -- col C
    advertising_fundraising INTEGER,              -- col D

    -- Line 14 — Information technology
    it_prog                 INTEGER,              -- col B
    it_mgmt                 INTEGER,              -- col C
    it_fundraising          INTEGER,              -- col D

    -- Line 11e — Professional fundraising service fees (TotalAmt; B/C/D in Phase B)
    prof_fundraising_fees   INTEGER,
    -- Line 11f — Investment management fees (TotalAmt; B/C/D in Phase B)
    invest_mgmt_fees        INTEGER,

    -- Calculated ratios (NULL if denominator is NULL or zero)
    prog_services_pct       REAL,
    overhead_ratio          REAL,
    fundraising_efficiency  REAL,

    -- ── Phase B: Lines 1–11d, 11e/f cols, 11g, 13, 15–24 ────────────────
    -- Naming: ln{line}_{shortname}_{prog|mgmt|fundraising}

    -- Line 1 — Grants and other assistance to domestic orgs and governments
    ln01_grants_govts_prog          INTEGER,
    ln01_grants_govts_mgmt          INTEGER,
    ln01_grants_govts_fundraising   INTEGER,

    -- Line 2 — Grants and other assistance to domestic individuals
    ln02_grants_indiv_prog          INTEGER,
    ln02_grants_indiv_mgmt          INTEGER,
    ln02_grants_indiv_fundraising   INTEGER,

    -- Line 3 — Grants and other assistance to foreign orgs/individuals
    ln03_grants_foreign_prog        INTEGER,
    ln03_grants_foreign_mgmt        INTEGER,
    ln03_grants_foreign_fundraising INTEGER,

    -- Line 4 — Benefits paid to or for members
    ln04_member_benefits_prog        INTEGER,
    ln04_member_benefits_mgmt        INTEGER,
    ln04_member_benefits_fundraising INTEGER,

    -- Line 5 — Compensation of current officers, directors, trustees, key employees
    ln05_officer_comp_prog          INTEGER,
    ln05_officer_comp_mgmt          INTEGER,
    ln05_officer_comp_fundraising   INTEGER,

    -- Line 6 — Compensation not included above, to disqualified persons
    ln06_disqualified_comp_prog          INTEGER,
    ln06_disqualified_comp_mgmt          INTEGER,
    ln06_disqualified_comp_fundraising   INTEGER,

    -- Line 7 — Other salaries and wages
    ln07_other_salaries_prog        INTEGER,
    ln07_other_salaries_mgmt        INTEGER,
    ln07_other_salaries_fundraising INTEGER,

    -- Line 8 — Pension plan accruals and contributions
    ln08_pension_prog               INTEGER,
    ln08_pension_mgmt               INTEGER,
    ln08_pension_fundraising        INTEGER,

    -- Line 9 — Other employee benefits
    ln09_emp_benefits_prog          INTEGER,
    ln09_emp_benefits_mgmt          INTEGER,
    ln09_emp_benefits_fundraising   INTEGER,

    -- Line 10 — Payroll taxes
    ln10_payroll_taxes_prog         INTEGER,
    ln10_payroll_taxes_mgmt         INTEGER,
    ln10_payroll_taxes_fundraising  INTEGER,

    -- Line 11a — Fees for services: management
    ln11a_fees_mgmt_svc_prog        INTEGER,
    ln11a_fees_mgmt_svc_mgmt        INTEGER,
    ln11a_fees_mgmt_svc_fundraising INTEGER,

    -- Line 11b — Fees for services: legal
    ln11b_fees_legal_prog           INTEGER,
    ln11b_fees_legal_mgmt           INTEGER,
    ln11b_fees_legal_fundraising    INTEGER,

    -- Line 11c — Fees for services: accounting
    ln11c_fees_accounting_prog          INTEGER,
    ln11c_fees_accounting_mgmt          INTEGER,
    ln11c_fees_accounting_fundraising   INTEGER,

    -- Line 11d — Fees for services: lobbying
    ln11d_fees_lobbying_prog        INTEGER,
    ln11d_fees_lobbying_mgmt        INTEGER,
    ln11d_fees_lobbying_fundraising INTEGER,

    -- Line 11e — Professional fundraising fees: functional columns
    ln11e_fees_prof_fund_prog        INTEGER,
    ln11e_fees_prof_fund_mgmt        INTEGER,
    ln11e_fees_prof_fund_fundraising INTEGER,

    -- Line 11f — Investment management fees: functional columns
    ln11f_fees_invest_mgmt_prog        INTEGER,
    ln11f_fees_invest_mgmt_mgmt        INTEGER,
    ln11f_fees_invest_mgmt_fundraising INTEGER,

    -- Line 11g — Fees for services: other
    ln11g_fees_other_prog           INTEGER,
    ln11g_fees_other_mgmt           INTEGER,
    ln11g_fees_other_fundraising    INTEGER,

    -- Line 13 — Office expenses
    ln13_office_exp_prog            INTEGER,
    ln13_office_exp_mgmt            INTEGER,
    ln13_office_exp_fundraising     INTEGER,

    -- Line 15 — Royalties
    ln15_royalties_prog             INTEGER,
    ln15_royalties_mgmt             INTEGER,
    ln15_royalties_fundraising      INTEGER,

    -- Line 16 — Occupancy
    ln16_occupancy_prog             INTEGER,
    ln16_occupancy_mgmt             INTEGER,
    ln16_occupancy_fundraising      INTEGER,

    -- Line 17 — Travel
    ln17_travel_prog                INTEGER,
    ln17_travel_mgmt                INTEGER,
    ln17_travel_fundraising         INTEGER,

    -- Line 18 — Travel/entertainment for public officials
    ln18_travel_officials_prog          INTEGER,
    ln18_travel_officials_mgmt          INTEGER,
    ln18_travel_officials_fundraising   INTEGER,

    -- Line 19 — Conferences, conventions, and meetings
    ln19_conferences_prog           INTEGER,
    ln19_conferences_mgmt           INTEGER,
    ln19_conferences_fundraising    INTEGER,

    -- Line 20 — Interest
    ln20_interest_prog              INTEGER,
    ln20_interest_mgmt              INTEGER,
    ln20_interest_fundraising       INTEGER,

    -- Line 21 — Payments to affiliates
    ln21_pmts_affiliates_prog           INTEGER,
    ln21_pmts_affiliates_mgmt           INTEGER,
    ln21_pmts_affiliates_fundraising    INTEGER,

    -- Line 22 — Depreciation, depletion, and amortization
    ln22_depreciation_prog          INTEGER,
    ln22_depreciation_mgmt          INTEGER,
    ln22_depreciation_fundraising   INTEGER,

    -- Line 23 — Insurance
    ln23_insurance_prog             INTEGER,
    ln23_insurance_mgmt             INTEGER,
    ln23_insurance_fundraising      INTEGER,

    -- Line 24 — All other expenses (aggregate of 24a–24e; per-line descriptions not stored)
    ln24_other_exp_prog             INTEGER,
    ln24_other_exp_mgmt             INTEGER,
    ln24_other_exp_fundraising      INTEGER,

    -- Metadata
    loaded_at               TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_partix_ein       ON form990_part_ix (ein);
CREATE INDEX IF NOT EXISTS idx_partix_year      ON form990_part_ix (fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_partix_ein_year  ON form990_part_ix (ein, fiscal_year_end);
