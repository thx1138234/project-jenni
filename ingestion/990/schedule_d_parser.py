#!/usr/bin/env python3
"""
ingestion/990/schedule_d_parser.py
------------------------------------
Parse IRS Form 990 Schedule D Part V (Endowment Funds) into form990_schedule_d.
Source: TEOS/IRSx XML only.

Only the current-year endowment group (CYEndwmtFundGrp) is extracted per filing.
Prior-year groups (CYMinus1Yr–CYMinus4Yr) are redundant with adjacent filings.

Dollar breakdown fields (endowment_board_designated, endowment_restricted_perm,
endowment_restricted_temp, endowment_unrestricted) are calculated at load time
by multiplying the reported EOY percentage × endowment_eoy.

Usage:
    # Validation institutions only (dry run)
    .venv/bin/python3 ingestion/990/schedule_d_parser.py \\
        --db data/databases/990_data.db \\
        --ein 042103544 041081650 042103545 042103580 042103594 --dry-run

    # Full TEOS universe
    .venv/bin/python3 ingestion/990/schedule_d_parser.py \\
        --db data/databases/990_data.db
"""

import argparse
import logging
import sqlite3
from pathlib import Path

from irsx.filing import Filing

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "990_schedule_d_schema.sql"
XML_DIR     = Path(__file__).resolve().parents[2] / "data" / "raw" / "990_xml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _calc_dollars(pct: float | None, eoy: int | None) -> int | None:
    if pct is None or eoy is None:
        return None
    return round(pct * eoy)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        logger.warning("990_schedule_d_schema.sql not found")


UPSERT_SQL = """
INSERT INTO form990_schedule_d (
    object_id, ein, fiscal_year_end,
    endowment_boy, contributions_endowment, investment_return_endowment,
    grants_from_endowment, other_endowment_changes, admin_expenses_endowment,
    endowment_eoy,
    board_designated_pct, perm_restricted_pct, temp_restricted_pct,
    endowment_board_designated, endowment_restricted_perm,
    endowment_restricted_temp, endowment_unrestricted,
    data_source
) VALUES (
    :object_id, :ein, :fiscal_year_end,
    :endowment_boy, :contributions_endowment, :investment_return_endowment,
    :grants_from_endowment, :other_endowment_changes, :admin_expenses_endowment,
    :endowment_eoy,
    :board_designated_pct, :perm_restricted_pct, :temp_restricted_pct,
    :endowment_board_designated, :endowment_restricted_perm,
    :endowment_restricted_temp, :endowment_unrestricted,
    :data_source
)
ON CONFLICT(object_id) DO UPDATE SET
    ein=excluded.ein,
    fiscal_year_end=excluded.fiscal_year_end,
    endowment_boy=excluded.endowment_boy,
    contributions_endowment=excluded.contributions_endowment,
    investment_return_endowment=excluded.investment_return_endowment,
    grants_from_endowment=excluded.grants_from_endowment,
    other_endowment_changes=excluded.other_endowment_changes,
    admin_expenses_endowment=excluded.admin_expenses_endowment,
    endowment_eoy=excluded.endowment_eoy,
    board_designated_pct=excluded.board_designated_pct,
    perm_restricted_pct=excluded.perm_restricted_pct,
    temp_restricted_pct=excluded.temp_restricted_pct,
    endowment_board_designated=excluded.endowment_board_designated,
    endowment_restricted_perm=excluded.endowment_restricted_perm,
    endowment_restricted_temp=excluded.endowment_restricted_temp,
    endowment_unrestricted=excluded.endowment_unrestricted,
    data_source=excluded.data_source,
    loaded_at=datetime('now')
"""


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_schedule_d(xml_path: Path) -> dict | None:
    """
    Parse one Form 990 XML and return a form990_schedule_d row dict.
    Returns None if the filing cannot be parsed or has no Schedule D.
    Returns a dict with endowment_eoy=None if Schedule D exists but no
    endowment data is present (institution has no endowment fund).
    """
    stem      = xml_path.stem
    object_id = stem.replace("_public", "")

    try:
        f = Filing(object_id, filepath=str(xml_path))
        f.process()
    except Exception as exc:
        logger.error(f"IRSx failed on {xml_path.name}: {exc}")
        return None

    if "IRS990" not in f.list_schedules():
        return None

    hdr = f.get_schedule("ReturnHeader990x") or {}
    ein = str(f.get_ein()).zfill(9)

    tax_period_end  = hdr.get("TaxPeriodEndDt", "")
    fiscal_year_end = int(tax_period_end[:4]) if tax_period_end else None

    if "IRS990ScheduleD" not in f.list_schedules():
        return None

    d   = f.get_schedule("IRS990ScheduleD") or {}
    grp = d.get("CYEndwmtFundGrp")
    if not isinstance(grp, dict):
        return None  # No endowment fund data

    endowment_boy               = _int(grp.get("BeginningYearBalanceAmt"))
    contributions_endowment     = _int(grp.get("ContributionsAmt"))
    investment_return_endowment = _int(grp.get("InvestmentEarningsOrLossesAmt"))
    grants_from_endowment       = _int(grp.get("GrantsOrScholarshipsAmt"))
    other_endowment_changes     = _int(grp.get("OtherExpendituresAmt"))
    admin_expenses_endowment    = _int(grp.get("AdministrativeExpensesAmt"))
    endowment_eoy               = _int(grp.get("EndYearBalanceAmt"))

    board_designated_pct = _float(d.get("BoardDesignatedBalanceEOYPct"))
    perm_restricted_pct  = _float(d.get("PrmnntEndowmentBalanceEOYPct"))
    temp_restricted_pct  = _float(d.get("TermEndowmentBalanceEOYPct"))

    # Calculate dollar breakdowns from EOY percentages
    endowment_board_designated = _calc_dollars(board_designated_pct, endowment_eoy)
    endowment_restricted_perm  = _calc_dollars(perm_restricted_pct,  endowment_eoy)
    endowment_restricted_temp  = _calc_dollars(temp_restricted_pct,  endowment_eoy)

    # Residual unrestricted = EOY minus the three accounted-for buckets
    if endowment_eoy is not None and all(
        v is not None for v in [endowment_board_designated,
                                endowment_restricted_perm,
                                endowment_restricted_temp]
    ):
        endowment_unrestricted = (
            endowment_eoy
            - endowment_board_designated
            - endowment_restricted_perm
            - endowment_restricted_temp
        )
    else:
        endowment_unrestricted = None

    return {
        "object_id":                   object_id,
        "ein":                         ein,
        "fiscal_year_end":             fiscal_year_end,
        "endowment_boy":               endowment_boy,
        "contributions_endowment":     contributions_endowment,
        "investment_return_endowment": investment_return_endowment,
        "grants_from_endowment":       grants_from_endowment,
        "other_endowment_changes":     other_endowment_changes,
        "admin_expenses_endowment":    admin_expenses_endowment,
        "endowment_eoy":               endowment_eoy,
        "board_designated_pct":        board_designated_pct,
        "perm_restricted_pct":         perm_restricted_pct,
        "temp_restricted_pct":         temp_restricted_pct,
        "endowment_board_designated":  endowment_board_designated,
        "endowment_restricted_perm":   endowment_restricted_perm,
        "endowment_restricted_temp":   endowment_restricted_temp,
        "endowment_unrestricted":      endowment_unrestricted,
        "data_source":                 "irsx",
    }


# ---------------------------------------------------------------------------
# Print helper
# ---------------------------------------------------------------------------

def print_row(row: dict) -> None:
    print(f"\n{'='*70}")
    print(f"  EIN {row['ein']}  FY{row['fiscal_year_end']}  [{row['object_id']}]")
    print(f"{'='*70}")

    def fmt(v):
        if v is None:
            return "          NULL"
        return f"  ${v:>14,.0f}"

    def pct(v):
        return f"{v*100:>6.1f}%" if v is not None else "   NULL"

    print(f"  {'Endowment BOY':<35} {fmt(row.get('endowment_boy'))}")
    print(f"  {'  + Contributions':<35} {fmt(row.get('contributions_endowment'))}")
    print(f"  {'  + Investment return':<35} {fmt(row.get('investment_return_endowment'))}")
    print(f"  {'  - Grants/scholarships':<35} {fmt(row.get('grants_from_endowment'))}")
    print(f"  {'  - Other expenditures':<35} {fmt(row.get('other_endowment_changes'))}")
    print(f"  {'  - Admin expenses':<35} {fmt(row.get('admin_expenses_endowment'))}")
    print(f"  {'Endowment EOY':<35} {fmt(row.get('endowment_eoy'))}")
    print()
    print(f"  EOY breakdown:")
    print(f"    Board-designated:   {pct(row.get('board_designated_pct'))}  "
          f"{fmt(row.get('endowment_board_designated'))}")
    print(f"    Perm. restricted:   {pct(row.get('perm_restricted_pct'))}  "
          f"{fmt(row.get('endowment_restricted_perm'))}")
    print(f"    Temp. restricted:   {pct(row.get('temp_restricted_pct'))}  "
          f"{fmt(row.get('endowment_restricted_temp'))}")
    print(f"    Unrestricted (res): {'':>7}  {fmt(row.get('endowment_unrestricted'))}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(xml_files: list[Path], db_path: str, ein_filter: set[str] | None,
        dry_run: bool) -> None:
    conn = sqlite3.connect(db_path)
    init_db(conn)

    parsed = written = skipped = no_sched_d = errors = 0
    for xml_path in xml_files:
        row = extract_schedule_d(xml_path)
        if row is None:
            errors += 1
            continue

        if ein_filter and row["ein"] not in ein_filter:
            skipped += 1
            continue

        if row.get("endowment_eoy") is None:
            no_sched_d += 1
            continue  # Has Schedule D but no endowment fund data

        parsed += 1
        if dry_run:
            print_row(row)

        if not dry_run:
            conn.execute(UPSERT_SQL, row)
            written += 1
            if written % 500 == 0:
                conn.commit()
                logger.info(f"  ... {written} rows written")

    conn.commit()
    conn.close()

    action = "would write" if dry_run else "written"
    logger.info(
        f"Done — {parsed} parsed, {written} {action}, "
        f"{skipped} skipped (EIN filter), {no_sched_d} no endowment data, "
        f"{errors} errors"
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Parse Form 990 Schedule D Part V endowment data from TEOS XML"
    )
    parser.add_argument("--db", required=True, help="Path to 990_data.db")
    parser.add_argument("--xml", nargs="+",
                        help="Specific XML file(s); default: all in data/raw/990_xml/")
    parser.add_argument("--ein", nargs="+",
                        help="Filter to these EINs only (zero-padded, no hyphens)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print without writing to DB")
    args = parser.parse_args()

    if args.xml:
        xml_files = [Path(p) for p in args.xml]
    else:
        xml_files = sorted(XML_DIR.glob("*_public.xml"))

    if not xml_files:
        logger.error("No XML files found")
        return

    ein_filter = None
    if args.ein:
        ein_filter = {e.replace("-", "").strip().zfill(9) for e in args.ein}

    logger.info(f"Schedule D parse — {len(xml_files)} XML files"
                + (f", EIN filter: {ein_filter}" if ein_filter else ""))

    run(xml_files, args.db, ein_filter, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
