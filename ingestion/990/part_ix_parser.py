#!/usr/bin/env python3
"""
ingestion/990/part_ix_parser.py
---------------------------------
Phase A: Parse Form 990 Part IX (Statement of Functional Expenses) —
functional column breakdowns from TEOS/IRSx XML into form990_part_ix.

Extracts:
  Line 25 — Total functional expenses: cols B (program services), C (mgmt & general), D (fundraising)
  Line 12 — Advertising and promotion: cols B, C, D
  Line 14 — Information technology: cols B, C, D
  Line 11e — Professional fundraising service fees (TotalAmt)
  Line 11f — Investment management fees (TotalAmt)

Calculates on load (requires form990_filings row for same object_id):
  prog_services_pct      = total_prog_services / total_functional_expenses
  overhead_ratio         = (total_mgmt_general + total_fundraising_exp) / total_functional_expenses
  fundraising_efficiency = total_fundraising_exp / contributions_grants

ProPublica rows: NULL by design — ProPublica API does not expose column breakdowns.

Usage:
    # Validation institutions only (dry run)
    python3 ingestion/990/part_ix_parser.py --db data/databases/990_data.db \\
        --ein 042103544 041081650 042103545 042103580 042103594 --dry-run

    # Full TEOS universe
    python3 ingestion/990/part_ix_parser.py --db data/databases/990_data.db
"""

import argparse
import logging
import sqlite3
from pathlib import Path

from irsx.filing import Filing

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "990_part_ix_schema.sql"
XML_DIR     = Path(__file__).resolve().parents[2] / "data" / "raw" / "990_xml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _grp(d: dict | None, key: str) -> int | None:
    if not isinstance(d, dict):
        return None
    return _int(d.get(key))


def _ratio(numerator, denominator) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 6)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        logger.warning("990_part_ix_schema.sql not found")


UPSERT_SQL = """
INSERT INTO form990_part_ix (
    object_id, ein, fiscal_year_end,
    total_prog_services, total_mgmt_general, total_fundraising_exp,
    advertising_prog, advertising_mgmt, advertising_fundraising,
    it_prog, it_mgmt, it_fundraising,
    prof_fundraising_fees, invest_mgmt_fees,
    prog_services_pct, overhead_ratio, fundraising_efficiency
) VALUES (
    :object_id, :ein, :fiscal_year_end,
    :total_prog_services, :total_mgmt_general, :total_fundraising_exp,
    :advertising_prog, :advertising_mgmt, :advertising_fundraising,
    :it_prog, :it_mgmt, :it_fundraising,
    :prof_fundraising_fees, :invest_mgmt_fees,
    :prog_services_pct, :overhead_ratio, :fundraising_efficiency
)
ON CONFLICT(object_id) DO UPDATE SET
    ein=excluded.ein, fiscal_year_end=excluded.fiscal_year_end,
    total_prog_services=excluded.total_prog_services,
    total_mgmt_general=excluded.total_mgmt_general,
    total_fundraising_exp=excluded.total_fundraising_exp,
    advertising_prog=excluded.advertising_prog,
    advertising_mgmt=excluded.advertising_mgmt,
    advertising_fundraising=excluded.advertising_fundraising,
    it_prog=excluded.it_prog,
    it_mgmt=excluded.it_mgmt,
    it_fundraising=excluded.it_fundraising,
    prof_fundraising_fees=excluded.prof_fundraising_fees,
    invest_mgmt_fees=excluded.invest_mgmt_fees,
    prog_services_pct=excluded.prog_services_pct,
    overhead_ratio=excluded.overhead_ratio,
    fundraising_efficiency=excluded.fundraising_efficiency,
    loaded_at=datetime('now')
"""


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_part_ix(xml_path: Path, conn: sqlite3.Connection | None) -> dict | None:
    """
    Parse one Form 990 XML and return a form990_part_ix row dict.
    conn is used to look up total_functional_expenses and contributions_grants
    from form990_filings for ratio calculation.
    Returns None if the filing cannot be parsed.
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

    s   = f.get_schedule("IRS990")
    hdr = f.get_schedule("ReturnHeader990x") or {}

    ein = str(f.get_ein()).zfill(9)

    tax_period_end = hdr.get("TaxPeriodEndDt", "")
    fiscal_year_end = int(tax_period_end[:4]) if tax_period_end else None

    # ------------------------------------------------------------------
    # Line 25 — Total functional expenses by column
    # ------------------------------------------------------------------
    tfe = s.get("TotalFunctionalExpensesGrp") or {}
    total_prog_services   = _grp(tfe, "ProgramServicesAmt")
    total_mgmt_general    = _grp(tfe, "ManagementAndGeneralAmt")
    total_fundraising_exp = _grp(tfe, "FundraisingAmt")
    # Column A (total) from the same group — used for ratio denominator
    total_functional_exp  = _grp(tfe, "TotalAmt")

    # ------------------------------------------------------------------
    # Line 12 — Advertising and promotion
    # ------------------------------------------------------------------
    adv = s.get("AdvertisingGrp") or {}
    advertising_prog        = _grp(adv, "ProgramServicesAmt")
    advertising_mgmt        = _grp(adv, "ManagementAndGeneralAmt")
    advertising_fundraising = _grp(adv, "FundraisingAmt")

    # ------------------------------------------------------------------
    # Line 14 — Information technology
    # ------------------------------------------------------------------
    it = s.get("InformationTechnologyGrp") or {}
    it_prog        = _grp(it, "ProgramServicesAmt")
    it_mgmt        = _grp(it, "ManagementAndGeneralAmt")
    it_fundraising = _grp(it, "FundraisingAmt")

    # ------------------------------------------------------------------
    # Line 11e — Professional fundraising service fees
    # ------------------------------------------------------------------
    pff = s.get("FeesForServicesProfFundraising") or {}
    prof_fundraising_fees = _grp(pff, "TotalAmt")

    # ------------------------------------------------------------------
    # Line 11f — Investment management fees
    # ------------------------------------------------------------------
    imf = s.get("FeesForSrvcInvstMgmntFeesGrp") or {}
    invest_mgmt_fees = _grp(imf, "TotalAmt")

    # ------------------------------------------------------------------
    # Look up contributions_grants from form990_filings for ratio calc
    # ------------------------------------------------------------------
    contributions_grants = None
    if conn is not None:
        r = conn.execute(
            "SELECT contributions_grants FROM form990_filings WHERE object_id=?",
            (object_id,)
        ).fetchone()
        if r:
            contributions_grants = r[0]

    # If total_functional_exp is NULL here, try to fall back to form990_filings
    if total_functional_exp is None and conn is not None:
        r2 = conn.execute(
            "SELECT total_functional_expenses FROM form990_filings WHERE object_id=?",
            (object_id,)
        ).fetchone()
        if r2:
            total_functional_exp = r2[0]

    # ------------------------------------------------------------------
    # Calculated ratios
    # ------------------------------------------------------------------
    prog_services_pct = _ratio(total_prog_services, total_functional_exp)

    overhead_num = None
    if total_mgmt_general is not None and total_fundraising_exp is not None:
        overhead_num = total_mgmt_general + total_fundraising_exp
    elif total_mgmt_general is not None:
        overhead_num = total_mgmt_general
    elif total_fundraising_exp is not None:
        overhead_num = total_fundraising_exp
    overhead_ratio = _ratio(overhead_num, total_functional_exp)

    fundraising_efficiency = _ratio(total_fundraising_exp, contributions_grants)

    return {
        "object_id":              object_id,
        "ein":                    ein,
        "fiscal_year_end":        fiscal_year_end,
        "total_prog_services":    total_prog_services,
        "total_mgmt_general":     total_mgmt_general,
        "total_fundraising_exp":  total_fundraising_exp,
        "advertising_prog":       advertising_prog,
        "advertising_mgmt":       advertising_mgmt,
        "advertising_fundraising":advertising_fundraising,
        "it_prog":                it_prog,
        "it_mgmt":                it_mgmt,
        "it_fundraising":         it_fundraising,
        "prof_fundraising_fees":  prof_fundraising_fees,
        "invest_mgmt_fees":       invest_mgmt_fees,
        "prog_services_pct":      prog_services_pct,
        "overhead_ratio":         overhead_ratio,
        "fundraising_efficiency": fundraising_efficiency,
    }


# ---------------------------------------------------------------------------
# Print helper
# ---------------------------------------------------------------------------

def print_row(row: dict) -> None:
    tfe = (row.get("total_prog_services") or 0) + \
          (row.get("total_mgmt_general") or 0) + \
          (row.get("total_fundraising_exp") or 0)
    print(f"\n{'='*65}")
    print(f"  EIN {row.get('ein')}  FY{row.get('fiscal_year_end')}  "
          f"[{row.get('object_id')}]")
    print(f"{'='*65}")
    print(f"  {'Column':<30} {'Prog Svc (B)':>14} {'Mgmt/Gen (C)':>14} {'Fundraising (D)':>16}")
    print(f"  {'-'*78}")

    def fmt(v):
        return f"${v:>13,}" if v is not None else f"{'NULL':>14}"

    print(f"  {'Line 25 — Total func exp':<30} "
          f"{fmt(row.get('total_prog_services'))} "
          f"{fmt(row.get('total_mgmt_general'))} "
          f"{fmt(row.get('total_fundraising_exp'))}")
    print(f"  {'Line 12 — Advertising':<30} "
          f"{fmt(row.get('advertising_prog'))} "
          f"{fmt(row.get('advertising_mgmt'))} "
          f"{fmt(row.get('advertising_fundraising'))}")
    print(f"  {'Line 14 — IT expenses':<30} "
          f"{fmt(row.get('it_prog'))} "
          f"{fmt(row.get('it_mgmt'))} "
          f"{fmt(row.get('it_fundraising'))}")
    print(f"  {'Line 11e — Prof fund fees':<30} "
          f"{'':14} {'':14} {fmt(row.get('prof_fundraising_fees'))}")
    print(f"  {'Line 11f — Invest mgmt fees':<30} "
          f"{'':14} {fmt(row.get('invest_mgmt_fees'))} {'':16}")
    print()

    def pct(v):
        return f"{v*100:.1f}%" if v is not None else "NULL"

    print(f"  prog_services_pct      = {pct(row.get('prog_services_pct'))}")
    print(f"  overhead_ratio         = {pct(row.get('overhead_ratio'))}")
    print(f"  fundraising_efficiency = {pct(row.get('fundraising_efficiency'))}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(xml_files: list[Path], db_path: str, ein_filter: set[str] | None,
        dry_run: bool) -> None:
    conn = sqlite3.connect(db_path)
    init_db(conn)

    parsed = written = skipped = errors = 0
    for xml_path in xml_files:
        row = extract_part_ix(xml_path, conn)
        if row is None:
            errors += 1
            continue

        if ein_filter and row["ein"] not in ein_filter:
            skipped += 1
            continue

        parsed += 1
        if dry_run or logger.isEnabledFor(logging.DEBUG):
            print_row(row)

        if not dry_run:
            conn.execute(UPSERT_SQL, row)
            if parsed % 500 == 0:
                conn.commit()
                logger.info(f"  ... {parsed} rows written")
            written += 1

    conn.commit()
    conn.close()

    action = "would write" if dry_run else "written"
    logger.info(f"Done — {parsed} parsed, {written} {action}, "
                f"{skipped} skipped (EIN filter), {errors} errors")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Parse Form 990 Part IX functional columns from TEOS XML"
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

    logger.info(f"Part IX parse — {len(xml_files)} XML files"
                + (f", EIN filter: {ein_filter}" if ein_filter else ""))

    run(xml_files, args.db, ein_filter, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
