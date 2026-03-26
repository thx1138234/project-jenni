#!/usr/bin/env python3
"""
ingestion/990/compensation_parser.py
--------------------------------------
Parse IRS Form 990 Schedule J officer/director/key employee compensation into
form990_compensation. Source: TEOS/IRSx XML only.

Data sources per record:
  Schedule J Part II (RltdOrgOfficerTrstKeyEmplGrp):
    comp_base, comp_bonus, comp_other, comp_deferred, comp_nontaxable,
    comp_total, related_org_comp

  Part VII Section A (Form990PartVIISectionAGrp), joined by officer_name:
    hours_per_week, former_officer, is_officer, is_key_employee, is_highest_comp

ProPublica gap: ProPublica API only exposes aggregate officer compensation
(compnsatncurrofcr), not per-person Schedule J breakdowns. For FY2012–2019
per-person data, download pre-2019 TEOS XML (IRS portal has index years 2013–2018).

Usage:
    # Validation institutions only (dry run)
    .venv/bin/python3 ingestion/990/compensation_parser.py \\
        --db data/databases/990_data.db \\
        --ein 042103544 041081650 042103545 042103580 042103594 --dry-run

    # Full TEOS universe
    .venv/bin/python3 ingestion/990/compensation_parser.py \\
        --db data/databases/990_data.db
"""

import argparse
import logging
import sqlite3
from pathlib import Path

from irsx.filing import Filing

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "990_compensation_schema.sql"
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


def _flag(d: dict, key: str) -> int:
    """Return 1 if d[key] == 'X', else 0."""
    return 1 if d.get(key) == "X" else 0


def _name(entry: dict) -> str | None:
    """Extract person name from Part VII or Schedule J entry.
    Handles both PersonNm (most cases) and BusinessName.BusinessNameLine1Txt."""
    name = entry.get("PersonNm")
    if name:
        return name.strip()
    biz = entry.get("BusinessName")
    if isinstance(biz, dict):
        n = biz.get("BusinessNameLine1Txt")
        if n:
            return n.strip()
    return None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        logger.warning("990_compensation_schema.sql not found")


UPSERT_SQL = """
INSERT INTO form990_compensation (
    object_id, ein, fiscal_year_end, officer_name, officer_title,
    comp_base, comp_bonus, comp_other, comp_deferred, comp_nontaxable,
    comp_total, related_org_comp,
    hours_per_week, former_officer, is_officer, is_key_employee, is_highest_comp,
    data_source
) VALUES (
    :object_id, :ein, :fiscal_year_end, :officer_name, :officer_title,
    :comp_base, :comp_bonus, :comp_other, :comp_deferred, :comp_nontaxable,
    :comp_total, :related_org_comp,
    :hours_per_week, :former_officer, :is_officer, :is_key_employee, :is_highest_comp,
    :data_source
)
ON CONFLICT(object_id, officer_name) DO UPDATE SET
    ein=excluded.ein,
    fiscal_year_end=excluded.fiscal_year_end,
    officer_title=excluded.officer_title,
    comp_base=excluded.comp_base,
    comp_bonus=excluded.comp_bonus,
    comp_other=excluded.comp_other,
    comp_deferred=excluded.comp_deferred,
    comp_nontaxable=excluded.comp_nontaxable,
    comp_total=excluded.comp_total,
    related_org_comp=excluded.related_org_comp,
    hours_per_week=excluded.hours_per_week,
    former_officer=excluded.former_officer,
    is_officer=excluded.is_officer,
    is_key_employee=excluded.is_key_employee,
    is_highest_comp=excluded.is_highest_comp,
    data_source=excluded.data_source,
    loaded_at=datetime('now')
"""


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_compensation(xml_path: Path) -> tuple[str | None, list[dict]]:
    """
    Parse one Form 990 XML and return (ein, list_of_compensation_rows).
    Returns (None, []) if the filing cannot be parsed.

    Strategy:
    1. Extract Schedule J Part II for detailed comp breakdown.
    2. Build a Part VII Section A lookup (by name) for hours/week and role flags.
    3. Join Schedule J entries to Part VII lookup by officer_name.
    """
    stem      = xml_path.stem
    object_id = stem.replace("_public", "")

    try:
        f = Filing(object_id, filepath=str(xml_path))
        f.process()
    except Exception as exc:
        logger.error(f"IRSx failed on {xml_path.name}: {exc}")
        return None, []

    if "IRS990" not in f.list_schedules():
        return None, []

    s   = f.get_schedule("IRS990")
    hdr = f.get_schedule("ReturnHeader990x") or {}

    ein = str(f.get_ein()).zfill(9)

    tax_period_end = hdr.get("TaxPeriodEndDt", "")
    fiscal_year_end = int(tax_period_end[:4]) if tax_period_end else None

    # ------------------------------------------------------------------
    # Build Part VII Section A lookup: name → {hours_per_week, flags...}
    # ------------------------------------------------------------------
    part7_raw = s.get("Form990PartVIISectionAGrp") or []
    if isinstance(part7_raw, dict):
        part7_raw = [part7_raw]

    part7_by_name: dict[str, dict] = {}
    for entry in part7_raw:
        name = _name(entry)
        if name:
            part7_by_name[name.upper()] = entry

    # ------------------------------------------------------------------
    # Schedule J Part II — one dict or list of dicts
    # ------------------------------------------------------------------
    if "IRS990ScheduleJ" not in f.list_schedules():
        return ein, []

    j = f.get_schedule("IRS990ScheduleJ")
    officers_raw = j.get("RltdOrgOfficerTrstKeyEmplGrp", [])
    if isinstance(officers_raw, dict):
        officers_raw = [officers_raw]

    rows = []
    for o in officers_raw:
        name = _name(o)
        if not name:
            continue

        title = o.get("TitleTxt", "").strip() or None

        comp_base       = _int(o.get("BaseCompensationFilingOrgAmt"))
        comp_bonus      = _int(o.get("BonusFilingOrganizationAmount"))
        comp_other      = _int(o.get("OtherCompensationFilingOrgAmt"))
        comp_deferred   = _int(o.get("DeferredCompensationFlngOrgAmt"))
        comp_nontaxable = _int(o.get("NontaxableBenefitsFilingOrgAmt"))
        comp_total      = _int(o.get("TotalCompensationFilingOrgAmt"))
        related_org     = _int(o.get("TotalCompensationRltdOrgsAmt"))

        # Augment from Part VII Section A
        p7 = part7_by_name.get(name.upper(), {})
        hours_per_week  = _float(p7.get("AverageHoursPerWeekRt"))
        former_officer  = _flag(p7, "FormerOfcrDirectorTrusteeInd")
        is_officer      = _flag(p7, "OfficerInd")
        is_key_employee = _flag(p7, "KeyEmployeeInd")
        is_highest_comp = _flag(p7, "HighestCompensatedEmployeeInd")

        rows.append({
            "object_id":       object_id,
            "ein":             ein,
            "fiscal_year_end": fiscal_year_end,
            "officer_name":    name,
            "officer_title":   title,
            "comp_base":       comp_base,
            "comp_bonus":      comp_bonus,
            "comp_other":      comp_other,
            "comp_deferred":   comp_deferred,
            "comp_nontaxable": comp_nontaxable,
            "comp_total":      comp_total,
            "related_org_comp":related_org,
            "hours_per_week":  hours_per_week,
            "former_officer":  former_officer,
            "is_officer":      is_officer,
            "is_key_employee": is_key_employee,
            "is_highest_comp": is_highest_comp,
            "data_source":     "irsx",
        })

    return ein, rows


# ---------------------------------------------------------------------------
# Print helper
# ---------------------------------------------------------------------------

def print_filing_comp(ein: str, rows: list[dict]) -> None:
    if not rows:
        return
    fy   = rows[0].get("fiscal_year_end")
    oid  = rows[0].get("object_id")
    print(f"\n{'='*80}")
    print(f"  EIN {ein}  FY{fy}  [{oid}]  —  {len(rows)} Schedule J entries")
    print(f"{'='*80}")
    print(f"  {'Name':<35} {'Title':<30} {'Total':>12} {'Related':>10} {'Hrs/wk':>7}")
    print(f"  {'-'*97}")
    for r in sorted(rows, key=lambda x: -(x.get("comp_total") or 0)):
        total   = f"${r['comp_total']:>11,}" if r.get("comp_total") is not None else "       NULL"
        related = f"${r['related_org_comp']:>9,}" if r.get("related_org_comp") is not None else "      NULL"
        hrs     = f"{r['hours_per_week']:>6.1f}" if r.get("hours_per_week") is not None else "  NULL"
        flag    = " [FORMER]" if r.get("former_officer") else ""
        print(f"  {(r['officer_name'] or '')[:35]:<35} "
              f"{(r['officer_title'] or '')[:30]:<30} "
              f"{total} {related} {hrs}{flag}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(xml_files: list[Path], db_path: str, ein_filter: set[str] | None,
        dry_run: bool) -> None:
    conn = sqlite3.connect(db_path)
    init_db(conn)

    filings_parsed = person_rows = skipped = errors = 0
    for xml_path in xml_files:
        ein, rows = extract_compensation(xml_path)
        if ein is None:
            errors += 1
            continue

        if ein_filter and ein not in ein_filter:
            skipped += 1
            continue

        if not rows:
            continue  # No Schedule J — institution has no high-comp staff (rare)

        filings_parsed += 1
        if dry_run:
            print_filing_comp(ein, rows)

        if not dry_run:
            for row in rows:
                conn.execute(UPSERT_SQL, row)
            person_rows += len(rows)
            if filings_parsed % 500 == 0:
                conn.commit()
                logger.info(f"  ... {filings_parsed} filings, {person_rows} rows")

    conn.commit()
    conn.close()

    action = "would write" if dry_run else "written"
    logger.info(
        f"Done — {filings_parsed} filings parsed, {person_rows} person-rows {action}, "
        f"{skipped} skipped (EIN filter), {errors} errors"
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Parse Form 990 Schedule J officer compensation from TEOS XML"
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

    logger.info(f"Compensation parse — {len(xml_files)} XML files"
                + (f", EIN filter: {ein_filter}" if ein_filter else ""))

    run(xml_files, args.db, ein_filter, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
