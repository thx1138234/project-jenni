-- 990_compensation_schema.sql
-- IRS Form 990 Schedule J — Officer/Director/Key Employee Compensation
--
-- One row per person per filing. Source: Schedule J Part II (detailed breakdown)
-- augmented by Part VII Section A (hours per week, role flags).
--
-- TEOS/IRSx rows: fully populated from Schedule J + Part VII.
-- ProPublica rows (FY2012–2019): NULL by design — ProPublica API exposes only
--   aggregate officer compensation (compnsatncurrofcr), not per-person Schedule J
--   breakdowns. Pre-2019 per-person data requires downloading TEOS XML for index
--   years 2013–2018 (XML exists on IRS portal; downloader extension needed).
--
-- Compensation fields (from Schedule J Part II):
--   comp_base        = base compensation from filing organization
--   comp_bonus       = bonus/incentive compensation from filing org
--   comp_other       = other reportable compensation from filing org
--   comp_deferred    = deferred compensation from filing org
--   comp_nontaxable  = nontaxable benefits from filing org
--   comp_total       = total compensation from filing org (cols B–F sum)
--   related_org_comp = total compensation from related organizations (col G)
--
-- Role/hours fields (from Part VII Section A, joined by officer_name):
--   hours_per_week   = AverageHoursPerWeekRt
--   former_officer   = 1 if FormerOfcrDirectorTrusteeInd = 'X', else 0
--   is_officer       = 1 if OfficerInd = 'X'
--   is_key_employee  = 1 if KeyEmployeeInd = 'X'
--   is_highest_comp  = 1 if HighestCompensatedEmployeeInd = 'X'
--
-- PRIMARY KEY is (object_id, officer_name) — one row per person per filing.

CREATE TABLE IF NOT EXISTS form990_compensation (
    object_id           TEXT    NOT NULL,   -- FK → form990_filings.object_id
    ein                 TEXT    NOT NULL,
    fiscal_year_end     INTEGER,
    officer_name        TEXT    NOT NULL,
    officer_title       TEXT,

    -- Compensation from filing organization (Schedule J Part II, cols B–F)
    comp_base           INTEGER,
    comp_bonus          INTEGER,
    comp_other          INTEGER,
    comp_deferred       INTEGER,
    comp_nontaxable     INTEGER,
    comp_total          INTEGER,            -- total from filing org

    -- Compensation from related organizations (col G)
    related_org_comp    INTEGER,

    -- Role and hours (from Part VII Section A)
    hours_per_week      REAL,
    former_officer      INTEGER DEFAULT 0,  -- 1 = former officer/director/trustee
    is_officer          INTEGER DEFAULT 0,  -- 1 = current officer
    is_key_employee     INTEGER DEFAULT 0,  -- 1 = key employee
    is_highest_comp     INTEGER DEFAULT 0,  -- 1 = highest-compensated employee

    -- Metadata
    data_source         TEXT    DEFAULT 'irsx',
    loaded_at           TEXT    DEFAULT (datetime('now')),

    PRIMARY KEY (object_id, officer_name)
);

CREATE INDEX IF NOT EXISTS idx_comp_ein       ON form990_compensation (ein);
CREATE INDEX IF NOT EXISTS idx_comp_year      ON form990_compensation (fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_comp_ein_year  ON form990_compensation (ein, fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_comp_name      ON form990_compensation (officer_name);
