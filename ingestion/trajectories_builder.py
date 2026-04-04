#!/usr/bin/env python3
"""
ingestion/trajectories_builder.py
----------------------------------
Quant analytics layer: fits trajectory models for key institutional metrics.

For each institution-metric combination, fits two windows:
  1. Full available history
  2. Rolling 10-year window (most recent 10 data points)

Models fitted: linear, exponential, power_law, logistic.
Best fit = highest R². Ties broken: linear > exponential > power_law > logistic.

Structural break detection via ruptures (Pelt RBF, pen=3).
Regime classification and trajectory_summary are fully deterministic — no model calls.

Minimum data points: 5. Insufficient-data rows are recorded honestly.

Usage:
    # Full build — all institutions, all metrics
    .venv/bin/python3 ingestion/trajectories_builder.py \\
        --ipeds   data/databases/ipeds_data.db \\
        --quant   data/databases/institution_quant.db \\
        --990     data/databases/990_data.db \\
        --out     data/databases/institution_trajectories.db \\
        --stage   all

    # Single institution (for testing)
    .venv/bin/python3 ingestion/trajectories_builder.py \\
        --ipeds   data/databases/ipeds_data.db \\
        --quant   data/databases/institution_quant.db \\
        --990     data/databases/990_data.db \\
        --out     data/databases/institution_trajectories.db \\
        --unitid  164739
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import scipy.stats
import scipy.optimize

try:
    import ruptures as rpt
    HAS_RUPTURES = True
except ImportError:
    HAS_RUPTURES = False
    logging.warning("ruptures not available — breakpoint detection disabled")

logger = logging.getLogger(__name__)

FORMULA_VERSION = '1.0'
MIN_DATA_POINTS = 5

# ─── metric label strings ────────────────────────────────────────────────────

METRIC_LABELS = {
    'enrollment_total':          'Total enrollment',
    'tuition_revenue':           'Tuition revenue',
    'operating_margin':          'Operating margin',
    'tuition_dependency':        'Tuition dependency',
    'endowment_eoy':             'Endowment (EOY)',
    'net_assets':                'Net assets',
    'total_functional_expenses': 'Total functional expenses',
}

PATTERN_LABELS = {
    'linear':              'linearly',
    'exponential':         'exponentially',
    'power_law':           'along a power curve',
    'logistic':            'along an S-curve',
    'flat':                'without a statistically significant trend',
    'insufficient_data':   'with insufficient data for trend analysis',
}


# ─── curve fitting ────────────────────────────────────────────────────────────

def _r2_from_residuals(y: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return float(1.0 - ss_res / ss_tot)


def fit_linear(years: list[int], values: list[float]) -> dict | None:
    x = np.array(years, dtype=float)
    y = np.array(values, dtype=float)
    result = scipy.stats.linregress(x, y)
    r2 = float(result.rvalue ** 2)
    return {
        'r2': r2,
        'params': {'slope': float(result.slope), 'intercept': float(result.intercept)},
    }


def fit_exponential(years: list[int], values: list[float]) -> dict | None:
    """fit log(y) = log(a) + b*x. Only valid when all y > 0."""
    y = np.array(values, dtype=float)
    if np.any(y <= 0):
        return None
    x = np.array(years, dtype=float)
    log_y = np.log(y)
    result = scipy.stats.linregress(x, log_y)
    a = float(np.exp(result.intercept))
    b = float(result.slope)
    y_pred = a * np.exp(b * x)
    r2 = _r2_from_residuals(y, y_pred)
    return {
        'r2': r2,
        'params': {'a': a, 'b': b},
    }


def fit_power_law(years: list[int], values: list[float]) -> dict | None:
    """fit log(y) = log(a) + b*log(x), x = year - year_start + 1. Only valid when all y > 0."""
    y = np.array(values, dtype=float)
    if np.any(y <= 0):
        return None
    year_start = years[0]
    x = np.array([yr - year_start + 1 for yr in years], dtype=float)
    if np.any(x <= 0):
        return None
    log_y = np.log(y)
    log_x = np.log(x)
    result = scipy.stats.linregress(log_x, log_y)
    a = float(np.exp(result.intercept))
    b = float(result.slope)
    y_pred = a * (x ** b)
    r2 = _r2_from_residuals(y, y_pred)
    return {
        'r2': r2,
        'params': {'a': a, 'b': b},
    }


def _logistic_fn(x: np.ndarray, L: float, k: float, x0: float) -> np.ndarray:
    return L / (1.0 + np.exp(-k * (x - x0)))


def fit_logistic(years: list[int], values: list[float]) -> dict | None:
    """Bounded logistic fit. L in [max(y), 3*max(y)]."""
    x = np.array(years, dtype=float)
    y = np.array(values, dtype=float)
    max_y = float(np.max(np.abs(y)))
    if max_y == 0:
        return None
    # Use midpoint of x range as initial x0 guess
    x0_guess = float(np.mean(x))
    p0 = [max_y * 1.5, 0.5, x0_guess]
    bounds = (
        [float(np.max(y)), -10.0, float(x[0])],
        [3.0 * float(np.max(y)), 10.0, float(x[-1])],
    )
    try:
        popt, _ = scipy.optimize.curve_fit(
            _logistic_fn, x, y, p0=p0, bounds=bounds,
            maxfev=5000,
        )
        L, k, x0 = float(popt[0]), float(popt[1]), float(popt[2])
        y_pred = _logistic_fn(x, L, k, x0)
        r2 = _r2_from_residuals(y, y_pred)
        # approx slope for direction_from_params
        approx_slope = float(y_pred[-1] - y_pred[0]) / max(len(y) - 1, 1)
        return {
            'r2': r2,
            'params': {'L': L, 'k': k, 'x0': x0, 'slope': approx_slope},
        }
    except (RuntimeError, ValueError, scipy.optimize.OptimizeWarning):
        return None


def fit_all_models(years: list[int], values: list[float]) -> dict:
    """Fit all four models; return dict with all R² values and best-fit selection."""
    results = {}
    results['linear']      = fit_linear(years, values)
    results['exponential'] = fit_exponential(years, values)
    results['power_law']   = fit_power_law(years, values)
    results['logistic']    = fit_logistic(years, values)

    # Collect valid fits with their R² values
    # Tie-breaking order: linear > exponential > power_law > logistic
    priority = ['linear', 'exponential', 'power_law', 'logistic']
    best_model = None
    best_r2 = None

    for model in priority:
        res = results[model]
        if res is None:
            continue
        r2 = res['r2']
        if best_r2 is None or r2 > best_r2:
            best_model = model
            best_r2 = r2

    return {
        'linear_r2':      results['linear']['r2']      if results['linear']      else None,
        'exponential_r2': results['exponential']['r2'] if results['exponential'] else None,
        'power_law_r2':   results['power_law']['r2']   if results['power_law']   else None,
        'logistic_r2':    results['logistic']['r2']    if results['logistic']    else None,
        'best_fit_model': best_model if best_model else 'flat',
        'best_fit_r2':    best_r2,
        'best_fit_params': (
            json.dumps(results[best_model]['params'], default=float)
            if best_model and results[best_model]
            else None
        ),
    }


# ─── breakpoint detection ────────────────────────────────────────────────────

def detect_breakpoint(y_series: list[float], years: list[int]) -> dict:
    if not HAS_RUPTURES or len(y_series) < 8:
        return {'detected': 0}
    try:
        model = rpt.Pelt(model='rbf').fit(np.array(y_series))
        breakpoints = model.predict(pen=3)
        # ruptures returns [n] for no break (just the end of the series)
        if len(breakpoints) == 1:
            return {'detected': 0}
        break_idx = breakpoints[0]
        # Need at least 2 points on each side for linregress
        if break_idx < 2 or break_idx > len(y_series) - 2:
            return {'detected': 0}
        break_year = years[break_idx - 1]
        pre_slope  = float(scipy.stats.linregress(years[:break_idx], y_series[:break_idx]).slope)
        post_slope = float(scipy.stats.linregress(years[break_idx:], y_series[break_idx:]).slope)
        # Confidence: piecewise R² improvement over single linear R²
        full_r2 = float(scipy.stats.linregress(years, y_series).rvalue ** 2)
        pre_r2  = float(scipy.stats.linregress(years[:break_idx], y_series[:break_idx]).rvalue ** 2)
        post_r2 = float(scipy.stats.linregress(years[break_idx:], y_series[break_idx:]).rvalue ** 2)
        piecewise_r2 = (pre_r2 + post_r2) / 2
        confidence = piecewise_r2 - full_r2
        return {
            'detected': 1 if confidence > 0.15 else 0,
            'breakpoint_year':       break_year,
            'breakpoint_confidence': round(confidence, 4),
            'pre_break_slope':       pre_slope,
            'post_break_slope':      post_slope,
        }
    except Exception:
        return {'detected': 0}


# ─── regime classification ───────────────────────────────────────────────────

def classify_regime(
    best_fit_model: str | None,
    best_fit_params: str | None,
    breakpoint_detected: int,
    pre_break_slope: float | None,
    post_break_slope: float | None,
    data_points: int,
    values: list[float] | None = None,
    years: list[int] | None = None,
) -> str:
    if data_points < MIN_DATA_POINTS or best_fit_model in ('insufficient_data', None):
        return 'insufficient_data'
    params = json.loads(best_fit_params) if best_fit_params else {}
    slope  = params.get('slope', params.get('b', 0))

    # Plateau detection for logistic fits: absolute final-segment slope < 5% of series mean.
    # Uses post_break_slope when a breakpoint was detected, otherwise the final-third slope.
    if best_fit_model == 'logistic' and values and len(values) >= MIN_DATA_POINTS:
        series_mean = float(np.mean(np.abs(values)))
        plateau_threshold = 0.05 * series_mean if series_mean > 0 else 0.0
        if breakpoint_detected and post_break_slope is not None:
            final_slope_abs = abs(post_break_slope)
        else:
            n = len(values)
            third = max(n // 3, 2)
            final_y = list(values[-third:])
            final_x = list(years[-third:]) if years else list(range(third))
            if len(final_y) >= 2:
                final_slope_abs = abs(float(scipy.stats.linregress(final_x, final_y).slope))
            else:
                final_slope_abs = abs(slope)
        if final_slope_abs < plateau_threshold:
            return 'plateau'

    if breakpoint_detected:
        pre  = pre_break_slope or 0
        post = post_break_slope or 0
        if post > 0 and pre < 0:
            return 'recovering'
        if post < 0 and pre > 0:
            return 'declining'
        if pre != 0 and post > pre * 1.5:
            return 'accelerating'
    if best_fit_model == 'flat' or abs(slope) < 0.005:
        return 'stable'
    if slope > 0:
        return 'growth'
    if slope < 0:
        return 'declining'
    return 'stable'


# ─── deterministic trajectory summary ────────────────────────────────────────

def direction_from_params(model: str, params_json: str | None) -> str:
    if model in ('flat', 'insufficient_data'):
        return 'moved'
    params = json.loads(params_json) if params_json else {}
    slope  = params.get('slope', params.get('b', 0))
    return 'grew' if slope > 0 else 'declined'


def direction_from_slope(slope: float | None) -> str:
    if slope is None:
        return 'unknown trajectory'
    return 'growth' if slope > 0 else 'decline'


def build_trajectory_summary(row: dict) -> str:
    label   = METRIC_LABELS.get(row['metric'], row['metric'])
    pattern = PATTERN_LABELS.get(row['best_fit_model'] or 'insufficient_data', 'with unknown pattern')
    regime  = row.get('regime', '')
    if regime == 'plateau':
        direction = 'plateaued'
    else:
        direction = direction_from_params(row['best_fit_model'] or 'insufficient_data', row['best_fit_params'])
    r2_str  = (f"R²={row['best_fit_r2']:.2f}"
               if row['best_fit_r2'] is not None else 'R²=n/a')
    base = (
        f"{label} {direction} {pattern} "
        f"from {row['year_start']} to {row['year_end']} "
        f"({row['data_points']} observations, {r2_str})"
    )
    if row.get('breakpoint_detected'):
        pre  = direction_from_slope(row.get('pre_break_slope'))
        post = direction_from_slope(row.get('post_break_slope'))
        base += (
            f", with a structural break in {row['breakpoint_year']} "
            f"({pre} before, {post} after)"
        )
    return base + '.'


# ─── data loading ─────────────────────────────────────────────────────────────

def load_enrollment_series(ipeds_conn: sqlite3.Connection, unitid: int) -> list[tuple[int, float]]:
    rows = ipeds_conn.execute(
        """SELECT survey_year, enrtot FROM ipeds_ef
           WHERE unitid = ? AND enrtot IS NOT NULL AND survey_year BETWEEN 2000 AND 2022
           ORDER BY survey_year""",
        (unitid,),
    ).fetchall()
    return [(r[0], float(r[1])) for r in rows]


def load_quant_series(
    quant_conn: sqlite3.Connection, unitid: int, column: str
) -> list[tuple[int, float]]:
    rows = quant_conn.execute(
        f"""SELECT survey_year, {column} FROM institution_quant
            WHERE unitid = ? AND {column} IS NOT NULL AND survey_year BETWEEN 2019 AND 2022
            ORDER BY survey_year""",
        (unitid,),
    ).fetchall()
    return [(r[0], float(r[1])) for r in rows]


def load_990_series(
    db990_conn: sqlite3.Connection, ein: str | None, column: str
) -> list[tuple[int, float]]:
    """Load 990 financials; convert fiscal_year_end → survey_year (fy - 1)."""
    if not ein:
        return []
    rows = db990_conn.execute(
        f"""SELECT fiscal_year_end, {column} FROM form990_filings
            WHERE ein = ? AND {column} IS NOT NULL AND {column} > 0
            ORDER BY fiscal_year_end""",
        (ein,),
    ).fetchall()
    # Convert: survey_year = fiscal_year_end - 1
    return [(r[0] - 1, float(r[1])) for r in rows]


def load_schedule_d_series(
    db990_conn: sqlite3.Connection, ein: str | None
) -> list[tuple[int, float]]:
    """Load endowment_eoy; store fiscal_year_end directly (spec: 'fiscal_years')."""
    if not ein:
        return []
    rows = db990_conn.execute(
        """SELECT fiscal_year_end, endowment_eoy FROM form990_schedule_d
           WHERE ein = ? AND endowment_eoy IS NOT NULL AND endowment_eoy > 0
           ORDER BY fiscal_year_end""",
        (ein,),
    ).fetchall()
    return [(r[0], float(r[1])) for r in rows]


def get_series(
    metric: str,
    unitid: int,
    ein: str | None,
    ipeds_conn: sqlite3.Connection,
    quant_conn: sqlite3.Connection,
    db990_conn: sqlite3.Connection,
) -> tuple[list[tuple[int, float]], str]:
    """Return (year_value_pairs, data_source_string)."""
    if metric == 'enrollment_total':
        return load_enrollment_series(ipeds_conn, unitid), 'ipeds_ef.enrtot'
    if metric == 'tuition_revenue':
        return load_990_series(db990_conn, ein, 'program_service_revenue'), 'form990_filings.program_service_revenue'
    if metric == 'operating_margin':
        return load_quant_series(quant_conn, unitid, 'operating_margin_value'), 'institution_quant.operating_margin_value'
    if metric == 'tuition_dependency':
        return load_quant_series(quant_conn, unitid, 'tuition_dependency_value'), 'institution_quant.tuition_dependency_value'
    if metric == 'endowment_eoy':
        return load_schedule_d_series(db990_conn, ein), 'form990_schedule_d.endowment_eoy'
    if metric == 'net_assets':
        return load_990_series(db990_conn, ein, 'net_assets_eoy'), 'form990_filings.net_assets_eoy'
    if metric == 'total_functional_expenses':
        return load_990_series(db990_conn, ein, 'total_functional_expenses'), 'form990_filings.total_functional_expenses'
    raise ValueError(f'Unknown metric: {metric}')


# ─── window slicing ───────────────────────────────────────────────────────────

def make_windows(data: list[tuple[int, float]]) -> list[list[tuple[int, float]]]:
    """
    Return list of windows to fit:
      - Full history (all data points)
      - Rolling 10-year (last 10 points), only if distinct from full history
    """
    if not data:
        return [data]
    windows = [data]
    if len(data) > 10:
        windows.append(data[-10:])
    return windows


# ─── row construction ─────────────────────────────────────────────────────────

def build_row(
    unitid: int,
    metric: str,
    data: list[tuple[int, float]],
    data_source: str,
) -> dict:
    computed_at = datetime.now(timezone.utc).isoformat()
    n = len(data)

    base = {
        'unitid':                   unitid,
        'metric':                   metric,
        'year_start':               data[0][0] if data else 0,
        'year_end':                 data[-1][0] if data else 0,
        'data_points':              n,
        'data_source':              data_source,
        'best_fit_model':           'insufficient_data',
        'best_fit_r2':              None,
        'best_fit_params':          None,
        'linear_r2':                None,
        'exponential_r2':           None,
        'power_law_r2':             None,
        'logistic_r2':              None,
        'breakpoint_detected':      0,
        'breakpoint_year':          None,
        'breakpoint_confidence':    None,
        'pre_break_slope':          None,
        'post_break_slope':         None,
        'regime':                   'insufficient_data',
        'trajectory_summary':       None,
        'trajectory_summary_method': 'deterministic_v1',
        'computed_at':              computed_at,
        'formula_version':          FORMULA_VERSION,
        'min_data_points_req':      MIN_DATA_POINTS,
    }

    if n < MIN_DATA_POINTS:
        base['trajectory_summary'] = build_trajectory_summary(base)
        return base

    years  = [d[0] for d in data]
    values = [d[1] for d in data]

    # Curve fitting
    fit = fit_all_models(years, values)
    base.update(fit)

    # Breakpoint detection
    bp = detect_breakpoint(values, years)
    base['breakpoint_detected']   = bp.get('detected', 0)
    base['breakpoint_year']       = bp.get('breakpoint_year')
    base['breakpoint_confidence'] = bp.get('breakpoint_confidence')
    base['pre_break_slope']       = bp.get('pre_break_slope')
    base['post_break_slope']      = bp.get('post_break_slope')

    # Regime classification
    base['regime'] = classify_regime(
        base['best_fit_model'],
        base['best_fit_params'],
        base['breakpoint_detected'],
        base['pre_break_slope'],
        base['post_break_slope'],
        n,
        values=values,
        years=years,
    )

    # Deterministic summary
    base['trajectory_summary'] = build_trajectory_summary(base)

    return base


# ─── database upsert ──────────────────────────────────────────────────────────

INSERT_SQL = """
INSERT OR REPLACE INTO institution_trajectories (
    unitid, metric, year_start, year_end, data_points, data_source,
    best_fit_model, best_fit_r2, best_fit_params,
    linear_r2, exponential_r2, power_law_r2, logistic_r2,
    breakpoint_detected, breakpoint_year, breakpoint_confidence,
    pre_break_slope, post_break_slope,
    regime, trajectory_summary, trajectory_summary_method,
    computed_at, formula_version, min_data_points_req
) VALUES (
    :unitid, :metric, :year_start, :year_end, :data_points, :data_source,
    :best_fit_model, :best_fit_r2, :best_fit_params,
    :linear_r2, :exponential_r2, :power_law_r2, :logistic_r2,
    :breakpoint_detected, :breakpoint_year, :breakpoint_confidence,
    :pre_break_slope, :post_break_slope,
    :regime, :trajectory_summary, :trajectory_summary_method,
    :computed_at, :formula_version, :min_data_points_req
)
"""


def upsert_rows(out_conn: sqlite3.Connection, rows: list[dict]) -> None:
    out_conn.executemany(INSERT_SQL, rows)


# ─── main builder ─────────────────────────────────────────────────────────────

METRICS = [
    'enrollment_total',
    'tuition_revenue',
    'operating_margin',
    'tuition_dependency',
    'endowment_eoy',
    'net_assets',
    'total_functional_expenses',
]


def process_institution(
    unitid: int,
    ein: str | None,
    ipeds_conn: sqlite3.Connection,
    quant_conn: sqlite3.Connection,
    db990_conn: sqlite3.Connection,
    out_conn: sqlite3.Connection,
) -> int:
    """Fit all metrics for one institution. Returns number of rows written."""
    rows = []
    for metric in METRICS:
        data, data_source = get_series(metric, unitid, ein, ipeds_conn, quant_conn, db990_conn)
        for window in make_windows(data):
            if not window:
                # Store an explicit insufficient_data row for the metric (no data at all)
                row = build_row(unitid, metric, [], data_source)
                rows.append(row)
                break  # only one empty row per metric
            rows.append(build_row(unitid, metric, window, data_source))
    upsert_rows(out_conn, rows)
    return len(rows)


def run(
    ipeds_db: str,
    quant_db: str,
    db990: str,
    out_db: str,
    unitid_filter: int | None = None,
) -> dict:
    t0 = time.time()

    ipeds_conn = sqlite3.connect(ipeds_db)
    ipeds_conn.row_factory = sqlite3.Row
    quant_conn = sqlite3.connect(quant_db)
    db990_conn = sqlite3.connect(db990)
    out_conn   = sqlite3.connect(out_db)
    out_conn.execute('PRAGMA journal_mode=WAL')

    # Fetch institution list
    if unitid_filter:
        institutions = ipeds_conn.execute(
            'SELECT unitid, ein FROM institution_master WHERE unitid = ?',
            (unitid_filter,),
        ).fetchall()
    else:
        institutions = ipeds_conn.execute(
            'SELECT unitid, ein FROM institution_master ORDER BY unitid'
        ).fetchall()

    logger.info(f"Processing {len(institutions)} institutions × {len(METRICS)} metrics")

    total_rows = 0
    batch = []
    BATCH_SIZE = 200

    for i, inst in enumerate(institutions):
        unitid = inst[0]
        ein    = inst[1] if inst[1] and inst[1] not in ('', '-1') else None
        try:
            n = process_institution(unitid, ein, ipeds_conn, quant_conn, db990_conn, out_conn)
            total_rows += n
        except Exception as e:
            logger.warning(f"  unitid={unitid}: {e}")

        if (i + 1) % BATCH_SIZE == 0:
            out_conn.commit()
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            logger.info(f"  {i+1}/{len(institutions)} institutions ({rate:.0f}/s, {total_rows} rows)")

    out_conn.commit()
    elapsed = time.time() - t0
    logger.info(f"Done: {total_rows} rows in {elapsed:.1f}s")

    # Summary stats
    stats = out_conn.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN best_fit_r2 > 0.80 THEN 1 ELSE 0 END) as high_r2,
                  SUM(CASE WHEN breakpoint_detected = 1 THEN 1 ELSE 0 END) as breakpoints,
                  SUM(CASE WHEN best_fit_model = 'insufficient_data' THEN 1 ELSE 0 END) as insuf
           FROM institution_trajectories WHERE formula_version = ?""",
        (FORMULA_VERSION,),
    ).fetchone()

    return {
        'total_rows':         stats[0],
        'high_r2_count':      stats[1],
        'breakpoints':        stats[2],
        'insufficient_data':  stats[3],
        'elapsed_s':          round(elapsed, 1),
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    parser = argparse.ArgumentParser(description='Build institution_trajectories')
    parser.add_argument('--ipeds',   default='data/databases/ipeds_data.db')
    parser.add_argument('--quant',   default='data/databases/institution_quant.db')
    parser.add_argument('--990',     dest='db990', default='data/databases/990_data.db')
    parser.add_argument('--out',     default='data/databases/institution_trajectories.db')
    parser.add_argument('--stage',   choices=['all'], default='all')
    parser.add_argument('--unitid',  type=int, default=None,
                        help='Process single institution (for testing)')
    args = parser.parse_args()

    result = run(
        ipeds_db=args.ipeds,
        quant_db=args.quant,
        db990=args.db990,
        out_db=args.out,
        unitid_filter=args.unitid,
    )
    logger.info(f"Result: {result}")


if __name__ == '__main__':
    main()
