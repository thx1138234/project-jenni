-- ipeds_e12_schema.sql
-- IPEDS EFIA (12-Month Enrollment) — FTE and credit hour counts
--
-- One row per institution per survey year.
-- survey_year = fall start year (IPEDS convention: AY 2022-23 → survey_year=2022).
-- Source files: EFIA{year}.csv (2012+), downloaded to data/raw/ipeds_csv/E12/.
--
-- FTE calculation basis (NCES methodology):
--   ugfte12  = EFTEUG  = undergraduate credit hours / 30
--   grfte12  = EFTEGD  = graduate credit hours / 24
--   dpp_fte12 = FTEDPP = doctoral/professional practice credit hours / 24
--   fte12    = ugfte12 + grfte12 + dpp_fte12  (NULL if all three are NULL)
--
-- fte12 is THE critical field for all per-student ratio calculations:
--   instruction_exp_per_fte = ipeds_finance.exp_instruction / ipeds_e12.fte12
--   endowment_per_fte       = form990_schedule_d.endowment_eoy / ipeds_e12.fte12
--
-- Note: Headcount (ug12, gr12, total12) is NOT available in EFIA format.
--   ug_credit_hrs (CDACTUA) and gr_credit_hrs (CDACTGA) are total 12-month
--   credit hours — the raw input for FTE calculation, not headcounts.
--
-- acttype codes: 1=credit only, 2=credit+non-credit, 3=non-credit only, -2=N/A.
--   Filter to acttype IN (1,2) for per-student ratio calculations.
--   acttype=3 institutions report no credit instruction.

CREATE TABLE IF NOT EXISTS ipeds_e12 (
    unitid          INTEGER NOT NULL,
    survey_year     INTEGER NOT NULL,

    -- 12-month credit hour totals (raw inputs for FTE)
    ug_credit_hrs   INTEGER,    -- CDACTUA: total undergraduate credit hours, 12-month
    gr_credit_hrs   INTEGER,    -- CDACTGA: total graduate credit hours, 12-month

    -- 12-month FTE (NCES calculated: credit hrs / 30 for UG, / 24 for grad)
    ugfte12         INTEGER,    -- EFTEUG: undergraduate FTE
    grfte12         INTEGER,    -- EFTEGD: graduate FTE
    dpp_fte12       INTEGER,    -- FTEDPP: doctoral/professional practice FTE
    fte12           INTEGER,    -- computed: ugfte12 + grfte12 + dpp_fte12

    -- Reporting type
    acttype         INTEGER,    -- 1=credit only, 2=credit+non-credit, 3=non-credit, -2=N/A

    loaded_at       TEXT DEFAULT (datetime('now')),

    PRIMARY KEY (unitid, survey_year)
);

CREATE INDEX IF NOT EXISTS idx_e12_year ON ipeds_e12 (survey_year);
