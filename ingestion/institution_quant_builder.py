#!/usr/bin/env python3
"""
ingestion/institution_quant_builder.py
---------------------------------------
Build institution_quant — the authoritative quantitative metrics layer.
One row per (unitid, survey_year). Pure math only: no thresholds, no composites.

Build order (matches commit history stages):
  --stage financial   : 12 financial metrics from 990 + schedule_d + part_ix + e12
  --stage demand      : 8 demand metrics from ipeds_ef / ipeds_adm / ipeds_sfa
  --stage value       : 3 value + 3 athletics metrics from scorecard + eada
  --stage peers       : compute peer_median + peer_pct for all metrics
  --stage trends      : compute trend_1yr, trend_3yr, trend_dir for all metrics
  --stage completeness: compute data_completeness_pct
  --stage all         : run all stages in order (default)

Year convention:
  institution_quant.survey_year = IPEDS fall start year
  990 join:  fiscal_year_end = survey_year + 1
  EADA join: eada.survey_year = institution_quant.survey_year + 1

Peer groups: Carnegie basic classification, min 5 institutions with non-NULL values.

Trend direction: 'improving' | 'stable' | 'deteriorating'
  stable threshold: |relative_change| < 0.02 (2%)
  polarity defined per metric in METRIC_DIRECTION dict.

Usage:
    .venv/bin/python3 ingestion/institution_quant_builder.py \\
        --db990   data/databases/990_data.db \\
        --ipeds   data/databases/ipeds_data.db \\
        --eada    data/databases/eada_data.db \\
        --scorecard data/databases/scorecard_data.db \\
        --out     data/databases/institution_quant.db \\
        --stage   all
"""

import argparse
import logging
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "institution_quant_schema.sql"
SURVEY_YEARS = list(range(2016, 2023))   # 2016-2022; trends need lookback to 2016 for 3yr at 2019
TARGET_YEARS = list(range(2019, 2023))   # 2019-2022: rows we produce

STABLE_THRESHOLD = 0.02   # 2% relative change = stable

# Metric direction: True = higher is better, False = lower is better
METRIC_DIRECTION: dict[str, bool] = {
    "tuition_dependency":      False,
    "operating_margin":        True,
    "debt_to_assets":          False,
    "debt_to_revenue":         False,
    "endowment_per_student":   True,
    "endowment_spending_rate": False,
    "endowment_runway":        True,
    "fundraising_efficiency":  True,
    "overhead_ratio":          False,
    "program_services_pct":    True,
    "revenue_per_fte":         True,
    "expense_per_fte":         False,
    "enrollment_3yr_cagr":     True,
    "yield_rate":              True,
    "admit_rate":              False,
    "app_3yr_cagr":            True,
    "grad_rate_150":           True,
    "retention_rate":          True,
    "grad_enrollment_pct":     True,
    "pell_pct":                True,
    "net_price":               False,
    "earnings_to_debt_ratio":  True,
    "net_price_to_earnings":   False,
    "athletics_to_expense_pct": False,
    "athletics_net":           True,
    "athletics_per_student":   False,
}

ALL_METRICS = list(METRIC_DIRECTION.keys())
MIN_PEER_SIZE = 5


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def safe_div(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


def cagr(start_val, end_val, years):
    """Compound annual growth rate. Returns None if inputs invalid."""
    if start_val is None or end_val is None or start_val <= 0 or years <= 0:
        return None
    return (end_val / start_val) ** (1.0 / years) - 1.0


def median(values):
    v = sorted(v for v in values if v is not None)
    if not v:
        return None
    n = len(v)
    mid = n // 2
    return v[mid] if n % 2 else (v[mid - 1] + v[mid]) / 2


def percentile_rank(value, peer_values):
    """Fraction of peer_values strictly less than value (0.0–1.0)."""
    valid = [v for v in peer_values if v is not None]
    if not valid or value is None:
        return None
    below = sum(1 for v in valid if v < value)
    return round(below / len(valid), 4)


def trend_direction(current, prior, higher_is_better: bool) -> str | None:
    if current is None or prior is None or prior == 0:
        return None
    rel_change = (current - prior) / abs(prior)
    if abs(rel_change) < STABLE_THRESHOLD:
        return "stable"
    improving = rel_change > 0 if higher_is_better else rel_change < 0
    return "improving" if improving else "deteriorating"


# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

def init_db(out_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(out_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    return conn


def ensure_row(conn, unitid, ein, survey_year):
    conn.execute("""
        INSERT OR IGNORE INTO institution_quant (unitid, ein, survey_year, formula_version)
        VALUES (?, ?, ?, '1.0')
    """, (unitid, ein, survey_year))


# ---------------------------------------------------------------------------
# Stage 2: Financial metrics
# ---------------------------------------------------------------------------

def build_financial(conn_out: sqlite3.Connection,
                    conn_990: sqlite3.Connection,
                    conn_ipeds: sqlite3.Connection) -> int:
    """
    Financial metrics from form990_filings, schedule_d, part_ix, ipeds_e12.
    survey_year = fiscal_year_end - 1.
    """
    logger.info("Stage: financial metrics")

    # Canonical EIN→UNITID map
    ein_to_unitid = {}
    for row in conn_ipeds.execute("""
        SELECT ein, MIN(unitid) as unitid FROM institution_master
        WHERE ein IS NOT NULL AND ein != '' AND ein != '-1'
        GROUP BY ein
    """):
        ein_to_unitid[row["ein"]] = row["unitid"]

    # Load 990 filings for fiscal_year_end range needed
    fy_years = [sy + 1 for sy in SURVEY_YEARS]
    placeholders = ",".join("?" * len(fy_years))
    filings = {}
    for row in conn_990.execute(f"""
        SELECT ein, fiscal_year_end, total_revenue, program_service_revenue,
               total_expenses, total_functional_expenses,
               total_assets_eoy, total_liabilities_eoy,
               net_assets_boy, net_assets_eoy, reconciliation_surplus,
               cash_and_equivalents
        FROM form990_filings
        WHERE fiscal_year_end IN ({placeholders})
    """, fy_years):
        key = (row["ein"], row["fiscal_year_end"])
        filings[key] = dict(row)

    # Schedule D
    sched_d = {}
    for row in conn_990.execute(f"""
        SELECT ein, fiscal_year_end, endowment_eoy, endowment_spending_rate, endowment_runway
        FROM form990_schedule_d
        WHERE fiscal_year_end IN ({placeholders})
    """, fy_years):
        sched_d[(row["ein"], row["fiscal_year_end"])] = dict(row)

    # Part IX
    part_ix = {}
    for row in conn_990.execute(f"""
        SELECT ein, fiscal_year_end, fundraising_efficiency, overhead_ratio, prog_services_pct
        FROM form990_part_ix
        WHERE fiscal_year_end IN ({placeholders})
    """, fy_years):
        part_ix[(row["ein"], row["fiscal_year_end"])] = dict(row)

    # IPEDS E12 FTE (keyed by unitid, survey_year)
    e12 = {}
    sy_placeholders = ",".join("?" * len(SURVEY_YEARS))
    for row in conn_ipeds.execute(f"""
        SELECT unitid, survey_year, fte12
        FROM ipeds_e12
        WHERE survey_year IN ({sy_placeholders})
    """, SURVEY_YEARS):
        e12[(row["unitid"], row["survey_year"])] = row["fte12"]

    written = 0
    for (ein, fy), ff in filings.items():
        survey_year = fy - 1
        if survey_year not in TARGET_YEARS:
            continue
        unitid = ein_to_unitid.get(ein)
        if unitid is None:
            continue

        sd = sched_d.get((ein, fy), {})
        px = part_ix.get((ein, fy), {})
        fte = e12.get((unitid, survey_year))

        tv  = ff.get("total_revenue")
        te  = ff.get("total_expenses")
        tfe = ff.get("total_functional_expenses") or te
        psr = ff.get("program_service_revenue")
        la  = ff.get("total_liabilities_eoy")
        aa  = ff.get("total_assets_eoy")
        sur = ff.get("reconciliation_surplus")
        endo = sd.get("endowment_eoy")

        vals = {
            "tuition_dependency":     safe_div(psr, tv),
            "operating_margin":       safe_div(sur, tv),
            "debt_to_assets":         safe_div(la, aa),
            "debt_to_revenue":        safe_div(la, tv),
            "endowment_per_student":  safe_div(endo, fte),
            "endowment_spending_rate": sd.get("endowment_spending_rate"),
            "endowment_runway":       sd.get("endowment_runway"),
            "fundraising_efficiency": px.get("fundraising_efficiency"),
            "overhead_ratio":         px.get("overhead_ratio"),
            "program_services_pct":   px.get("prog_services_pct"),
            "revenue_per_fte":        safe_div(tv, fte),
            "expense_per_fte":        safe_div(te, fte),
        }

        ensure_row(conn_out, unitid, ein, survey_year)
        for metric, value in vals.items():
            if value is not None:
                conn_out.execute(
                    f"UPDATE institution_quant SET {metric}_value=? WHERE unitid=? AND survey_year=?",
                    (value, unitid, survey_year)
                )
        written += 1

    conn_out.commit()
    logger.info(f"  financial: {written} institution-years updated")
    return written


# ---------------------------------------------------------------------------
# Stage 3: Demand metrics
# ---------------------------------------------------------------------------

def build_demand(conn_out: sqlite3.Connection,
                 conn_ipeds: sqlite3.Connection) -> int:
    logger.info("Stage: demand metrics")

    sy_ph = ",".join("?" * len(SURVEY_YEARS))

    # ipeds_ef enrollment
    ef = {}
    for row in conn_ipeds.execute(f"""
        SELECT unitid, survey_year, enrtot, enrgrad, enrugrd
        FROM ipeds_ef WHERE survey_year IN ({sy_ph})
    """, SURVEY_YEARS):
        ef[(row["unitid"], row["survey_year"])] = dict(row)

    # ipeds_adm
    adm = {}
    for row in conn_ipeds.execute(f"""
        SELECT unitid, survey_year, applcn, admssn, enrlt, admit_rate, yield_rate
        FROM ipeds_adm WHERE survey_year IN ({sy_ph})
    """, SURVEY_YEARS):
        adm[(row["unitid"], row["survey_year"])] = dict(row)

    # ipeds_sfa
    sfa = {}
    for row in conn_ipeds.execute(f"""
        SELECT unitid, survey_year, pct_pell
        FROM ipeds_sfa WHERE survey_year IN ({sy_ph})
    """, SURVEY_YEARS):
        sfa[(row["unitid"], row["survey_year"])] = dict(row)

    # All unitids with any data in target years
    all_unitids = set()
    for (uid, sy) in ef.keys():
        if sy in TARGET_YEARS:
            all_unitids.add(uid)

    written = 0
    for uid in all_unitids:
        for sy in TARGET_YEARS:
            ef_now  = ef.get((uid, sy), {})
            adm_now = adm.get((uid, sy), {})
            sfa_now = sfa.get((uid, sy), {})

            enr_now = ef_now.get("enrtot")
            enr_3yr = ef.get((uid, sy - 3), {}).get("enrtot")
            app_now = adm_now.get("applcn")
            app_3yr = adm.get((uid, sy - 3), {}).get("applcn")

            vals = {
                "enrollment_3yr_cagr": cagr(enr_3yr, enr_now, 3),
                "yield_rate":          adm_now.get("yield_rate"),
                "admit_rate":          adm_now.get("admit_rate"),
                "app_3yr_cagr":        cagr(app_3yr, app_now, 3),
                "retention_rate":      None,   # EF Part D not loaded — known gap
                "grad_enrollment_pct": safe_div(ef_now.get("enrgrad"), enr_now),
                "pell_pct":            sfa_now.get("pct_pell"),
            }

            if enr_now is None and all(v is None for v in vals.values()):
                continue

            # Get ein for this unitid
            ein = conn_ipeds.execute(
                "SELECT ein FROM institution_master WHERE unitid=? LIMIT 1", (uid,)
            ).fetchone()
            ein_val = ein["ein"] if ein else None

            ensure_row(conn_out, uid, ein_val, sy)
            for metric, value in vals.items():
                if value is not None:
                    conn_out.execute(
                        f"UPDATE institution_quant SET {metric}_value=? WHERE unitid=? AND survey_year=?",
                        (value, uid, sy)
                    )
            written += 1

    conn_out.commit()
    logger.info(f"  demand: {written} institution-years updated")
    return written


# ---------------------------------------------------------------------------
# Stage 4a: Value metrics (Scorecard)
# ---------------------------------------------------------------------------

def build_value(conn_out: sqlite3.Connection,
                conn_scorecard: sqlite3.Connection,
                conn_ipeds: sqlite3.Connection) -> int:
    logger.info("Stage: value metrics (scorecard)")

    # Scorecard is single-year (data_year=2023); map to survey_year=2022
    SCORECARD_SURVEY_YEAR = 2022
    written = 0

    for row in conn_scorecard.execute("""
        SELECT unitid, avg_net_price_pub, avg_net_price_priv,
               earnings_6yr_median, median_debt, completion_rate_4yr
        FROM scorecard_institution
    """):
        uid = row["unitid"]
        # Pick relevant net price (priv preferred; fallback to pub)
        net_p = row["avg_net_price_priv"] or row["avg_net_price_pub"]
        earn  = row["earnings_6yr_median"]
        debt  = row["median_debt"]
        comp  = row["completion_rate_4yr"]

        e_d_ratio = safe_div(earn, debt)
        np_e_ratio = safe_div(net_p, earn)

        vals = {
            "grad_rate_150":         comp,
            "net_price":             net_p,
            "earnings_to_debt_ratio": e_d_ratio,
            "net_price_to_earnings": np_e_ratio,
        }
        if all(v is None for v in vals.values()):
            continue

        ein = conn_ipeds.execute(
            "SELECT ein FROM institution_master WHERE unitid=? LIMIT 1", (uid,)
        ).fetchone()
        ein_val = ein["ein"] if ein else None

        ensure_row(conn_out, uid, ein_val, SCORECARD_SURVEY_YEAR)
        for metric, value in vals.items():
            if value is not None:
                conn_out.execute(
                    f"UPDATE institution_quant SET {metric}_value=? WHERE unitid=? AND survey_year=?",
                    (value, uid, SCORECARD_SURVEY_YEAR)
                )
        written += 1

    conn_out.commit()
    logger.info(f"  value: {written} institutions updated (survey_year={SCORECARD_SURVEY_YEAR})")
    return written


# ---------------------------------------------------------------------------
# Stage 4b: Athletics metrics (EADA)
# ---------------------------------------------------------------------------

def build_athletics(conn_out: sqlite3.Connection,
                    conn_eada: sqlite3.Connection,
                    conn_ipeds: sqlite3.Connection) -> int:
    logger.info("Stage: athletics metrics (eada)")

    # EADA survey_year = IPEDS survey_year + 1
    eada_years = [sy + 1 for sy in TARGET_YEARS]
    sy_ph = ",".join("?" * len(eada_years))

    # Load EADA instlevel (grand totals)
    eada = {}
    for row in conn_eada.execute(f"""
        SELECT unitid, survey_year,
               grnd_total_revenue, grnd_total_expense, ef_total_count
        FROM eada_instlevel
        WHERE survey_year IN ({sy_ph})
    """, eada_years):
        eada[(int(row["unitid"]), row["survey_year"])] = dict(row)

    # Load 990 total_functional_expenses for private institutions
    # (for athletics_to_expense_pct denominator)
    fy_years = [sy + 1 for sy in TARGET_YEARS]
    fy_ph = ",".join("?" * len(fy_years))
    inst_expenses = {}  # {(unitid, survey_year): total_functional_expenses}

    conn_eada.execute("ATTACH DATABASE ? AS ipeds", (conn_ipeds.execute("PRAGMA database_list").fetchall()[0][2],))

    # Use ipeds_ef enrollment as denominator for athletics_per_student
    ef_enr = {}
    ef_sy_ph = ",".join("?" * len(TARGET_YEARS))
    for row in conn_ipeds.execute(f"""
        SELECT unitid, survey_year, enrtot FROM ipeds_ef WHERE survey_year IN ({ef_sy_ph})
    """, TARGET_YEARS):
        ef_enr[(row["unitid"], row["survey_year"])] = row["enrtot"]

    written = 0
    for (uid, eada_sy), row in eada.items():
        survey_year = eada_sy - 1  # Convert EADA year to IPEDS survey_year
        if survey_year not in TARGET_YEARS:
            continue

        total_rev = row["grnd_total_revenue"]
        total_exp = row["grnd_total_expense"]
        enr = ef_enr.get((uid, survey_year)) or row.get("ef_total_count")

        # athletics_net
        ath_net = None
        if total_rev is not None and total_exp is not None:
            ath_net = total_rev - total_exp

        # athletics_per_student
        ath_per_student = safe_div(total_exp, enr)

        # athletics_to_expense_pct — we'll fill this in via UPDATE using 990 data below
        # For now set what we can
        vals = {
            "athletics_net":        ath_net,
            "athletics_per_student": ath_per_student,
        }

        ein = conn_ipeds.execute(
            "SELECT ein FROM institution_master WHERE unitid=? LIMIT 1", (uid,)
        ).fetchone()
        ein_val = ein["ein"] if ein else None

        ensure_row(conn_out, uid, ein_val, survey_year)
        for metric, value in vals.items():
            if value is not None:
                conn_out.execute(
                    f"UPDATE institution_quant SET {metric}_value=? WHERE unitid=? AND survey_year=?",
                    (value, uid, survey_year)
                )
        written += 1

    conn_out.commit()
    logger.info(f"  athletics: {written} institution-years updated")
    return written


def build_athletics_pct(conn_out: sqlite3.Connection,
                        conn_eada: sqlite3.Connection,
                        conn_990: sqlite3.Connection) -> int:
    """Second pass: compute athletics_to_expense_pct using 990 functional expenses."""
    logger.info("  athletics_to_expense_pct: second pass")

    eada_years = [sy + 1 for sy in TARGET_YEARS]
    sy_ph = ",".join("?" * len(eada_years))
    eada_exp = {}
    for row in conn_eada.execute(f"""
        SELECT unitid, survey_year, grnd_total_expense
        FROM eada_instlevel WHERE survey_year IN ({sy_ph})
    """, eada_years):
        eada_exp[(int(row["unitid"]), row["survey_year"] - 1)] = row["grnd_total_expense"]

    fy_years = [sy + 1 for sy in TARGET_YEARS]
    fy_ph = ",".join("?" * len(fy_years))
    tfe_990 = {}
    for row in conn_990.execute(f"""
        SELECT ff.ein, ff.fiscal_year_end,
               COALESCE(ff.total_functional_expenses, ff.total_expenses) AS tfe
        FROM form990_filings ff
        WHERE ff.fiscal_year_end IN ({fy_ph})
    """, fy_years):
        tfe_990[(row["ein"], row["fiscal_year_end"] - 1)] = row["tfe"]

    updated = 0
    for row in conn_out.execute("""
        SELECT unitid, survey_year, ein
        FROM institution_quant
        WHERE athletics_net_value IS NOT NULL
    """):
        uid, sy, ein = row["unitid"], row["survey_year"], row["ein"]
        eada_e = eada_exp.get((uid, sy))
        tfe = tfe_990.get((ein, sy)) if ein else None
        pct = safe_div(eada_e, tfe)
        if pct is not None:
            conn_out.execute(
                "UPDATE institution_quant SET athletics_to_expense_pct_value=? WHERE unitid=? AND survey_year=?",
                (pct, uid, sy)
            )
            updated += 1

    conn_out.commit()
    logger.info(f"  athletics_to_expense_pct: {updated} rows updated")
    return updated


# ---------------------------------------------------------------------------
# Stage: Peer stats (median + percentile)
# ---------------------------------------------------------------------------

def build_peer_stats(conn_out: sqlite3.Connection,
                     conn_ipeds: sqlite3.Connection) -> None:
    logger.info("Stage: peer stats (median + percentile)")

    # Load carnegie_basic for all unitids
    carnegie = {}
    for row in conn_ipeds.execute("SELECT unitid, carnegie_basic FROM institution_master"):
        carnegie[row["unitid"]] = row["carnegie_basic"]

    # Load all current metric values
    rows = conn_out.execute("SELECT * FROM institution_quant").fetchall()
    col_names = [d[0] for d in conn_out.execute("SELECT * FROM institution_quant LIMIT 0").description]

    # Group by (carnegie_basic, survey_year) → {metric: [values]}
    # Structure: peer_data[carnegie][survey_year][metric] = [val, ...]
    peer_data: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    row_dicts = []
    for row in rows:
        rd = dict(zip(col_names, row))
        row_dicts.append(rd)
        cb = carnegie.get(rd["unitid"])
        if cb is None:
            continue
        sy = rd["survey_year"]
        for m in ALL_METRICS:
            val = rd.get(f"{m}_value")
            if val is not None:
                peer_data[cb][sy][m].append(val)

    total_updated = 0
    for rd in row_dicts:
        uid = rd["unitid"]
        sy  = rd["survey_year"]
        cb  = carnegie.get(uid)
        if cb is None:
            continue

        updates = {}
        peer_group_size = None

        for m in ALL_METRICS:
            peer_vals = peer_data[cb][sy][m]
            n = len(peer_vals)
            val = rd.get(f"{m}_value")

            if n < MIN_PEER_SIZE:
                # Null peer stats for small groups
                continue

            if peer_group_size is None:
                peer_group_size = n  # use first metric's group size as representative

            med = median(peer_vals)
            pct = percentile_rank(val, peer_vals)
            updates[f"{m}_peer_median"] = med
            updates[f"{m}_peer_pct"]    = pct

        if updates:
            if peer_group_size is not None:
                updates["carnegie_peer_group_size"] = peer_group_size
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn_out.execute(
                f"UPDATE institution_quant SET {set_clause} WHERE unitid=? AND survey_year=?",
                list(updates.values()) + [uid, sy]
            )
            total_updated += 1

    conn_out.commit()
    logger.info(f"  peer stats: {total_updated} rows updated")


# ---------------------------------------------------------------------------
# Stage: Trends
# ---------------------------------------------------------------------------

def build_trends(conn_out: sqlite3.Connection) -> None:
    logger.info("Stage: trends (1yr, 3yr, direction)")

    # Load all values into memory: {(unitid, survey_year): {metric: value}}
    all_vals: dict = defaultdict(dict)
    col_names = [d[0] for d in conn_out.execute("SELECT * FROM institution_quant LIMIT 0").description]
    for row in conn_out.execute("SELECT * FROM institution_quant"):
        rd = dict(zip(col_names, row))
        key = (rd["unitid"], rd["survey_year"])
        for m in ALL_METRICS:
            all_vals[key][m] = rd.get(f"{m}_value")

    total_updated = 0
    for (uid, sy), vals in all_vals.items():
        if sy not in TARGET_YEARS:
            continue
        updates = {}
        for m in ALL_METRICS:
            cur = vals.get(m)
            if cur is None:
                continue

            # trend_1yr
            prior_1 = all_vals.get((uid, sy - 1), {}).get(m)
            t1 = safe_div(cur - prior_1, abs(prior_1)) if prior_1 is not None and prior_1 != 0 else None
            if t1 is not None:
                updates[f"{m}_trend_1yr"] = round(t1, 4)
                updates[f"{m}_trend_dir"] = trend_direction(cur, prior_1, METRIC_DIRECTION[m])

            # trend_3yr
            prior_3 = all_vals.get((uid, sy - 3), {}).get(m)
            t3 = safe_div(cur - prior_3, abs(prior_3)) if prior_3 is not None and prior_3 != 0 else None
            if t3 is not None:
                updates[f"{m}_trend_3yr"] = round(t3, 4)
                # trend_dir from 3yr if 1yr not available
                if f"{m}_trend_dir" not in updates:
                    updates[f"{m}_trend_dir"] = trend_direction(cur, prior_3, METRIC_DIRECTION[m])

        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn_out.execute(
                f"UPDATE institution_quant SET {set_clause} WHERE unitid=? AND survey_year=?",
                list(updates.values()) + [uid, sy]
            )
            total_updated += 1

    conn_out.commit()
    logger.info(f"  trends: {total_updated} rows updated")


# ---------------------------------------------------------------------------
# Stage: Data completeness
# ---------------------------------------------------------------------------

def build_completeness(conn_out: sqlite3.Connection) -> None:
    logger.info("Stage: data completeness")
    n_metrics = len(ALL_METRICS)
    conn_out.execute(f"""
        UPDATE institution_quant
        SET data_completeness_pct = ROUND((
            {" + ".join(f"CASE WHEN {m}_value IS NOT NULL THEN 1 ELSE 0 END" for m in ALL_METRICS)}
        ) * 100.0 / {n_metrics}, 1)
    """)
    conn_out.commit()
    logger.info("  completeness: done")


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------

VALIDATION_UNITIDS = {
    164580: "Babson",
    164739: "Bentley",
    164924: "BC",
    166027: "Harvard",
    166683: "MIT",
}


def validation_report(conn_out: sqlite3.Connection, survey_year: int = 2022) -> None:
    print(f"\n=== VALIDATION — {survey_year} ===")
    print(f"{'Institution':<10} {'Comp%':>6} {'OpMgn':>7} {'D/A':>6} {'EndoRun':>8} {'TuitDep':>8} {'EnrCAGR':>8} {'Yield':>7} {'PgrSvc':>7}")
    print("-" * 80)
    for uid, name in VALIDATION_UNITIDS.items():
        row = conn_out.execute("""
            SELECT data_completeness_pct,
                   operating_margin_value, debt_to_assets_value,
                   endowment_runway_value, tuition_dependency_value,
                   enrollment_3yr_cagr_value, yield_rate_value,
                   program_services_pct_value
            FROM institution_quant WHERE unitid=? AND survey_year=?
        """, (uid, survey_year)).fetchone()
        if row:
            def fmt(v, pct=False):
                if v is None: return "NULL"
                return f"{v*100:.1f}%" if pct else f"{v:.3f}"
            print(f"{name:<10} {fmt(row[0])+'%':>6} {fmt(row[1],True):>7} {fmt(row[2],True):>6} "
                  f"{f'{row[3]:.2f}' if row[3] else 'NULL':>8} {fmt(row[4],True):>8} "
                  f"{fmt(row[5],True):>8} {fmt(row[6],True):>7} {fmt(row[7],True):>7}")
        else:
            print(f"{name:<10} {'NO ROW':>6}")

    # Row counts
    r = conn_out.execute("""
        SELECT survey_year, COUNT(*) as rows,
               SUM(CASE WHEN operating_margin_value IS NOT NULL THEN 1 ELSE 0 END) as fin_coverage,
               SUM(CASE WHEN enrollment_3yr_cagr_value IS NOT NULL THEN 1 ELSE 0 END) as enr_coverage,
               SUM(CASE WHEN net_price_value IS NOT NULL THEN 1 ELSE 0 END) as sc_coverage,
               SUM(CASE WHEN athletics_net_value IS NOT NULL THEN 1 ELSE 0 END) as ath_coverage,
               ROUND(AVG(data_completeness_pct),1) as avg_completeness
        FROM institution_quant
        WHERE survey_year IN (2019,2020,2021,2022)
        GROUP BY survey_year ORDER BY survey_year
    """).fetchall()
    print(f"\n{'Year':>6} {'Rows':>7} {'Fin':>6} {'Enr':>6} {'SC':>6} {'Ath':>6} {'AvgComp%':>9}")
    print("-" * 55)
    for row in r:
        print(f"{row[0]:>6} {row[1]:>7} {row[2]:>6} {row[3]:>6} {row[4]:>6} {row[5]:>6} {str(row[6] or '-'):>9}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(db_990: str, ipeds: str, eada: str, scorecard: str,
        out: str, stages: list[str]) -> None:

    conn_out  = init_db(out)
    conn_990  = sqlite3.connect(db_990);  conn_990.row_factory  = sqlite3.Row
    conn_ipeds= sqlite3.connect(ipeds);   conn_ipeds.row_factory= sqlite3.Row
    conn_eada = sqlite3.connect(eada);    conn_eada.row_factory = sqlite3.Row
    conn_sc   = sqlite3.connect(scorecard); conn_sc.row_factory = sqlite3.Row

    run_all = "all" in stages

    if run_all or "financial" in stages:
        build_financial(conn_out, conn_990, conn_ipeds)
        if not (run_all or len(stages) > 1):
            validation_report(conn_out)

    if run_all or "demand" in stages:
        build_demand(conn_out, conn_ipeds)
        if not (run_all or len(stages) > 1):
            validation_report(conn_out)

    if run_all or "value" in stages:
        build_value(conn_out, conn_sc, conn_ipeds)
        build_athletics(conn_out, conn_eada, conn_ipeds)
        build_athletics_pct(conn_out, conn_eada, conn_990)
        if not (run_all or len(stages) > 1):
            validation_report(conn_out)

    if run_all or "peers" in stages:
        build_peer_stats(conn_out, conn_ipeds)

    if run_all or "trends" in stages:
        build_trends(conn_out)

    if run_all or "completeness" in stages:
        build_completeness(conn_out)

    validation_report(conn_out)

    total = conn_out.execute("SELECT COUNT(*) FROM institution_quant").fetchone()[0]
    target = conn_out.execute(
        "SELECT COUNT(*) FROM institution_quant WHERE survey_year IN (2019,2020,2021,2022)"
    ).fetchone()[0]
    logger.info(f"Done — {total:,} total rows, {target:,} in target years 2019-2022")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Build institution_quant")
    parser.add_argument("--db990",     required=True)
    parser.add_argument("--ipeds",     required=True)
    parser.add_argument("--eada",      required=True)
    parser.add_argument("--scorecard", required=True)
    parser.add_argument("--out",       required=True)
    parser.add_argument("--stage",     nargs="+",
                        default=["all"],
                        choices=["all","financial","demand","value","peers","trends","completeness"])
    args = parser.parse_args()
    run(args.db990, args.ipeds, args.eada, args.scorecard, args.out, args.stage)


if __name__ == "__main__":
    main()
