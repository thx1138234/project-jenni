-- 990_schedule_d_schema.sql
-- IRS Form 990 Schedule D Part V — Endowment Funds
--
-- One row per filing (object_id is PRIMARY KEY).
-- TEOS/IRSx rows only — ProPublica API does not expose Schedule D detail.
--
-- Schedule D Part V reports 5 years of endowment activity (CY + 4 prior years).
-- This table captures only the current-year group (CYEndwmtFundGrp) for the
-- filing year, since prior-year groups overlap with adjacent filings.
--
-- Dollar breakdown columns (endowment_board_designated, endowment_restricted_perm,
-- endowment_restricted_temp, endowment_unrestricted) are calculated at load time
-- by multiplying the reported EOY percentages × endowment_eoy. These percentages
-- are reported on Schedule D Part V lines 3a–3c and sum to 100%.
-- Percentage fields (board_designated_pct etc.) are also stored as-reported.
--
-- Field sources (CYEndwmtFundGrp):
--   BeginningYearBalanceAmt     → endowment_boy
--   ContributionsAmt            → contributions_endowment
--   InvestmentEarningsOrLossesAmt → investment_return_endowment
--   GrantsOrScholarshipsAmt     → grants_from_endowment
--   OtherExpendituresAmt        → other_endowment_changes
--   AdministrativeExpensesAmt   → admin_expenses_endowment
--   EndYearBalanceAmt           → endowment_eoy
--   BoardDesignatedBalanceEOYPct → board_designated_pct
--   PrmnntEndowmentBalanceEOYPct → perm_restricted_pct
--   TermEndowmentBalanceEOYPct  → temp_restricted_pct

CREATE TABLE IF NOT EXISTS form990_schedule_d (
    object_id                   TEXT    PRIMARY KEY,  -- FK → form990_filings.object_id
    ein                         TEXT    NOT NULL,
    fiscal_year_end             INTEGER,

    -- Schedule D Part V — Endowment activity (current year)
    endowment_boy               INTEGER,  -- beginning of year balance
    contributions_endowment     INTEGER,  -- new contributions to endowment
    investment_return_endowment INTEGER,  -- investment earnings (losses)
    grants_from_endowment       INTEGER,  -- grants/scholarships paid from endowment
    other_endowment_changes     INTEGER,  -- other expenditures
    admin_expenses_endowment    INTEGER,  -- administrative expenses
    endowment_eoy               INTEGER,  -- end of year balance

    -- EOY breakdown percentages (lines 3a–3c, sum to 1.0)
    board_designated_pct        REAL,     -- quasi-endowment (board-designated)
    perm_restricted_pct         REAL,     -- permanently restricted
    temp_restricted_pct         REAL,     -- temporarily restricted (term endowment)

    -- Calculated EOY dollar breakdowns (pct × endowment_eoy)
    endowment_board_designated  INTEGER,
    endowment_restricted_perm   INTEGER,
    endowment_restricted_temp   INTEGER,
    endowment_unrestricted      INTEGER,  -- (1 - board - perm - temp) × eoy; residual

    -- Derived ratio (computed at load from form990_filings for same ein+fiscal_year_end)
    endowment_runway            REAL,   -- endowment_eoy / total_functional_expenses (years)

    -- Endowment spending analysis
    endowment_spending_rate     REAL,   -- grants_from_endowment / NULLIF(endowment_boy,0); NULL if grants_from_endowment <= 0
    stress_endowment            INTEGER, -- 1=spending_rate>0.07 (HIGH), 0=0.03-0.07 (normal), -1=<0.03 and endowment>$100M (likely routing artifact)

    -- Metadata
    data_source                 TEXT    DEFAULT 'irsx',
    loaded_at                   TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sched_d_ein       ON form990_schedule_d (ein);
CREATE INDEX IF NOT EXISTS idx_sched_d_year      ON form990_schedule_d (fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_sched_d_ein_year  ON form990_schedule_d (ein, fiscal_year_end);
