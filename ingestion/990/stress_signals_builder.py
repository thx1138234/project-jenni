#!/usr/bin/env python3
"""
ingestion/990/stress_signals_builder.py
----------------------------------------
Build the financial_stress_signals table from form990_filings (FY2020-2022),
form990_schedule_d, and form990_part_ix.

Three fixes vs. single-year FY2022 query:
  Fix 1 — EIN-level dedup: one row per EIN (institution system), not per UNITID (campus).
           Multi-campus systems (DeVry, Altierus, Strayer…) are collapsed to the
           canonical EIN with MIN(unitid) as the representative UNITID.
  Fix 2 — Cash signal endowment suppression: sig_low_cash requires
           endowment_runway IS NULL OR endowment_runway < 1.0 to avoid flagging
           wealthy institutions that manage cash efficiently via endowment draws.
  Fix 3 — 3-year trending: signals evaluated for FY2020, FY2021, FY2022 independently.
           confirmed = fires in all available years (requires >=2 yrs of data).
           emerging  = fires in 2 of 3 years (only when 3 years available).
           single    = fires in exactly 1 year (potential COVID distortion).

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


# ---------------------------------------------------------------------------
# Signal computation — one year of data → 8 binary flags
# ---------------------------------------------------------------------------

def compute_signals(ff: dict, sd: dict | None, px: dict | None) -> dict:
    """
    Given one year's filing data, return dict of 8 binary signal values (0 or 1).
    Returns None if the filing row is absent (not just missing supplemental data).
    """
    def safe_div(num, den):
        if num is None or den is None or den == 0:
            return None
        return num / den

    surplus     = ff.get("reconciliation_surplus")
    net_eoy     = ff.get("net_assets_eoy")
    net_boy     = ff.get("net_assets_boy")
    liab_eoy    = ff.get("total_liabilities_eoy")
    assets_eoy  = ff.get("total_assets_eoy")
    cash        = ff.get("cash_and_equivalents")
    expenses    = ff.get("total_expenses")

    # Endowment fields (from schedule_d, may be None)
    end_runway   = sd.get("endowment_runway")   if sd else None
    end_eoy      = sd.get("endowment_eoy")      if sd else None
    stress_end   = sd.get("stress_endowment")   if sd else None

    # Functional expense pct (from part_ix, may be None)
    prog_pct     = px.get("prog_services_pct")  if px else None

    # --- Signal 1: Operating deficit ---
    sig_deficit = 1 if (surplus is not None and surplus < 0) else 0

    # --- Signal 2: Negative net assets ---
    sig_neg_assets = 1 if (net_eoy is not None and net_eoy < 0) else 0

    # --- Signal 3: Net asset decline > 10% ---
    na_chg = safe_div(
        (net_eoy - net_boy) if net_eoy is not None and net_boy is not None else None,
        abs(net_boy) if net_boy else None
    )
    sig_asset_decline = 1 if (na_chg is not None and na_chg < -0.10) else 0

    # --- Signal 4: High debt (liabilities > 50% of assets) ---
    debt_ratio = safe_div(liab_eoy, assets_eoy)
    sig_high_debt = 1 if (debt_ratio is not None and debt_ratio > 0.50) else 0

    # --- Signal 5: Low cash — with endowment suppression (Fix 2) ---
    cash_months = safe_div(cash, expenses / 12.0 if expenses else None)
    endowment_suppressed = (end_runway is not None and end_runway >= 1.0)
    if cash_months is not None and cash_months < 3.0 and not endowment_suppressed:
        sig_low_cash = 1
    else:
        sig_low_cash = 0

    # --- Signal 6: Endowment spending stress (> 7% rate, stress_endowment = 1) ---
    sig_end_stress = 1 if stress_end == 1 else 0

    # --- Signal 7: Low endowment runway (< 0.5 years, only when endowment present) ---
    sig_low_runway = 1 if (
        end_eoy is not None and end_runway is not None and end_runway < 0.5
    ) else 0

    # --- Signal 8: Low program services allocation (< 65%) ---
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
# Trend analysis — across up to 3 years of signal vectors
# ---------------------------------------------------------------------------

SIGNALS = ["deficit", "neg_assets", "asset_decline", "high_debt",
           "low_cash", "end_stress", "low_runway", "low_prog"]


def compute_trends(year_signals: dict[int, dict], years_available: int) -> dict:
    """
    year_signals: {2020: {sig: 0/1, ...}, 2021: {...}, 2022: {...}}
    Returns trend counts and composite score.
    """
    yrs = sorted(year_signals.keys())

    # Per-signal: count years fired
    sig_yrs = {}
    for sig in SIGNALS:
        sig_yrs[sig] = sum(year_signals[y][sig] for y in yrs)

    confirmed = 0
    emerging  = 0
    single    = 0

    for sig in SIGNALS:
        fired = sig_yrs[sig]
        if years_available >= 3:
            if fired == 3:
                confirmed += 1
            elif fired == 2:
                emerging += 1
            elif fired == 1:
                single += 1
        elif years_available == 2:
            if fired == 2:
                confirmed += 1
            elif fired == 1:
                # Only 2 years available: single-year firing is "single"
                single += 1
        else:  # years_available == 1
            if fired == 1:
                single += 1

    composite = round(confirmed * 1.0 + emerging * 0.5 + single * 0.25, 4)

    return {
        "sig_yrs":              sig_yrs,
        "confirmed_signal_count": confirmed,
        "emerging_signal_count":  emerging,
        "single_year_count":      single,
        "composite_stress_score": composite,
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO financial_stress_signals (
    ein, unitid, institution_name, state_abbr, hbcu, jesuit_institution, carnegie_basic,
    signal_year_range, years_available,
    sig_deficit_yrs, sig_neg_assets_yrs, sig_asset_decline_yrs, sig_high_debt_yrs,
    sig_low_cash_yrs, sig_end_stress_yrs, sig_low_runway_yrs, sig_low_prog_yrs,
    confirmed_signal_count, emerging_signal_count, single_year_count,
    composite_stress_score, data_completeness_pct
) VALUES (
    :ein, :unitid, :institution_name, :state_abbr, :hbcu, :jesuit_institution, :carnegie_basic,
    :signal_year_range, :years_available,
    :sig_deficit_yrs, :sig_neg_assets_yrs, :sig_asset_decline_yrs, :sig_high_debt_yrs,
    :sig_low_cash_yrs, :sig_end_stress_yrs, :sig_low_runway_yrs, :sig_low_prog_yrs,
    :confirmed_signal_count, :emerging_signal_count, :single_year_count,
    :composite_stress_score, :data_completeness_pct
)
ON CONFLICT(ein) DO UPDATE SET
    unitid                  = excluded.unitid,
    institution_name        = excluded.institution_name,
    state_abbr              = excluded.state_abbr,
    hbcu                    = excluded.hbcu,
    jesuit_institution      = excluded.jesuit_institution,
    carnegie_basic          = excluded.carnegie_basic,
    signal_year_range       = excluded.signal_year_range,
    years_available         = excluded.years_available,
    sig_deficit_yrs         = excluded.sig_deficit_yrs,
    sig_neg_assets_yrs      = excluded.sig_neg_assets_yrs,
    sig_asset_decline_yrs   = excluded.sig_asset_decline_yrs,
    sig_high_debt_yrs       = excluded.sig_high_debt_yrs,
    sig_low_cash_yrs        = excluded.sig_low_cash_yrs,
    sig_end_stress_yrs      = excluded.sig_end_stress_yrs,
    sig_low_runway_yrs      = excluded.sig_low_runway_yrs,
    sig_low_prog_yrs        = excluded.sig_low_prog_yrs,
    confirmed_signal_count  = excluded.confirmed_signal_count,
    emerging_signal_count   = excluded.emerging_signal_count,
    single_year_count       = excluded.single_year_count,
    composite_stress_score  = excluded.composite_stress_score,
    data_completeness_pct   = excluded.data_completeness_pct,
    loaded_at               = datetime('now')
"""


def run(db_path: str, ipeds_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ? AS ipeds", (ipeds_path,))

    # Init schema
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()

    # Canonical institution per EIN (Fix 1: MIN unitid per EIN, exclude EIN=-1 sentinel)
    canon = {}
    for row in conn.execute("""
        SELECT im.ein,
               MIN(im.unitid)         AS unitid,
               MIN(im.institution_name) AS institution_name,
               MIN(im.state_abbr)     AS state_abbr,
               MIN(im.hbcu)           AS hbcu,
               MIN(im.jesuit_institution) AS jesuit_institution,
               MIN(im.carnegie_basic) AS carnegie_basic
        FROM ipeds.institution_master im
        WHERE im.ein IS NOT NULL AND im.ein != '' AND im.ein != '-1'
        GROUP BY im.ein
    """):
        canon[row["ein"]] = dict(row)

    # For institution_name etc, we want the row for MIN(unitid), not MIN of names
    # Re-query to get actual values for the canonical unitid
    for row in conn.execute("""
        SELECT im.*
        FROM ipeds.institution_master im
        WHERE im.ein IS NOT NULL AND im.ein != '' AND im.ein != '-1'
          AND im.unitid = (
              SELECT MIN(unitid) FROM ipeds.institution_master im2
              WHERE im2.ein = im.ein
          )
    """):
        ein = row["ein"]
        if ein in canon:
            canon[ein].update({
                "unitid":           row["unitid"],
                "institution_name": row["institution_name"],
                "state_abbr":       row["state_abbr"],
                "hbcu":             row["hbcu"],
                "jesuit_institution": row["jesuit_institution"],
                "carnegie_basic":   row["carnegie_basic"],
            })

    # Load all filings FY2020-2022, keyed by (ein, fiscal_year_end)
    filings = {}
    for row in conn.execute("""
        SELECT * FROM form990_filings
        WHERE fiscal_year_end IN (2020, 2021, 2022)
    """):
        key = (row["ein"], row["fiscal_year_end"])
        # If duplicate filings for same EIN+year, keep latest loaded (last wins)
        filings[key] = dict(row)

    # Load schedule_d supplemental data
    sched_d = {}
    for row in conn.execute("""
        SELECT ein, fiscal_year_end, endowment_eoy, endowment_runway,
               endowment_spending_rate, stress_endowment
        FROM form990_schedule_d
        WHERE fiscal_year_end IN (2020, 2021, 2022)
    """):
        sched_d[(row["ein"], row["fiscal_year_end"])] = dict(row)

    # Load part_ix supplemental data
    part_ix = {}
    for row in conn.execute("""
        SELECT ein, fiscal_year_end, prog_services_pct, overhead_ratio
        FROM form990_part_ix
        WHERE fiscal_year_end IN (2020, 2021, 2022)
    """):
        part_ix[(row["ein"], row["fiscal_year_end"])] = dict(row)

    # Collect all EINs that appear in the filing window
    all_eins = {ein for (ein, _) in filings.keys()}

    written = 0
    skipped_no_canon = 0

    for ein in sorted(all_eins):
        # Gather available years for this EIN
        year_signals = {}
        years_present = []

        for yr in SIGNAL_YEARS:
            key = (ein, yr)
            if key not in filings:
                continue
            ff = filings[key]
            sd = sched_d.get(key)
            px = part_ix.get(key)
            sigs = compute_signals(ff, sd, px)
            year_signals[yr] = sigs
            years_present.append(yr)

        if not years_present:
            continue

        years_available = len(years_present)
        year_range = f"{min(years_present)}-{max(years_present)}"

        trends = compute_trends(year_signals, years_available)
        sig_yrs = trends["sig_yrs"]

        # Institution identity — use canon if available, else use org_name from filing
        inst = canon.get(ein)
        if inst is None:
            # EIN not in institution_master (e.g., non-IPEDS filer)
            # Use most recent filing's org_name as fallback
            latest = max(years_present)
            ff = filings[(ein, latest)]
            inst = {
                "unitid":           None,
                "institution_name": ff.get("org_name"),
                "state_abbr":       None,
                "hbcu":             None,
                "jesuit_institution": None,
                "carnegie_basic":   None,
            }

        conn.execute(UPSERT_SQL, {
            "ein":                   ein,
            "unitid":                inst["unitid"],
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
            "confirmed_signal_count":  trends["confirmed_signal_count"],
            "emerging_signal_count":   trends["emerging_signal_count"],
            "single_year_count":       trends["single_year_count"],
            "composite_stress_score":  trends["composite_stress_score"],
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
    parser = argparse.ArgumentParser(description="Build financial_stress_signals table")
    parser.add_argument("--db",    required=True, help="Path to 990_data.db")
    parser.add_argument("--ipeds", required=True, help="Path to ipeds_data.db")
    args = parser.parse_args()
    run(args.db, args.ipeds)


if __name__ == "__main__":
    main()
