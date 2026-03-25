-- schema/eada_schema.sql
-- -------------------------
-- Equity in Athletics Data Analysis (EADA) — institution-level summary.
-- Source: OPE portal https://ope.ed.gov/athletics/ — InstLevel.xlsx per year.
--
-- survey_year convention: END year of the academic year.
--   EADA file "2022-2023" → survey_year = 2023.
-- Join conventions:
--   eada ↔ 990:   eada.survey_year  = f990.fiscal_year_end
--   eada ↔ IPEDS: eada.survey_year  = ipeds.survey_year + 1
--
-- Financial columns use the EADA column names lowercased.
-- grnd_total_expense / grnd_total_revenue are the canonical totals —
--   they include men+women team allocations, coed teams, and not-allocated spend.

CREATE TABLE IF NOT EXISTS eada_instlevel (
    unitid                  TEXT    NOT NULL,
    survey_year             INTEGER NOT NULL,

    -- Institution metadata
    institution_name        TEXT,
    state_cd                TEXT,
    classification_code     INTEGER,    -- 1=D-I FBS, 2=D-I FCS, 3=D-I Other, 4=D-II w/FB, 5=D-II w/o FB, 6=D-III, 7=NAIA, 8=Other
    classification_name     TEXT,
    sector_cd               INTEGER,    -- 1=Public 4yr, 2=Private nonprofit 4yr, 3=Proprietary 4yr, etc.
    sector_name             TEXT,

    -- Enrollment (EADA self-reported, may differ slightly from IPEDS EF)
    ef_total_count          INTEGER,

    -- Grand totals (canonical — includes all programs + not-allocated)
    grnd_total_revenue      INTEGER,    -- GRND_TOTAL_REVENUE
    grnd_total_expense      INTEGER,    -- GRND_TOTAL_EXPENSE

    -- Men + Women allocated programs (excludes coed teams and not-allocated)
    il_total_revenue_all    INTEGER,    -- IL_TOTAL_REVENUE_ALL
    il_total_expense_all    INTEGER,    -- IL_TOTAL_EXPENSE_ALL

    -- Coed teams (separate from men/women buckets)
    il_total_rev_coed       INTEGER,    -- IL_TOTAL_REV_COED
    il_total_exp_coed       INTEGER,    -- IL_TOTAL_EXP_COED

    -- Not allocated by gender/sport
    tot_revenue_not_alloc   INTEGER,    -- TOT_REVENUE_ALL_NOTALLOC
    tot_expense_not_alloc   INTEGER,    -- TOT_EXPENSE_ALL_NOTALLOC

    -- Expense sub-components
    studentaid_total        INTEGER,    -- STUDENTAID_TOTAL (athletically related student aid)
    recruitexp_total        INTEGER,    -- RECRUITEXP_TOTAL (recruiting expenses)
    hdcoach_salary_men      INTEGER,    -- HDCOACH_SALARY_MEN (avg salary, men's teams)
    hdcoach_salary_women    INTEGER,    -- HDCOACH_SALARY_WOMEN (avg salary, women's teams)

    -- Participation
    partic_men              INTEGER,    -- IL_SUM_PARTIC_MEN
    partic_women            INTEGER,    -- IL_SUM_PARTIC_WOMEN

    loaded_at               TEXT        DEFAULT (datetime('now')),

    PRIMARY KEY (unitid, survey_year)
);

CREATE INDEX IF NOT EXISTS idx_eada_unitid      ON eada_instlevel (unitid);
CREATE INDEX IF NOT EXISTS idx_eada_year        ON eada_instlevel (survey_year);
CREATE INDEX IF NOT EXISTS idx_eada_state       ON eada_instlevel (state_cd);
CREATE INDEX IF NOT EXISTS idx_eada_class       ON eada_instlevel (classification_code);
