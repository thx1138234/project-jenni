#!/usr/bin/env python3
"""
ingestion/990/stress_signals_builder.py
----------------------------------------
Build the financial_stress_signals table from form990_filings (FY2020-2022),
form990_schedule_d, form990_part_ix, and ipeds_ef enrollment data.

Three production fixes vs. single-year FY2022 query:
  Fix 1 — EIN-level dedup: one row per EIN (institution system), not per UNITID (campus).
           Multi-campus systems (DeVry, Altierus, Strayer…) collapsed to MIN(unitid).
  Fix 2 — Cash signal endowment suppression: sig_low_cash requires
           endowment_runway IS NULL OR endowment_runway < 1.0 to avoid flagging
           wealthy institutions that manage cash efficiently via endowment draws.
  Fix 3 — 3-year trending: signals evaluated for FY2020, FY2021, FY2022 independently.
           confirmed = fires in all available years (requires >=2 yrs of data).
           emerging  = fires in 2 of 3 years (only when 3 years available).
           single    = fires in exactly 1 year (potential COVID distortion).

Ninth signal — enrollment decline (cross-validated with IPEDS):
  sig_enrollment_decline      : enrtot declined each consecutive year (2021<2020 AND 2022<2021)
  sig_enrollment_severe       : total 3yr decline exceeds 10%
  sig_enrollment_accelerating : rate of decline accelerated from interval 1 to interval 2
  enr_financial_combined      : sig_enrollment_decline=1 AND financial_stress_score >= 2.0
                                 (strongest signal in database — enrollment + financial co-occurrence)

Scoring:
  financial_stress_score  = confirmed*1.0 + emerging*0.5 + single*0.25
  enr_score_contribution  = decline*0.5 + severe*1.0 + accelerating*0.5; max 2.0
  composite_stress_score  = financial_stress_score + enr_score_contribution

Usage:
    .venv/bin/python3 ingestion/990/stress_signals_builder.py \\
        --db data/databases/990_data.db \\
        --ipeds data/databases/ipeds_data.db
"""

import argparse
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "financial_stress_signals_schema.sql"
SIGNAL_YEARS = (2020, 2021, 2022)
ENR_YEARS    = (2020, 2021, 2022)


# ---------------------------------------------------------------------------
# Financial signal computation — one year of 990 data → 8 binary flags
# ---------------------------------------------------------------------------

def compute_financial_signals(ff: dict, sd: dict | None, px: dict | None) -> dict:
    def safe_div(num, den):
        if num is None or den is None or den == 0:
            return None
        return num / den

    surplus    = ff.get("reconciliation_surplus")
    net_eoy    = ff.get("net_assets_eoy")
    net_boy    = ff.get("net_assets_boy")
    liab_eoy   = ff.get("total_liabilities_eoy")
    assets_eoy = ff.get("total_assets_eoy")
    cash       = ff.get("cash_and_equivalents")
    expenses   = ff.get("total_expenses")

    end_runway = sd.get("endowment_runway") if sd else None
    end_eoy    = sd.get("endowment_eoy")    if sd else None
    stress_end = sd.get("stress_endowment") if sd else None
    prog_pct   = px.get("prog_services_pct") if px else None

    # Signal 1: Operating deficit
    sig_deficit = 1 if (surplus is not None and surplus < 0) else 0

    # Signal 2: Negative net assets
    sig_neg_assets = 1 if (net_eoy is not None and net_eoy < 0) else 0

    # Signal 3: Net asset decline > 10% YoY
    na_chg = safe_div(
        (net_eoy - net_boy) if net_eoy is not None and net_boy is not None else None,
        abs(net_boy) if net_boy else None,
    )
    sig_asset_decline = 1 if (na_chg is not None and na_chg < -0.10) else 0

    # Signal 4: High debt (liabilities > 50% of assets)
    debt_ratio = safe_div(liab_eoy, assets_eoy)
    sig_high_debt = 1 if (debt_ratio is not None and debt_ratio > 0.50) else 0

    # Signal 5: Low cash — with endowment suppression (Fix 2)
    cash_months = safe_div(cash, expenses / 12.0 if expenses else None)
    endowment_suppressed = (end_runway is not None and end_runway >= 1.0)
    sig_low_cash = (
        1 if (cash_months is not None and cash_months < 3.0 and not endowment_suppressed) else 0
    )

    # Signal 6: Endowment spending stress (> 7%)
    sig_end_stress = 1 if stress_end == 1 else 0

    # Signal 7: Low endowment runway (< 0.5yr, only when endowment present)
    sig_low_runway = 1 if (
        end_eoy is not None and end_runway is not None and end_runway < 0.5
    ) else 0

    # Signal 8: Low program services allocation (< 65%)
    sig_low_prog = 1 if (prog_pct is not None and prog_pct < 0.65) else 0

    return {
        "deficit":       sig_deficit,
        "neg_assets":    sig_neg_assets,
        "asset_decline": sig_asset_decline,
        "high_debt":     sig_high_debt,
        "low_cash":      sig_low_cash,
        "end_stress":    sig_end_stress,
        "low_runway":    sig_low_runway,
        "low_prog":      sig_low_prog,
    }


# ---------------------------------------------------------------------------
# Financial trend analysis — across up to 3 years of signal vectors
# ---------------------------------------------------------------------------

FIN_SIGNALS = ["deficit", "neg_assets", "asset_decline", "high_debt",
               "low_cash", "end_stress", "low_runway", "low_prog"]


def compute_financial_trends(year_signals: dict, years_available: int) -> dict:
    yrs = sorted(year_signals.keys())

    sig_yrs = {sig: sum(year_signals[y][sig] for y in yrs) for sig in FIN_SIGNALS}

    confirmed = emerging = single = 0
    for sig in FIN_SIGNALS:
        fired = sig_yrs[sig]
        if years_available >= 3:
            if fired == 3:   confirmed += 1
            elif fired == 2: emerging  += 1
            elif fired == 1: single    += 1
        elif years_available == 2:
            if fired == 2:   confirmed += 1
            elif fired == 1: single    += 1
        else:
            if fired == 1:   single    += 1

    score = round(confirmed * 1.0 + emerging * 0.5 + single * 0.25, 4)

    return {
        "sig_yrs":               sig_yrs,
        "confirmed_signal_count": confirmed,
        "emerging_signal_count":  emerging,
        "single_year_count":      single,
        "financial_stress_score": score,
    }


# ---------------------------------------------------------------------------
# Enrollment signal computation — from ipeds_ef for survey_years 2020-2022
# ---------------------------------------------------------------------------

def compute_enrollment_signals(enr: dict) -> dict:
    """
    enr: {2020: int|None, 2021: int|None, 2022: int|None}
    Returns dict of enrollment signals and score contribution.
    All signals are None (not 0) when data is insufficient.
    """
    e20 = enr.get(2020)
    e21 = enr.get(2021)
    e22 = enr.get(2022)

    years_available = sum(1 for v in [e20, e21, e22] if v is not None)

    # enr_trend_3yr: requires both endpoints
    enr_trend_3yr = None
    if e20 is not None and e20 > 0 and e22 is not None:
        enr_trend_3yr = round((e22 - e20) / e20, 4)

    # sig_enrollment_decline: requires all 3 years
    sig_decline = None
    if e20 is not None and e21 is not None and e22 is not None:
        sig_decline = 1 if (e21 < e20 and e22 < e21) else 0

    # sig_enrollment_severe: requires both endpoints
    sig_severe = None
    if enr_trend_3yr is not None:
        sig_severe = 1 if enr_trend_3yr < -0.10 else 0

    # sig_enrollment_accelerating: requires all 3 years
    sig_accel = None
    if e20 is not None and e20 > 0 and e21 is not None and e21 > 0 and e22 is not None:
        interval1 = (e21 - e20) / e20   # pct change period 1
        interval2 = (e22 - e21) / e21   # pct change period 2
        # Accelerating decline = interval2 is more negative than interval1
        sig_accel = 1 if (interval2 < interval1 and interval2 < 0) else 0

    # Score contribution — NULL if all signals are NULL
    if sig_decline is None and sig_severe is None and sig_accel is None:
        enr_score = None
    else:
        enr_score = 0.0
        if sig_decline == 1: enr_score += 0.5
        if sig_severe  == 1: enr_score += 1.0
        if sig_accel   == 1: enr_score += 0.5
        enr_score = round(min(enr_score, 2.0), 4)

    return {
        "enr_2020":                  e20,
        "enr_2021":                  e21,
        "enr_2022":                  e22,
        "enr_trend_3yr":             enr_trend_3yr,
        "enr_years_available":       years_available,
        "sig_enrollment_decline":    sig_decline,
        "sig_enrollment_severe":     sig_severe,
        "sig_enrollment_accelerating": sig_accel,
        "enr_score_contribution":    enr_score,
    }


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO financial_stress_signals (
    ein, unitid, institution_name, state_abbr, hbcu, jesuit_institution, carnegie_basic,
    signal_year_range, years_available,
    sig_deficit_yrs, sig_neg_assets_yrs, sig_asset_decline_yrs, sig_high_debt_yrs,
    sig_low_cash_yrs, sig_end_stress_yrs, sig_low_runway_yrs, sig_low_prog_yrs,
    confirmed_signal_count, emerging_signal_count, single_year_count,
    financial_stress_score,
    enr_2020, enr_2021, enr_2022, enr_trend_3yr, enr_years_available,
    sig_enrollment_decline, sig_enrollment_severe, sig_enrollment_accelerating,
    enr_score_contribution,
    composite_stress_score,
    enr_financial_combined,
    data_completeness_pct
    -- narrative_flag intentionally omitted: populated post-build via UPDATE statements.
    -- The builder always leaves narrative_flag as NULL; narratives are editorial and
    -- must survive rebuilds. After running the builder, re-apply the narrative UPDATE
    -- script to restore them.
) VALUES (
    :ein, :unitid, :institution_name, :state_abbr, :hbcu, :jesuit_institution, :carnegie_basic,
    :signal_year_range, :years_available,
    :sig_deficit_yrs, :sig_neg_assets_yrs, :sig_asset_decline_yrs, :sig_high_debt_yrs,
    :sig_low_cash_yrs, :sig_end_stress_yrs, :sig_low_runway_yrs, :sig_low_prog_yrs,
    :confirmed_signal_count, :emerging_signal_count, :single_year_count,
    :financial_stress_score,
    :enr_2020, :enr_2021, :enr_2022, :enr_trend_3yr, :enr_years_available,
    :sig_enrollment_decline, :sig_enrollment_severe, :sig_enrollment_accelerating,
    :enr_score_contribution,
    :composite_stress_score,
    :enr_financial_combined,
    :data_completeness_pct
)
ON CONFLICT(ein) DO UPDATE SET
    unitid                      = excluded.unitid,
    institution_name            = excluded.institution_name,
    state_abbr                  = excluded.state_abbr,
    hbcu                        = excluded.hbcu,
    jesuit_institution          = excluded.jesuit_institution,
    carnegie_basic              = excluded.carnegie_basic,
    signal_year_range           = excluded.signal_year_range,
    years_available             = excluded.years_available,
    sig_deficit_yrs             = excluded.sig_deficit_yrs,
    sig_neg_assets_yrs          = excluded.sig_neg_assets_yrs,
    sig_asset_decline_yrs       = excluded.sig_asset_decline_yrs,
    sig_high_debt_yrs           = excluded.sig_high_debt_yrs,
    sig_low_cash_yrs            = excluded.sig_low_cash_yrs,
    sig_end_stress_yrs          = excluded.sig_end_stress_yrs,
    sig_low_runway_yrs          = excluded.sig_low_runway_yrs,
    sig_low_prog_yrs            = excluded.sig_low_prog_yrs,
    confirmed_signal_count      = excluded.confirmed_signal_count,
    emerging_signal_count       = excluded.emerging_signal_count,
    single_year_count           = excluded.single_year_count,
    financial_stress_score      = excluded.financial_stress_score,
    enr_2020                    = excluded.enr_2020,
    enr_2021                    = excluded.enr_2021,
    enr_2022                    = excluded.enr_2022,
    enr_trend_3yr               = excluded.enr_trend_3yr,
    enr_years_available         = excluded.enr_years_available,
    sig_enrollment_decline      = excluded.sig_enrollment_decline,
    sig_enrollment_severe       = excluded.sig_enrollment_severe,
    sig_enrollment_accelerating = excluded.sig_enrollment_accelerating,
    enr_score_contribution      = excluded.enr_score_contribution,
    composite_stress_score      = excluded.composite_stress_score,
    enr_financial_combined      = excluded.enr_financial_combined,
    data_completeness_pct       = excluded.data_completeness_pct,
    loaded_at                   = datetime('now')
"""


def run(db_path: str, ipeds_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ? AS ipeds", (ipeds_path,))

    # Full rebuild — drop and recreate (derived table, source data preserved)
    conn.execute("DROP TABLE IF EXISTS financial_stress_signals")
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()

    # --- Canonical institution per EIN (Fix 1) ---
    canon = {}
    for row in conn.execute("""
        SELECT im.ein, im.unitid, im.institution_name, im.state_abbr,
               im.hbcu, im.jesuit_institution, im.carnegie_basic
        FROM ipeds.institution_master im
        WHERE im.ein IS NOT NULL AND im.ein != '' AND im.ein != '-1'
          AND im.unitid = (
              SELECT MIN(unitid) FROM ipeds.institution_master im2
              WHERE im2.ein = im.ein
          )
    """):
        canon[row["ein"]] = dict(row)

    # --- Load 990 filings FY2020-2022 ---
    filings = {}
    for row in conn.execute("""
        SELECT * FROM form990_filings WHERE fiscal_year_end IN (2020, 2021, 2022)
    """):
        filings[(row["ein"], row["fiscal_year_end"])] = dict(row)

    # --- Load supplemental data ---
    sched_d = {}
    for row in conn.execute("""
        SELECT ein, fiscal_year_end, endowment_eoy, endowment_runway,
               endowment_spending_rate, stress_endowment
        FROM form990_schedule_d WHERE fiscal_year_end IN (2020, 2021, 2022)
    """):
        sched_d[(row["ein"], row["fiscal_year_end"])] = dict(row)

    part_ix = {}
    for row in conn.execute("""
        SELECT ein, fiscal_year_end, prog_services_pct
        FROM form990_part_ix WHERE fiscal_year_end IN (2020, 2021, 2022)
    """):
        part_ix[(row["ein"], row["fiscal_year_end"])] = dict(row)

    # --- Load enrollment data: {unitid: {year: enrtot}} ---
    enr_by_unitid: dict[int, dict[int, int | None]] = {}
    for row in conn.execute("""
        SELECT unitid, survey_year, enrtot
        FROM ipeds.ipeds_ef
        WHERE survey_year IN (2020, 2021, 2022) AND enrtot IS NOT NULL
    """):
        uid = row["unitid"]
        if uid not in enr_by_unitid:
            enr_by_unitid[uid] = {}
        enr_by_unitid[uid][row["survey_year"]] = row["enrtot"]

    # --- Process each EIN ---
    all_eins = {ein for (ein, _) in filings.keys()}
    written = 0

    for ein in sorted(all_eins):
        year_signals = {}
        years_present = []

        for yr in SIGNAL_YEARS:
            key = (ein, yr)
            if key not in filings:
                continue
            ff = filings[key]
            sd = sched_d.get(key)
            px = part_ix.get(key)
            year_signals[yr] = compute_financial_signals(ff, sd, px)
            years_present.append(yr)

        if not years_present:
            continue

        years_available = len(years_present)
        year_range = f"{min(years_present)}-{max(years_present)}"

        fin = compute_financial_trends(year_signals, years_available)
        sig_yrs = fin["sig_yrs"]
        financial_score = fin["financial_stress_score"]

        # --- Institution identity ---
        inst = canon.get(ein)
        if inst is None:
            latest = max(years_present)
            ff = filings[(ein, latest)]
            inst = {
                "unitid":            None,
                "institution_name":  ff.get("org_name"),
                "state_abbr":        None,
                "hbcu":              None,
                "jesuit_institution": None,
                "carnegie_basic":    None,
            }

        # --- Enrollment signals (requires unitid) ---
        unitid = inst["unitid"]
        if unitid is not None and unitid in enr_by_unitid:
            enr_data = enr_by_unitid[unitid]
        else:
            enr_data = {}

        enr = compute_enrollment_signals(enr_data)

        # --- Cross-validation flag ---
        enr_financial_combined = (
            1 if (enr["sig_enrollment_decline"] == 1 and financial_score >= 2.0) else 0
        )

        # --- Full composite score ---
        enr_contrib = enr["enr_score_contribution"]
        composite = round(financial_score + (enr_contrib or 0.0), 4)

        conn.execute(UPSERT_SQL, {
            "ein":                   ein,
            "unitid":                unitid,
            "institution_name":      inst["institution_name"],
            "state_abbr":            inst["state_abbr"],
            "hbcu":                  inst["hbcu"],
            "jesuit_institution":    inst["jesuit_institution"],
            "carnegie_basic":        inst["carnegie_basic"],
            "signal_year_range":     year_range,
            "years_available":       years_available,
            "sig_deficit_yrs":       sig_yrs["deficit"],
            "sig_neg_assets_yrs":    sig_yrs["neg_assets"],
            "sig_asset_decline_yrs": sig_yrs["asset_decline"],
            "sig_high_debt_yrs":     sig_yrs["high_debt"],
            "sig_low_cash_yrs":      sig_yrs["low_cash"],
            "sig_end_stress_yrs":    sig_yrs["end_stress"],
            "sig_low_runway_yrs":    sig_yrs["low_runway"],
            "sig_low_prog_yrs":      sig_yrs["low_prog"],
            "confirmed_signal_count":  fin["confirmed_signal_count"],
            "emerging_signal_count":   fin["emerging_signal_count"],
            "single_year_count":       fin["single_year_count"],
            "financial_stress_score":  financial_score,
            **{k: enr[k] for k in [
                "enr_2020", "enr_2021", "enr_2022", "enr_trend_3yr", "enr_years_available",
                "sig_enrollment_decline", "sig_enrollment_severe", "sig_enrollment_accelerating",
                "enr_score_contribution",
            ]},
            "composite_stress_score":  composite,
            "enr_financial_combined":  enr_financial_combined,
            "data_completeness_pct":   round(years_available / 3 * 100, 1),
        })
        written += 1

    conn.commit()
    conn.close()
    logger.info(f"Done — {written:,} institutions written to financial_stress_signals")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Build financial_stress_signals table (financial + enrollment signals)"
    )
    parser.add_argument("--db",    required=True, help="Path to 990_data.db")
    parser.add_argument("--ipeds", required=True, help="Path to ipeds_data.db")
    args = parser.parse_args()
    run(args.db, args.ipeds)


if __name__ == "__main__":
    main()
