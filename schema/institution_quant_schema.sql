-- institution_quant_schema.sql
-- Authoritative quantitative metrics layer. One row per institution per year.
-- Pure math only: no thresholds, no composite scores, no judgments.
-- Fully rebuildable from source data at any time.
-- formula_version tracks the metric calculation logic version for reproducibility.
--
-- Year convention: survey_year = IPEDS fall start year.
--   990 financial metrics use fiscal_year_end = survey_year + 1 for the join.
--   EADA athletics metrics use eada.survey_year = institution_quant.survey_year + 1.
--   Scorecard value metrics use scorecard.data_year (single year; no trend computation).
--
-- Peer groups: Carnegie basic classification (carnegie_basic from institution_master).
--   carnegie_peer_group_size = number of institutions in peer group with non-NULL values
--   for that metric in that year. Peer stats set NULL if peer_group_size < 5.
--
-- Trend direction: stored as 'improving' | 'stable' | 'deteriorating'
--   stable = |relative_change| < 0.02 (2% threshold).
--   Direction polarity defined per metric:
--     higher-is-better: positive change = improving
--     lower-is-better:  negative change = improving
--
-- 26 metrics × 6 columns = 156 metric columns + identity + peer context = 163 columns.
--
-- Known gaps:
--   retention_rate: EF Part D not loaded — always NULL.
--   grad_rate_150: scorecard completion_rate_4yr — single year 2023 only, no trend.
--   net_price, earnings_to_debt_ratio, net_price_to_earnings: scorecard single year 2023.
--   Financial metrics (990): private nonprofits only; public institutions get NULL.
--
-- Metric direction reference (for trend_dir interpretation):
--   tuition_dependency             lower   (990)
--   operating_margin               higher  (990)
--   debt_to_assets                 lower   (990)
--   debt_to_revenue                lower   (990)
--   endowment_per_student          higher  (990+e12)
--   endowment_spending_rate        lower   (schedule_d)
--   endowment_runway               higher  (schedule_d)
--   fundraising_efficiency         higher  (part_ix)
--   overhead_ratio                 lower   (part_ix)
--   program_services_pct           higher  (part_ix)
--   revenue_per_fte                higher  (990+e12)
--   expense_per_fte                lower   (990+e12)
--   enrollment_3yr_cagr            higher  (ipeds_ef)
--   yield_rate                     higher  (ipeds_adm)
--   admit_rate                     lower   (ipeds_adm)
--   app_3yr_cagr                   higher  (ipeds_adm)
--   grad_rate_150                  higher  (scorecard)
--   retention_rate                 higher  (NOT_LOADED)
--   grad_enrollment_pct            higher  (ipeds_ef)
--   pell_pct                       higher  (ipeds_sfa)
--   net_price                      lower   (scorecard)
--   earnings_to_debt_ratio         higher  (scorecard)
--   net_price_to_earnings          lower   (scorecard)
--   athletics_to_expense_pct       lower   (eada+990)
--   athletics_net                  higher  (eada)
--   athletics_per_student          lower   (eada+ef)

CREATE TABLE IF NOT EXISTS institution_quant (
    unitid                  INTEGER NOT NULL,
    ein                     TEXT,
    survey_year             INTEGER NOT NULL,
    formula_version         TEXT    NOT NULL DEFAULT '1.0',
    data_completeness_pct   REAL,
    carnegie_peer_group_size INTEGER,

    -- tuition_dependency (lower-is-better) | 990
    -- program_service_revenue / total_revenue
    tuition_dependency_value            REAL,
    tuition_dependency_peer_median      REAL,
    tuition_dependency_peer_pct         REAL,
    tuition_dependency_trend_1yr        REAL,
    tuition_dependency_trend_3yr        REAL,
    tuition_dependency_trend_dir        TEXT,

    -- operating_margin (higher-is-better) | 990
    -- reconciliation_surplus / total_revenue
    operating_margin_value            REAL,
    operating_margin_peer_median      REAL,
    operating_margin_peer_pct         REAL,
    operating_margin_trend_1yr        REAL,
    operating_margin_trend_3yr        REAL,
    operating_margin_trend_dir        TEXT,

    -- debt_to_assets (lower-is-better) | 990
    -- total_liabilities_eoy / total_assets_eoy
    debt_to_assets_value            REAL,
    debt_to_assets_peer_median      REAL,
    debt_to_assets_peer_pct         REAL,
    debt_to_assets_trend_1yr        REAL,
    debt_to_assets_trend_3yr        REAL,
    debt_to_assets_trend_dir        TEXT,

    -- debt_to_revenue (lower-is-better) | 990
    -- total_liabilities_eoy / total_revenue
    debt_to_revenue_value            REAL,
    debt_to_revenue_peer_median      REAL,
    debt_to_revenue_peer_pct         REAL,
    debt_to_revenue_trend_1yr        REAL,
    debt_to_revenue_trend_3yr        REAL,
    debt_to_revenue_trend_dir        TEXT,

    -- endowment_per_student (higher-is-better) | 990+e12
    -- endowment_eoy / fte12
    endowment_per_student_value            REAL,
    endowment_per_student_peer_median      REAL,
    endowment_per_student_peer_pct         REAL,
    endowment_per_student_trend_1yr        REAL,
    endowment_per_student_trend_3yr        REAL,
    endowment_per_student_trend_dir        TEXT,

    -- endowment_spending_rate (lower-is-better) | schedule_d
    -- grants_from_endowment / endowment_boy; NULL if grants<=0
    endowment_spending_rate_value            REAL,
    endowment_spending_rate_peer_median      REAL,
    endowment_spending_rate_peer_pct         REAL,
    endowment_spending_rate_trend_1yr        REAL,
    endowment_spending_rate_trend_3yr        REAL,
    endowment_spending_rate_trend_dir        TEXT,

    -- endowment_runway (higher-is-better) | schedule_d
    -- endowment_eoy / total_functional_expenses (years)
    endowment_runway_value            REAL,
    endowment_runway_peer_median      REAL,
    endowment_runway_peer_pct         REAL,
    endowment_runway_trend_1yr        REAL,
    endowment_runway_trend_3yr        REAL,
    endowment_runway_trend_dir        TEXT,

    -- fundraising_efficiency (higher-is-better) | part_ix
    -- contributions / fundraising_expenses
    fundraising_efficiency_value            REAL,
    fundraising_efficiency_peer_median      REAL,
    fundraising_efficiency_peer_pct         REAL,
    fundraising_efficiency_trend_1yr        REAL,
    fundraising_efficiency_trend_3yr        REAL,
    fundraising_efficiency_trend_dir        TEXT,

    -- overhead_ratio (lower-is-better) | part_ix
    -- (mgmt_general + fundraising) / total_expenses
    overhead_ratio_value            REAL,
    overhead_ratio_peer_median      REAL,
    overhead_ratio_peer_pct         REAL,
    overhead_ratio_trend_1yr        REAL,
    overhead_ratio_trend_3yr        REAL,
    overhead_ratio_trend_dir        TEXT,

    -- program_services_pct (higher-is-better) | part_ix
    -- total_prog_services / total_functional_expenses
    program_services_pct_value            REAL,
    program_services_pct_peer_median      REAL,
    program_services_pct_peer_pct         REAL,
    program_services_pct_trend_1yr        REAL,
    program_services_pct_trend_3yr        REAL,
    program_services_pct_trend_dir        TEXT,

    -- revenue_per_fte (higher-is-better) | 990+e12
    -- total_revenue / fte12
    revenue_per_fte_value            REAL,
    revenue_per_fte_peer_median      REAL,
    revenue_per_fte_peer_pct         REAL,
    revenue_per_fte_trend_1yr        REAL,
    revenue_per_fte_trend_3yr        REAL,
    revenue_per_fte_trend_dir        TEXT,

    -- expense_per_fte (lower-is-better) | 990+e12
    -- total_expenses / fte12
    expense_per_fte_value            REAL,
    expense_per_fte_peer_median      REAL,
    expense_per_fte_peer_pct         REAL,
    expense_per_fte_trend_1yr        REAL,
    expense_per_fte_trend_3yr        REAL,
    expense_per_fte_trend_dir        TEXT,

    -- enrollment_3yr_cagr (higher-is-better) | ipeds_ef
    -- (enrtot_t / enrtot_{t-3})^(1/3) - 1
    enrollment_3yr_cagr_value            REAL,
    enrollment_3yr_cagr_peer_median      REAL,
    enrollment_3yr_cagr_peer_pct         REAL,
    enrollment_3yr_cagr_trend_1yr        REAL,
    enrollment_3yr_cagr_trend_3yr        REAL,
    enrollment_3yr_cagr_trend_dir        TEXT,

    -- yield_rate (higher-is-better) | ipeds_adm
    -- enrolled / admitted
    yield_rate_value            REAL,
    yield_rate_peer_median      REAL,
    yield_rate_peer_pct         REAL,
    yield_rate_trend_1yr        REAL,
    yield_rate_trend_3yr        REAL,
    yield_rate_trend_dir        TEXT,

    -- admit_rate (lower-is-better) | ipeds_adm
    -- admitted / applied
    admit_rate_value            REAL,
    admit_rate_peer_median      REAL,
    admit_rate_peer_pct         REAL,
    admit_rate_trend_1yr        REAL,
    admit_rate_trend_3yr        REAL,
    admit_rate_trend_dir        TEXT,

    -- app_3yr_cagr (higher-is-better) | ipeds_adm
    -- (applcn_t / applcn_{t-3})^(1/3) - 1
    app_3yr_cagr_value            REAL,
    app_3yr_cagr_peer_median      REAL,
    app_3yr_cagr_peer_pct         REAL,
    app_3yr_cagr_trend_1yr        REAL,
    app_3yr_cagr_trend_3yr        REAL,
    app_3yr_cagr_trend_dir        TEXT,

    -- grad_rate_150 (higher-is-better) | scorecard
    -- completion_rate_4yr (scorecard; single year 2023)
    grad_rate_150_value            REAL,
    grad_rate_150_peer_median      REAL,
    grad_rate_150_peer_pct         REAL,
    grad_rate_150_trend_1yr        REAL,
    grad_rate_150_trend_3yr        REAL,
    grad_rate_150_trend_dir        TEXT,

    -- retention_rate (higher-is-better) | NOT_LOADED
    -- EF Part D not loaded — always NULL; see known gaps
    retention_rate_value            REAL,
    retention_rate_peer_median      REAL,
    retention_rate_peer_pct         REAL,
    retention_rate_trend_1yr        REAL,
    retention_rate_trend_3yr        REAL,
    retention_rate_trend_dir        TEXT,

    -- grad_enrollment_pct (higher-is-better) | ipeds_ef
    -- enrgrad / enrtot
    grad_enrollment_pct_value            REAL,
    grad_enrollment_pct_peer_median      REAL,
    grad_enrollment_pct_peer_pct         REAL,
    grad_enrollment_pct_trend_1yr        REAL,
    grad_enrollment_pct_trend_3yr        REAL,
    grad_enrollment_pct_trend_dir        TEXT,

    -- pell_pct (higher-is-better) | ipeds_sfa
    -- pct_pell (fraction of students receiving Pell)
    pell_pct_value            REAL,
    pell_pct_peer_median      REAL,
    pell_pct_peer_pct         REAL,
    pell_pct_trend_1yr        REAL,
    pell_pct_trend_3yr        REAL,
    pell_pct_trend_dir        TEXT,

    -- net_price (lower-is-better) | scorecard
    -- avg_net_price_priv or avg_net_price_pub (single year 2023)
    net_price_value            REAL,
    net_price_peer_median      REAL,
    net_price_peer_pct         REAL,
    net_price_trend_1yr        REAL,
    net_price_trend_3yr        REAL,
    net_price_trend_dir        TEXT,

    -- earnings_to_debt_ratio (higher-is-better) | scorecard
    -- earnings_6yr_median / median_debt
    earnings_to_debt_ratio_value            REAL,
    earnings_to_debt_ratio_peer_median      REAL,
    earnings_to_debt_ratio_peer_pct         REAL,
    earnings_to_debt_ratio_trend_1yr        REAL,
    earnings_to_debt_ratio_trend_3yr        REAL,
    earnings_to_debt_ratio_trend_dir        TEXT,

    -- net_price_to_earnings (lower-is-better) | scorecard
    -- avg_net_price / earnings_6yr_median
    net_price_to_earnings_value            REAL,
    net_price_to_earnings_peer_median      REAL,
    net_price_to_earnings_peer_pct         REAL,
    net_price_to_earnings_trend_1yr        REAL,
    net_price_to_earnings_trend_3yr        REAL,
    net_price_to_earnings_trend_dir        TEXT,

    -- athletics_to_expense_pct (lower-is-better) | eada+990
    -- eada_total_expense / 990_total_functional_expenses
    athletics_to_expense_pct_value            REAL,
    athletics_to_expense_pct_peer_median      REAL,
    athletics_to_expense_pct_peer_pct         REAL,
    athletics_to_expense_pct_trend_1yr        REAL,
    athletics_to_expense_pct_trend_3yr        REAL,
    athletics_to_expense_pct_trend_dir        TEXT,

    -- athletics_net (higher-is-better) | eada
    -- grnd_total_revenue - grnd_total_expense
    athletics_net_value            REAL,
    athletics_net_peer_median      REAL,
    athletics_net_peer_pct         REAL,
    athletics_net_trend_1yr        REAL,
    athletics_net_trend_3yr        REAL,
    athletics_net_trend_dir        TEXT,

    -- athletics_per_student (lower-is-better) | eada+ef
    -- grnd_total_expense / enrollment
    athletics_per_student_value            REAL,
    athletics_per_student_peer_median      REAL,
    athletics_per_student_peer_pct         REAL,
    athletics_per_student_trend_1yr        REAL,
    athletics_per_student_trend_3yr        REAL,
    athletics_per_student_trend_dir        TEXT,

    loaded_at               TEXT DEFAULT (datetime('now')),

    PRIMARY KEY (unitid, survey_year)
);

CREATE INDEX IF NOT EXISTS idx_iq_unitid      ON institution_quant (unitid);
CREATE INDEX IF NOT EXISTS idx_iq_survey_year ON institution_quant (survey_year);
CREATE INDEX IF NOT EXISTS idx_iq_ein         ON institution_quant (ein);

