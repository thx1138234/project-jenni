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
-- Signal definitions (8 signals):
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
-- Trend tiers:
--   confirmed : signal fires in all available years (requires >= 2 years of data)
--   emerging  : signal fires in 2 of 3 years (when 3 years available)
--   single    : signal fires in exactly 1 year (may be COVID distortion)
--
-- composite_stress_score = confirmed * 1.0 + emerging * 0.5 + single * 0.25
-- data_completeness_pct  = (years_available / 3) * 100

CREATE TABLE IF NOT EXISTS financial_stress_signals (
    ein                     TEXT    PRIMARY KEY,
    unitid                  INTEGER,
    institution_name        TEXT,
    state_abbr              TEXT,
    hbcu                    INTEGER,
    jesuit_institution      INTEGER,
    carnegie_basic          INTEGER,

    -- Year coverage
    signal_year_range       TEXT,       -- e.g. '2020-2022', '2021-2022'
    years_available         INTEGER,    -- 1, 2, or 3

    -- Per-signal: count of years signal fired (0–3)
    sig_deficit_yrs         INTEGER,    -- operating deficit
    sig_neg_assets_yrs      INTEGER,    -- negative net assets
    sig_asset_decline_yrs   INTEGER,    -- net assets fell >10%
    sig_high_debt_yrs       INTEGER,    -- liabilities > 50% of assets
    sig_low_cash_yrs        INTEGER,    -- cash < 3mo (endowment-suppressed)
    sig_end_stress_yrs      INTEGER,    -- endowment spending > 7%
    sig_low_runway_yrs      INTEGER,    -- endowment runway < 0.5yr
    sig_low_prog_yrs        INTEGER,    -- program services % < 65%

    -- Trend tier counts
    confirmed_signal_count  INTEGER,    -- signals confirmed across all available years (>=2 yrs)
    emerging_signal_count   INTEGER,    -- signals firing in 2 of 3 years
    single_year_count       INTEGER,    -- signals firing in exactly 1 year only

    -- Composite
    composite_stress_score  REAL,       -- confirmed*1.0 + emerging*0.5 + single*0.25
    data_completeness_pct   REAL,       -- years_available / 3 * 100

    loaded_at               TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fss_unitid  ON financial_stress_signals (unitid);
CREATE INDEX IF NOT EXISTS idx_fss_score   ON financial_stress_signals (composite_stress_score DESC);
CREATE INDEX IF NOT EXISTS idx_fss_hbcu    ON financial_stress_signals (hbcu);
CREATE INDEX IF NOT EXISTS idx_fss_state   ON financial_stress_signals (state_abbr);
