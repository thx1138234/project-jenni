-- eada_sports_schema.sql
-- EADA Schools file — sport-level data per institution per year
--
-- One row per institution × sport × year.
-- PRIMARY KEY (unitid, survey_year, sport_code).
-- survey_year convention: END year of academic year (same as eada_instlevel).
--   "EADA 2022-2023.zip" → survey_year = 2023.
-- Join to eada_instlevel on (unitid, survey_year) for institutional totals.
--
-- Source: Schools.xlsx (2012+) / schools.xls (2000-2011) inside each EADA ZIP.
--   File naming: Schools.xlsx, schools.xlsx, Schools.xls, schools.xls (case varies).
--
-- Coaching SALARY data is NOT available at the sport level in EADA.
--   Per-sport coaching salary is not collected by the Dept of Education.
--   Institution-level totals (hdcoach_salary_men, hdcoach_salary_women,
--   recruitexp_total, studentaid_total) are in eada_instlevel.
--
-- Fields available at sport level:
--   Participation counts: participants_men, participants_women
--   Revenue: total_revenue (TOTAL_REVENUE_ALL), rev_men, rev_women
--   Expenses: total_expenses (TOTAL_EXPENSE_ALL), exp_men, exp_women
--   Operating expenses: total_opexp (TOTAL_OPEXP_INCLCOED, includes coed)
--   Head coach counts: headcoach_count_men, headcoach_count_women
--
-- SPORTSCODE reference values (consistent across years):
--   1=Baseball, 2=Basketball(M), 3=Cross Country(M), 4=Fencing(M), 5=Football,
--   6=Golf(M), 7=Gymnastics(M), 8=Ice Hockey(M), 9=Lacrosse(M), 10=Rifle,
--   11=Skiing(M), 12=Soccer(M), 13=Swimming(M), 14=Tennis(M), 15=Indoor Track(M),
--   16=Outdoor Track(M), 17=Volleyball(M), 18=Water Polo(M), 19=Wrestling,
--   20=Other(M), 21=Basketball(W), 22=Bowling(W), 23=Cross Country(W),
--   24=Equestrian(W), 25=Fencing(W), 26=Field Hockey(W), 27=Golf(W),
--   28=Gymnastics(W), 29=Ice Hockey(W), 30=Lacrosse(W), 31=Rowing(W),
--   32=Skiing(W), 33=Soccer(W), 34=Softball(W), 35=Swimming(W), 36=Tennis(W),
--   37=Indoor Track(W), 38=Outdoor Track(W), 39=Volleyball(W), 40=Water Polo(W),
--   41=Other(W), 42=Archery(Coed), 43=Badminton(Coed), 44=Sailing(Coed),
--   45=Squash(Coed), 46=Synchronized Swimming(Coed), 47=Other(Coed)

CREATE TABLE IF NOT EXISTS eada_sports (
    unitid                  INTEGER NOT NULL,
    survey_year             INTEGER NOT NULL,
    sport_code              INTEGER NOT NULL,
    sport_name              TEXT,
    classification_name     TEXT,

    -- Participation
    participants_men        INTEGER,    -- PARTIC_MEN
    participants_women      INTEGER,    -- PARTIC_WOMEN

    -- Revenue
    total_revenue           INTEGER,    -- TOTAL_REVENUE_ALL (men + women + coed)
    rev_men                 INTEGER,    -- REV_MEN
    rev_women               INTEGER,    -- REV_WOMEN

    -- Expenses
    total_expenses          INTEGER,    -- TOTAL_EXPENSE_ALL (men + women + coed)
    exp_men                 INTEGER,    -- EXP_MEN
    exp_women               INTEGER,    -- EXP_WOMEN
    total_opexp             INTEGER,    -- TOTAL_OPEXP_INCLCOED (operating expenses incl coed)

    -- Head coach counts (NO salary dollars at sport level — see eada_instlevel)
    headcoach_count_men     INTEGER,    -- MEN_TOTAL_HEADCOACH
    headcoach_count_women   INTEGER,    -- WOMEN_TOTAL_HDCOACH

    loaded_at               TEXT DEFAULT (datetime('now')),

    PRIMARY KEY (unitid, survey_year, sport_code)
);

CREATE INDEX IF NOT EXISTS idx_eada_sports_year      ON eada_sports (survey_year);
CREATE INDEX IF NOT EXISTS idx_eada_sports_sport     ON eada_sports (sport_code);
CREATE INDEX IF NOT EXISTS idx_eada_sports_uid_year  ON eada_sports (unitid, survey_year);
