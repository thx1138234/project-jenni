-- =============================================================================
-- ipeds_schema.sql
-- IPEDS database schema for higher-ed-db
-- All 12 survey components + institution_master + analytical views
--
-- Conventions:
--   - survey_year = fall start year of academic year (IPEDS convention)
--   - NULL = not reported / not applicable; 0 = reported as zero
--   - UNITID is the universal join key across all tables
--   - reporting_framework = 'GASB' (public) or 'FASB' (private nonprofit)
-- =============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- =============================================================================
-- institution_master
-- Shared lookup table across all four source databases.
-- Populated from IPEDS IC data; enriched with EIN (990) and OPEID (Scorecard).
-- =============================================================================

CREATE TABLE IF NOT EXISTS institution_master (
    unitid              INTEGER PRIMARY KEY,
    institution_name    TEXT,
    city                TEXT,
    state_abbr          TEXT,
    state_fips          INTEGER,
    zip                 TEXT,
    region              INTEGER,    -- NCES OBEREG codes 0-9
    locale              INTEGER,    -- NCES locale codes (city/suburb/town/rural)
    control             INTEGER,    -- 1=Public, 2=Private nonprofit, 3=Private for-profit
    control_label       TEXT,
    reporting_framework TEXT,       -- 'GASB' for public, 'FASB' for private
    hbcu                INTEGER,    -- 1=Yes, 0=No
    tribal_college      INTEGER,    -- 1=Yes, 0=No
    hospital            INTEGER,    -- 1=Yes, 0=No
    medical_degree      INTEGER,    -- 1=Yes, 0=No
    land_grant          INTEGER,    -- 1=Yes, 0=No
    jesuit_institution  INTEGER DEFAULT 0,  -- 1=AJCU member (Society of Jesus); set manually, RELAFFIL dropped from NCES HD files
    iclevel             INTEGER,    -- 1=4-year, 2=2-year, 3=Less-than-2-year
    iclevel_label       TEXT,
    degree_granting     INTEGER,    -- 1=Yes, 0=No
    carnegie_basic      INTEGER,    -- Carnegie Classification 2018 basic
    calendar_system     INTEGER,    -- 1=semester, 2=quarter, 3=trimester, etc.
    website             TEXT,
    ein                 TEXT,       -- EIN for private nonprofits (990 join key)
    opeid               TEXT,       -- OPE ID (College Scorecard join key)
    is_active           INTEGER DEFAULT 1,
    last_updated        TEXT DEFAULT (date('now'))
);

-- =============================================================================
-- ipeds_ic — Institutional Characteristics
-- Tuition, fees, room & board, program offerings, calendar system.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ipeds_ic (
    unitid                  INTEGER NOT NULL,
    survey_year             INTEGER NOT NULL,

    -- Tuition & Fees
    tuition_indistrict      INTEGER,    -- In-district undergraduate tuition
    tuition_instate         INTEGER,    -- In-state undergraduate tuition
    tuition_outstate        INTEGER,    -- Out-of-state undergraduate tuition
    fee_indistrict          INTEGER,
    fee_instate             INTEGER,
    fee_outstate            INTEGER,
    tuition_grad_instate    INTEGER,
    tuition_grad_outstate   INTEGER,

    -- Room, Board & Other Expenses
    roomboard_oncampus      INTEGER,
    books_oncampus          INTEGER,
    otherexp_oncampus       INTEGER,

    -- Institutional Characteristics
    calendar_system         INTEGER,
    offers_undergrad        INTEGER,    -- 1=Yes
    offers_graduate         INTEGER,    -- 1=Yes
    offers_distance_ed      INTEGER,    -- 1=Yes, 2=No
    openadmp                INTEGER,    -- Open admissions: 1=Yes, 2=No
    sat_act_req             INTEGER,    -- SAT/ACT required: 1=Required, 2=Recommended, etc.
    credit_ap               INTEGER,    -- AP credit accepted: 1=Yes, 2=No
    credit_clep             INTEGER,    -- CLEP credit accepted: 1=Yes, 2=No

    PRIMARY KEY (unitid, survey_year),
    FOREIGN KEY (unitid) REFERENCES institution_master(unitid)
);

-- =============================================================================
-- ipeds_adm — Admissions
-- Standalone from 2014; pre-2014 admissions data is embedded in IC.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ipeds_adm (
    unitid                  INTEGER NOT NULL,
    survey_year             INTEGER NOT NULL,

    -- Applications, Admissions, Enrollment
    applcn                  INTEGER,    -- Total applicants
    applcnm                 INTEGER,    -- Male applicants
    applcnw                 INTEGER,    -- Female applicants
    admssn                  INTEGER,    -- Total admitted
    admssnm                 INTEGER,
    admssnw                 INTEGER,
    enrlt                   INTEGER,    -- Total enrolled (first-time)
    enrlm                   INTEGER,
    enrlw                   INTEGER,
    enrlft                  INTEGER,    -- Full-time enrolled
    enrlpt                  INTEGER,    -- Part-time enrolled

    -- Calculated Rates (pre-computed at load time)
    admit_rate              REAL,       -- admssn / applcn
    yield_rate              REAL,       -- enrlt / admssn

    -- SAT Scores (25th/75th percentile)
    sat_reading_25          INTEGER,
    sat_reading_75          INTEGER,
    sat_math_25             INTEGER,
    sat_math_75             INTEGER,

    -- ACT Scores
    act_composite_25        INTEGER,
    act_composite_75        INTEGER,
    act_english_25          INTEGER,
    act_english_75          INTEGER,
    act_math_25             INTEGER,
    act_math_75             INTEGER,

    -- Test Score Submission
    pct_submitting_sat      INTEGER,    -- % submitting SAT
    pct_submitting_act      INTEGER,    -- % submitting ACT
    sat_act_required        INTEGER,    -- Test policy code

    PRIMARY KEY (unitid, survey_year),
    FOREIGN KEY (unitid) REFERENCES institution_master(unitid)
);

-- =============================================================================
-- ipeds_ef — Fall Enrollment
-- Totals from Part D; race/ethnicity detail from Part A.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ipeds_ef (
    unitid          INTEGER NOT NULL,
    survey_year     INTEGER NOT NULL,

    -- Enrollment Totals (Part D)
    enrtot          INTEGER,    -- Total headcount enrollment
    enrugrd         INTEGER,    -- Undergraduate
    enrgrad         INTEGER,    -- Graduate
    enrft           INTEGER,    -- Full-time
    enrpt           INTEGER,    -- Part-time
    stufacr         REAL,       -- Student-to-faculty ratio
    ret_pcf         REAL,       -- First-time full-time retention rate (0–100)

    -- Race/Ethnicity Breakdown (Part A — totals across all levels)
    enr_white       INTEGER,
    enr_black       INTEGER,
    enr_hispanic    INTEGER,
    enr_asian       INTEGER,
    enr_aian        INTEGER,    -- American Indian / Alaska Native
    enr_nhpi        INTEGER,    -- Native Hawaiian / Pacific Islander
    enr_twomore     INTEGER,    -- Two or more races
    enr_unknrace    INTEGER,    -- Unknown race
    enr_nonres      INTEGER,    -- Nonresident alien
    enrtotm         INTEGER,    -- Total male
    enrtotw         INTEGER,    -- Total female

    PRIMARY KEY (unitid, survey_year),
    FOREIGN KEY (unitid) REFERENCES institution_master(unitid)
);

-- =============================================================================
-- ipeds_completions — Degrees & Certificates Awarded (C)
-- One row per institution × CIP code × award level.
-- Full national build: ~50M+ rows across all years.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ipeds_completions (
    unitid          INTEGER NOT NULL,
    survey_year     INTEGER NOT NULL,
    cipcode         TEXT    NOT NULL,   -- 6-digit CIP code (e.g., "11.0701")
    cip2digit       TEXT,               -- 2-digit series derived from cipcode
    awlevel         INTEGER NOT NULL,   -- Award level: 1=<1yr cert, 3=AA, 5=BA, 7=MA, 9=PhD, etc.

    -- Award Counts by Gender
    ctotalt         INTEGER,    -- Total awards
    ctotalm         INTEGER,
    ctotalw         INTEGER,

    -- Race/Ethnicity
    caiant          INTEGER,    -- American Indian / Alaska Native
    casiat          INTEGER,    -- Asian
    cbkaat          INTEGER,    -- Black / African American
    chispt          INTEGER,    -- Hispanic
    cnhpit          INTEGER,    -- Native Hawaiian / Pacific Islander
    cwhitt          INTEGER,    -- White
    c2mort          INTEGER,    -- Two or more races
    cunknt          INTEGER,    -- Unknown
    cnralt          INTEGER,    -- Nonresident alien
    distance_ed     INTEGER,    -- Completions via distance education

    PRIMARY KEY (unitid, survey_year, cipcode, awlevel),
    FOREIGN KEY (unitid) REFERENCES institution_master(unitid)
);

CREATE INDEX IF NOT EXISTS idx_completions_year_cip
    ON ipeds_completions(survey_year, cipcode, awlevel);

CREATE INDEX IF NOT EXISTS idx_completions_cip2
    ON ipeds_completions(cip2digit, survey_year);

-- =============================================================================
-- ipeds_gr — Graduation Rates (GR)
-- 150% time completion for first-time, full-time bachelor's cohort.
-- Also includes Pell and loan recipient sub-cohorts.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ipeds_gr (
    unitid          INTEGER NOT NULL,
    survey_year     INTEGER NOT NULL,

    -- Bachelor's Degree-Seeking Cohort (150% time = 6-year rate)
    gba_cohort      INTEGER,    -- Cohort size
    gba_grad_150    INTEGER,    -- Graduates within 150% time
    gba_rate_150    REAL,       -- Graduation rate (pre-computed)

    -- Pell Grant Recipient Sub-cohort
    pell_cohort     INTEGER,
    pell_grad_150   INTEGER,
    pell_rate_150   REAL,

    -- Federal Loan (non-Pell) Sub-cohort
    loan_cohort     INTEGER,
    loan_grad_150   INTEGER,
    loan_rate_150   REAL,

    PRIMARY KEY (unitid, survey_year),
    FOREIGN KEY (unitid) REFERENCES institution_master(unitid)
);

-- =============================================================================
-- ipeds_finance — Finance (F)
-- GASB (public) and FASB (private) in a single table, identified by
-- reporting_framework column. See docs/gasb_fasb_crosswalk.md for
-- cross-sector comparison guidance.
--
-- CURRENT POLICY: FASB rows loaded; GASB deferred (see CLAUDE.md).
-- =============================================================================

CREATE TABLE IF NOT EXISTS ipeds_finance (
    unitid                      INTEGER NOT NULL,
    survey_year                 INTEGER NOT NULL,
    reporting_framework         TEXT    NOT NULL,   -- 'GASB' or 'FASB'

    -- Revenue
    rev_tuition_fees            INTEGER,    -- Net tuition (FASB) / Gross tuition (GASB)
    tuition_discounts           INTEGER,    -- FASB only — scholarship allowances
    rev_fed_approp              INTEGER,    -- GASB only — federal appropriations
    rev_state_approp            INTEGER,    -- GASB only — state appropriations
    rev_local_approp            INTEGER,    -- GASB only — local appropriations
    rev_fed_grants              INTEGER,
    rev_state_grants            INTEGER,
    rev_private_grants          INTEGER,
    rev_private_gifts           INTEGER,
    rev_investment              INTEGER,    -- Investment return / income
    rev_auxiliary               INTEGER,    -- Housing, dining, parking
    rev_hospitals               INTEGER,
    rev_other                   INTEGER,
    rev_total                   INTEGER,    -- Use with caution cross-sector

    -- Expenses
    exp_instruction             INTEGER,
    exp_research                INTEGER,
    exp_public_service          INTEGER,
    exp_academic_support        INTEGER,
    exp_student_services        INTEGER,
    exp_institutional_support   INTEGER,
    exp_net_scholarships        INTEGER,
    exp_aux_enterprises         INTEGER,
    exp_hospitals               INTEGER,
    exp_depreciation            INTEGER,    -- GASB only (embedded in FASB functional expenses)
    exp_other                   INTEGER,
    exp_total                   INTEGER,

    -- Balance Sheet
    assets_total                INTEGER,
    assets_current              INTEGER,
    assets_capital_net          INTEGER,
    assets_endowment            INTEGER,
    liab_total                  INTEGER,
    liab_current                INTEGER,
    liab_longterm_debt          INTEGER,
    netassets_total             INTEGER,
    netassets_unrestricted      INTEGER,    -- FASB only
    netassets_restricted_temp   INTEGER,    -- FASB only
    netassets_restricted_perm   INTEGER,    -- FASB only
    netassets_invested_capital  INTEGER,    -- GASB only

    PRIMARY KEY (unitid, survey_year, reporting_framework),
    FOREIGN KEY (unitid) REFERENCES institution_master(unitid)
);

-- =============================================================================
-- ipeds_sfa — Student Financial Aid (SFA)
-- Aid receipt rates, average amounts, net price by income band.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ipeds_sfa (
    unitid              INTEGER NOT NULL,
    survey_year         INTEGER NOT NULL,

    scugffn             INTEGER,    -- Full-time, first-time degree-seeking undergrads
    pct_any_grant       REAL,       -- % receiving any grant aid
    pct_fed_grant       REAL,       -- % receiving federal grant aid
    pct_pell            REAL,       -- % receiving Pell grants
    avg_any_grant       INTEGER,    -- Average grant amount
    avg_pell            INTEGER,    -- Average Pell grant
    pct_loan            REAL,       -- % receiving federal loans
    avg_loan            INTEGER,    -- Average federal loan amount

    -- Net Price (published price minus average aid)
    netprice            INTEGER,    -- Overall average net price
    netprice_0_30k      INTEGER,    -- Net price for family income $0-$30K
    netprice_30_48k     INTEGER,
    netprice_48_75k     INTEGER,
    netprice_75_110k    INTEGER,
    netprice_over110k   INTEGER,

    PRIMARY KEY (unitid, survey_year),
    FOREIGN KEY (unitid) REFERENCES institution_master(unitid)
);

-- =============================================================================
-- ipeds_hr — Human Resources (HR)
-- Faculty and staff counts, instructional staff by rank, average salaries.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ipeds_hr (
    unitid              INTEGER NOT NULL,
    survey_year         INTEGER NOT NULL,

    ft_instr_total      INTEGER,    -- Full-time instructional staff (total)
    ft_instr_male       INTEGER,
    ft_instr_female     INTEGER,
    ft_prof             INTEGER,    -- Full professors
    ft_assoc            INTEGER,    -- Associate professors
    ft_asst             INTEGER,    -- Assistant professors
    sal_prof_9mo        INTEGER,    -- Average 9-month salary (all ranks combined)
    emp_total           INTEGER,    -- Total employees (all categories)

    PRIMARY KEY (unitid, survey_year),
    FOREIGN KEY (unitid) REFERENCES institution_master(unitid)
);

-- =============================================================================
-- ANALYTICAL VIEWS
-- Pre-join common patterns. Query these instead of writing raw joins.
-- =============================================================================

-- v_enrollment_trends: Enrollment by year with race/ethnicity percentages.
CREATE VIEW IF NOT EXISTS v_enrollment_trends AS
SELECT
    ef.unitid,
    im.institution_name,
    im.state_abbr,
    im.control_label,
    im.iclevel_label,
    ef.survey_year,
    ef.enrtot,
    ef.enrugrd,
    ef.enrgrad,
    ef.enrft,
    ef.enrpt,
    ef.stufacr,
    -- Race/ethnicity as % of total enrollment
    ROUND(100.0 * ef.enr_white    / NULLIF(ef.enrtot, 0), 1) AS pct_white,
    ROUND(100.0 * ef.enr_black    / NULLIF(ef.enrtot, 0), 1) AS pct_black,
    ROUND(100.0 * ef.enr_hispanic / NULLIF(ef.enrtot, 0), 1) AS pct_hispanic,
    ROUND(100.0 * ef.enr_asian    / NULLIF(ef.enrtot, 0), 1) AS pct_asian,
    ROUND(100.0 * ef.enr_nonres   / NULLIF(ef.enrtot, 0), 1) AS pct_nonresident,
    ROUND(100.0 * ef.enr_twomore  / NULLIF(ef.enrtot, 0), 1) AS pct_twomore
FROM ipeds_ef ef
JOIN institution_master im ON ef.unitid = im.unitid;


-- v_financial_summary: Key financial ratios with per-student metrics.
-- ALWAYS check reporting_framework before cross-sector comparisons.
CREATE VIEW IF NOT EXISTS v_financial_summary AS
SELECT
    f.unitid,
    im.institution_name,
    im.state_abbr,
    im.control_label,
    f.survey_year,
    f.reporting_framework,
    f.rev_tuition_fees,
    f.rev_total,
    f.exp_total,
    f.exp_instruction,
    f.assets_endowment,
    f.netassets_total,
    ef.enrtot,
    -- Per-student metrics
    ROUND(1.0 * f.exp_instruction / NULLIF(ef.enrtot, 0), 0)  AS inst_exp_per_fte,
    ROUND(1.0 * f.rev_total       / NULLIF(ef.enrtot, 0), 0)  AS rev_per_fte,
    ROUND(1.0 * f.assets_endowment/ NULLIF(ef.enrtot, 0), 0)  AS endowment_per_student,
    -- Tuition dependency ratio (tuition as % of total revenue)
    ROUND(100.0 * f.rev_tuition_fees / NULLIF(f.rev_total, 0), 1) AS tuition_dependency_pct,
    -- Operating margin proxy
    ROUND(100.0 * (f.rev_total - f.exp_total) / NULLIF(f.rev_total, 0), 1) AS operating_margin_pct
FROM ipeds_finance f
JOIN institution_master im ON f.unitid = im.unitid
LEFT JOIN ipeds_ef ef ON f.unitid = ef.unitid AND f.survey_year = ef.survey_year;


-- v_masters_programs: Master's degree completions by CIP code.
-- awlevel = 7 is master's degrees.
CREATE VIEW IF NOT EXISTS v_masters_programs AS
SELECT
    c.unitid,
    im.institution_name,
    im.state_abbr,
    im.control_label,
    c.survey_year,
    c.cipcode,
    c.cip2digit,
    c.ctotalt   AS masters_total,
    c.ctotalm   AS masters_male,
    c.ctotalw   AS masters_female
FROM ipeds_completions c
JOIN institution_master im ON c.unitid = im.unitid
WHERE c.awlevel = 7;


-- v_admissions_selectivity: Admit rate, yield, test scores with enrollment context.
CREATE VIEW IF NOT EXISTS v_admissions_selectivity AS
SELECT
    a.unitid,
    im.institution_name,
    im.state_abbr,
    im.control_label,
    im.carnegie_basic,
    a.survey_year,
    a.applcn,
    a.admssn,
    a.enrlt,
    a.admit_rate,
    a.yield_rate,
    a.sat_math_25,
    a.sat_math_75,
    a.sat_reading_25,
    a.sat_reading_75,
    a.act_composite_25,
    a.act_composite_75,
    a.pct_submitting_sat,
    a.pct_submitting_act,
    ef.enrtot       AS total_enrollment,
    ef.enrugrd      AS undergrad_enrollment
FROM ipeds_adm a
JOIN institution_master im ON a.unitid = im.unitid
LEFT JOIN ipeds_ef ef ON a.unitid = ef.unitid AND a.survey_year = ef.survey_year;
