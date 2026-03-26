-- financial_stress_signals_schema.sql
-- Pre-computed multi-year financial stress signals for private nonprofit institutions.
--
-- One row per EIN (institution system), not per UNITID (campus).
-- Multi-campus systems (DeVry, Altierus/Everest, Strayer, etc.) are collapsed to their
-- canonical EIN. UNITID stored is MIN(unitid) for the EIN from institution_master.
--
-- Signal window: FY2020, FY2021, FY2022 (3-year trend, COVID-aware)
-- Each signal is evaluated per year; the _yrs column counts how many years it fired.
--
-- Signal definitions (8 financial + 3 enrollment = 11 signals):
--
-- Financial signals (from form990_filings + schedule_d + part_ix):
--   sig_deficit      : reconciliation_surplus < 0 (operating loss)
--   sig_neg_assets   : net_assets_eoy < 0 (technically insolvent)
--   sig_asset_decline: net asset change < -10% YoY
--   sig_high_debt    : total_liabilities_eoy / total_assets_eoy > 0.50
--   sig_low_cash     : cash < 3 months of expenses AND (no endowment OR endowment_runway < 1.0yr)
--                      [endowment suppression: wealthy institutions hold cash differently]
--   sig_end_stress   : endowment spending_rate > 7% (above NACUBO max; stress_endowment=1)
--   sig_low_runway   : endowment present AND endowment_runway < 0.5yr
--   sig_low_prog     : prog_services_pct < 65% (low mission-spend ratio; from part_ix)
--
-- Enrollment signals (from ipeds_ef survey_years 2020-2022; NULL if insufficient data):
--   sig_enrollment_decline      : declined each consecutive year (2021<2020 AND 2022<2021)
--   sig_enrollment_severe       : total 3yr decline > 10%
--   sig_enrollment_accelerating : rate of decline increased from interval 1 to interval 2
--
-- Trend tiers (financial signals):
--   confirmed : signal fires in all available years (requires >= 2 years of data)
--   emerging  : signal fires in 2 of 3 years (when 3 years available)
--   single    : signal fires in exactly 1 year (may be COVID distortion)
--
-- Scoring:
--   financial:   confirmed*1.0 + emerging*0.5 + single*0.25
--   enrollment:  decline*0.5 + severe*1.0 + accelerating*0.5; max 2.0
--   composite_stress_score = financial_score + enr_score_contribution
--
-- Cross-validation:
--   enr_financial_combined = 1 if sig_enrollment_decline=1 AND financial_score >= 2.0
--   This is the strongest signal in the database: enrollment and financial stress co-occurring.

CREATE TABLE IF NOT EXISTS financial_stress_signals (
    ein                         TEXT    PRIMARY KEY,
    unitid                      INTEGER,
    institution_name            TEXT,
    state_abbr                  TEXT,
    hbcu                        INTEGER,
    jesuit_institution          INTEGER,
    carnegie_basic              INTEGER,

    -- Financial year coverage
    signal_year_range           TEXT,       -- e.g. '2020-2022', '2021-2022'
    years_available             INTEGER,    -- 1, 2, or 3

    -- Per-signal: count of years signal fired (0–3)
    sig_deficit_yrs             INTEGER,    -- operating deficit
    sig_neg_assets_yrs          INTEGER,    -- negative net assets
    sig_asset_decline_yrs       INTEGER,    -- net assets fell >10%
    sig_high_debt_yrs           INTEGER,    -- liabilities > 50% of assets
    sig_low_cash_yrs            INTEGER,    -- cash < 3mo (endowment-suppressed)
    sig_end_stress_yrs          INTEGER,    -- endowment spending > 7%
    sig_low_runway_yrs          INTEGER,    -- endowment runway < 0.5yr
    sig_low_prog_yrs            INTEGER,    -- program services % < 65%

    -- Financial trend tier counts
    confirmed_signal_count      INTEGER,    -- signals confirmed across all available years (>=2 yrs)
    emerging_signal_count       INTEGER,    -- signals firing in 2 of 3 years
    single_year_count           INTEGER,    -- signals firing in exactly 1 year only

    -- Financial-only composite (before enrollment)
    financial_stress_score      REAL,       -- confirmed*1.0 + emerging*0.5 + single*0.25

    -- Enrollment data (ipeds_ef survey_years 2020-2022)
    enr_2020                    INTEGER,    -- enrtot survey_year=2020
    enr_2021                    INTEGER,    -- enrtot survey_year=2021
    enr_2022                    INTEGER,    -- enrtot survey_year=2022
    enr_trend_3yr               REAL,       -- (enr_2022 - enr_2020) / enr_2020; NULL if either endpoint missing
    enr_years_available         INTEGER,    -- 0-3: enrollment years with data

    -- Enrollment stress signals (NULL if insufficient data for that signal)
    sig_enrollment_decline      INTEGER,    -- 1=declined each consecutive year; NULL if <3 enrollment years
    sig_enrollment_severe       INTEGER,    -- 1=total 3yr decline >10%; NULL if either endpoint missing
    sig_enrollment_accelerating INTEGER,    -- 1=rate of decline accelerated interval1→2; NULL if <3 yrs

    -- Enrollment score contribution (NULL if all enrollment signals NULL)
    enr_score_contribution      REAL,       -- decline*0.5 + severe*1.0 + accelerating*0.5; max 2.0

    -- Full composite (financial + enrollment)
    composite_stress_score      REAL,       -- financial_stress_score + enr_score_contribution (or financial if enr NULL)

    -- Cross-validation: strongest signal in database
    enr_financial_combined      INTEGER,    -- 1 if sig_enrollment_decline=1 AND financial_stress_score >= 2.0

    -- Plain-language narrative for top stress cases (populated post-build via UPDATE)
    -- Null for institutions not yet reviewed. Seed of JENNI's stress signal language.
    narrative_flag              TEXT,

    data_completeness_pct       REAL,       -- financial years_available / 3 * 100

    loaded_at                   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fss_unitid    ON financial_stress_signals (unitid);
CREATE INDEX IF NOT EXISTS idx_fss_score     ON financial_stress_signals (composite_stress_score DESC);
CREATE INDEX IF NOT EXISTS idx_fss_hbcu      ON financial_stress_signals (hbcu);
CREATE INDEX IF NOT EXISTS idx_fss_state     ON financial_stress_signals (state_abbr);
CREATE INDEX IF NOT EXISTS idx_fss_combined  ON financial_stress_signals (enr_financial_combined);
