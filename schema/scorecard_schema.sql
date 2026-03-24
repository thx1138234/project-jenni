-- scorecard_schema.sql
-- College Scorecard — institution-level and program-level tables.
--
-- Join key to institution_master: unitid (IPEDS 6-digit ID).
-- All monetary values in nominal dollars as reported by the API.
-- NULL = not reported or not applicable for this institution/year.
-- Negative net price values are preserved (valid: aid exceeds sticker price).
-- Carnegie classification omitted — already in institution_master from IPEDS HD.
--
-- Field name reference: api.data.gov/ed/collegescorecard/v1/
-- Data dictionary: collegescorecard.ed.gov/assets/CollegeScorecardDataDictionary.xlsx

-- ---------------------------------------------------------------------------
-- scorecard_institution
-- Institution-level outcomes, costs, and aid data.
-- One row per institution per data year.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scorecard_institution (
    unitid              INTEGER NOT NULL,   -- IPEDS UNITID; FK to institution_master
    data_year           INTEGER NOT NULL,   -- academic year (fall start); "latest" resolves to this

    -- Enrollment
    student_size        INTEGER,            -- latest.student.size (headcount)
    enroll_undergrad    INTEGER,            -- latest.student.enrollment.undergrad_12_month
    enroll_grad         INTEGER,            -- latest.student.enrollment.grad_12_month

    -- Cost
    tuition_instate     INTEGER,            -- latest.cost.tuition.in_state
    tuition_outstate    INTEGER,            -- latest.cost.tuition.out_of_state
    avg_net_price_pub   INTEGER,            -- latest.cost.avg_net_price.public (public inst only)
    avg_net_price_priv  INTEGER,            -- latest.cost.avg_net_price.private (private inst only)

    -- Net price by income band — public institutions (ownership=1)
    -- NULL for private institutions; negative values valid (aid > cost)
    np_pub_0_30k        INTEGER,
    np_pub_30_48k       INTEGER,
    np_pub_48_75k       INTEGER,
    np_pub_75_110k      INTEGER,
    np_pub_110k_plus    INTEGER,

    -- Net price by income band — private NP and for-profit institutions (ownership=2,3)
    -- NULL for public institutions; negative values valid
    np_priv_0_30k       INTEGER,
    np_priv_30_48k      INTEGER,
    np_priv_48_75k      INTEGER,
    np_priv_75_110k     INTEGER,
    np_priv_110k_plus   INTEGER,

    -- Aid
    pell_grant_rate     REAL,               -- latest.aid.pell_grant_rate (0–1)
    federal_loan_rate   REAL,               -- latest.aid.federal_loan_rate (0–1)
    median_debt         INTEGER,            -- latest.aid.median_debt.completers.overall

    -- Outcomes
    completion_rate_4yr REAL,               -- latest.completion.completion_rate_4yr_150nt (0–1)
    completion_rate_2yr REAL,               -- latest.completion.completion_rate_less_than_4yr_150nt
    earnings_6yr_median INTEGER,            -- latest.earnings.6_yrs_after_entry.median
    earnings_10yr_median INTEGER,           -- latest.earnings.10_yrs_after_entry.median
    repayment_3yr       REAL,               -- latest.repayment.3_yr_repayment.overall

    PRIMARY KEY (unitid, data_year)
);

-- ---------------------------------------------------------------------------
-- scorecard_programs
-- Field-of-study level earnings and debt data.
-- One row per institution × CIP 4-digit code × credential level × data year.
-- Source: programs.cip_4_digit (underscore) nested fields in the Scorecard API.
-- Note: API only supports "latest" program data (year-prefix returns HTTP 500).
--       All rows loaded with the current data year; historical not available via API.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scorecard_programs (
    unitid              INTEGER NOT NULL,
    data_year           INTEGER NOT NULL,
    cip_code            TEXT    NOT NULL,   -- 4-digit CIP code (e.g., "5201")
    cip_title           TEXT,               -- program title
    credential_level    INTEGER NOT NULL,   -- 1=certificate, 2=associate, 3=bachelor's, etc.

    -- Earnings — 1yr and 2yr post-completion medians
    earnings_1yr_median INTEGER,
    earnings_2yr_median INTEGER,

    -- Debt at graduation
    debt_median         INTEGER,
    debt_mean           INTEGER,

    -- Count of students in cohort (for data suppression context)
    n_students          INTEGER,

    PRIMARY KEY (unitid, data_year, cip_code, credential_level)
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_sc_inst_unitid   ON scorecard_institution (unitid);
CREATE INDEX IF NOT EXISTS idx_sc_inst_year     ON scorecard_institution (data_year);
CREATE INDEX IF NOT EXISTS idx_sc_prog_unitid   ON scorecard_programs (unitid);
CREATE INDEX IF NOT EXISTS idx_sc_prog_cip      ON scorecard_programs (cip_code);
