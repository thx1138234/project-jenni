CREATE TABLE IF NOT EXISTS institution_trajectories (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    unitid                   INTEGER NOT NULL,
    metric                   TEXT NOT NULL,
    year_start               INTEGER NOT NULL,
    year_end                 INTEGER NOT NULL,
    data_points              INTEGER NOT NULL,
    data_source              TEXT NOT NULL,
    best_fit_model           TEXT,
    best_fit_r2              REAL,
    best_fit_params          TEXT,
    linear_r2                REAL,
    exponential_r2           REAL,
    power_law_r2             REAL,
    logistic_r2              REAL,
    breakpoint_detected      INTEGER DEFAULT 0,
    breakpoint_year          INTEGER,
    breakpoint_confidence    REAL,
    pre_break_slope          REAL,
    post_break_slope         REAL,
    regime                   TEXT,
    trajectory_summary       TEXT,
    trajectory_summary_method TEXT NOT NULL DEFAULT 'deterministic_v1',
    computed_at              TEXT NOT NULL,
    formula_version          TEXT NOT NULL DEFAULT '1.0',
    min_data_points_req      INTEGER DEFAULT 5,
    UNIQUE (unitid, metric, year_start, year_end, formula_version),
    FOREIGN KEY (unitid) REFERENCES institution_master(unitid)
);

CREATE INDEX IF NOT EXISTS idx_traj_unitid
    ON institution_trajectories(unitid);
CREATE INDEX IF NOT EXISTS idx_traj_metric_regime
    ON institution_trajectories(metric, regime);
CREATE INDEX IF NOT EXISTS idx_traj_best_fit
    ON institution_trajectories(best_fit_model, best_fit_r2);
CREATE INDEX IF NOT EXISTS idx_traj_formula_version
    ON institution_trajectories(formula_version);
