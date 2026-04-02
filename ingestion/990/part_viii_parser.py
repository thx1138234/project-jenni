#!/usr/bin/env python3
"""
ingestion/990/part_viii_parser.py
------------------------------------
Parse IRS Form 990 Part VIII (Statement of Revenue) — Tier 1 sub-line fields.

Extracts granular revenue sub-lines not captured in form990_filings:
  Line 1e — Government grants (GovernmentGrantsAmt)
  Line 1f — All other contributions (AllOtherContributionsAmt)
  Lines 2a–2e — Program service revenue by named program (up to 5)

form990_filings already captures aggregate Part VIII totals
(contributions_grants, program_service_revenue, investment_income,
net_gain_investments, other_revenue, total_revenue). This table adds
the sub-line detail not available there.

TEOS/IRSx source only. ProPublica API does not expose Part VIII sub-lines.

Usage:
    # Validation institutions only (dry run)
    .venv/bin/python3 ingestion/990/part_viii_parser.py --db data/databases/990_data.db \\
        --ein 042103544 041081650 042103545 042103580 042103594 --dry-run

    # Full TEOS universe
    .venv/bin/python3 ingestion/990/part_viii_parser.py --db data/databases/990_data.db

    # Via supplemental_runner (parsers=part_viii)
    .venv/bin/python3 ingestion/990/supplemental_runner.py \\
        --db data/databases/990_data.db --xml data/raw/990_xml --parsers part_viii
"""

import argparse
import logging
import sqlite3
from pathlib import Path

from irsx.filing import Filing

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "990_part_viii_schema.sql"
XML_DIR     = Path(__file__).resolve().parents[2] / "data" / "raw" / "990_xml"

# Columns in insertion order (excluding loaded_at which uses DEFAULT)
_COLS = [
    "object_id", "ein", "fiscal_year_end",
    "govt_grants_amt", "all_other_contributions_amt",
    "prog_svc_revenue_2a", "prog_svc_desc_2a",
    "prog_svc_revenue_2b", "prog_svc_desc_2b",
    "prog_svc_revenue_2c", "prog_svc_desc_2c",
    "prog_svc_revenue_2d", "prog_svc_desc_2d",
    "prog_svc_revenue_2e", "prog_svc_desc_2e",
]

_col_csv       = ", ".join(_COLS)
_ph_csv        = ", ".join(f":{c}" for c in _COLS)
_update_csv    = ",\n    ".join(f"{c}=excluded.{c}" for c in _COLS if c != "object_id")
UPSERT_SQL = f"""
INSERT INTO form990_part_viii ({_col_csv})
VALUES ({_ph_csv})
ON CONFLICT(object_id) DO UPDATE SET
    {_update_csv},
    loaded_at=datetime('now')
"""

# Program service line slots (lines 2a–2e)
_PROG_SLOTS = ["2a", "2b", "2c", "2d", "2e"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _str(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        logger.warning("990_part_viii_schema.sql not found — table may not exist")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_part_viii(object_id: str, xml_path: Path) -> dict | None:
    """
    Parse one Form 990 XML and return a form990_part_viii row dict.
    Returns None if the filing cannot be parsed or has no Part VIII data.
    """
    try:
        f = Filing(object_id, filepath=str(xml_path))
        f.process()
    except Exception as exc:
        logger.error(f"IRSx failed on {xml_path.name}: {exc}")
        return None

    if "IRS990" not in f.list_schedules():
        return None

    try:
        sked = f.get_schedule("IRS990")
        hdr  = f.get_schedule("ReturnHeader990x") or {}
    except Exception as exc:
        logger.warning(f"Schedule access failed {object_id}: {exc}")
        return None

    if not sked:
        return None

    ein = str(f.get_ein()).zfill(9)

    tax_period_end  = hdr.get("TaxPeriodEndDt", "")
    fiscal_year_end = int(tax_period_end[:4]) if tax_period_end else None

    # ------------------------------------------------------------------
    # Line 1e — Government grants
    # Line 1f — All other contributions
    # ------------------------------------------------------------------
    govt_grants_amt             = _int(sked.get("GovernmentGrantsAmt"))
    all_other_contributions_amt = _int(sked.get("AllOtherContributionsAmt"))

    # ------------------------------------------------------------------
    # Lines 2a–2e — Program service revenue by program
    # ProgramServiceRevenueGrp is a list (up to 7 items in the XML).
    # irsx returns it as list[dict] or a single dict (if only 1 entry).
    # ------------------------------------------------------------------
    prog_grps = sked.get("ProgramServiceRevenueGrp") or []
    if isinstance(prog_grps, dict):
        prog_grps = [prog_grps]
    if not isinstance(prog_grps, list):
        prog_grps = []

    row: dict = {
        "object_id":                    object_id,
        "ein":                          ein,
        "fiscal_year_end":              fiscal_year_end,
        "govt_grants_amt":              govt_grants_amt,
        "all_other_contributions_amt":  all_other_contributions_amt,
    }

    for i, slot in enumerate(_PROG_SLOTS):
        grp = prog_grps[i] if i < len(prog_grps) else {}
        row[f"prog_svc_revenue_{slot}"] = _int(grp.get("TotalRevenueColumnAmt"))
        row[f"prog_svc_desc_{slot}"]    = _str(grp.get("Desc"))

    # Skip rows where all Tier 1 fields are NULL (nothing to store)
    tier1_vals = [
        govt_grants_amt, all_other_contributions_amt,
        row.get("prog_svc_revenue_2a"),
    ]
    if all(v is None for v in tier1_vals):
        return None

    return row


# ---------------------------------------------------------------------------
# Main pipeline (supplemental_runner interface)
# ---------------------------------------------------------------------------

def run(
    db_path: str,
    xml_dir: Path = XML_DIR,
    target_eins: set[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Run Part VIII extraction over all TEOS XML files in xml_dir.
    Called by supplemental_runner as: mod.run(db, xml_dir)
    Returns summary dict.
    """
    conn = sqlite3.connect(db_path)
    init_db(conn)

    xml_files = sorted(xml_dir.glob("*_public.xml"))
    logger.info(f"Part VIII parser — {len(xml_files):,} XML files")

    processed = written = skipped = errors = 0

    for xml_path in xml_files:
        stem      = xml_path.stem
        object_id = stem.replace("_public", "")

        # Quick EIN filter from filename is not possible; filter after extract
        row = extract_part_viii(object_id, xml_path)

        if row is None:
            errors += 1
            continue

        if target_eins and row["ein"] not in target_eins:
            skipped += 1
            continue

        processed += 1

        if dry_run:
            logger.info(
                f"  DRY RUN {object_id} EIN {row['ein']} FY{row['fiscal_year_end']}: "
                f"govt={row['govt_grants_amt']} "
                f"other_contrib={row['all_other_contributions_amt']} "
                f"2a={row['prog_svc_revenue_2a']} [{row['prog_svc_desc_2a']}]"
            )
            written += 1
            continue

        conn.execute(UPSERT_SQL, row)
        written += 1

        if written % 500 == 0:
            conn.commit()
            logger.info(f"  ... {written:,} rows written")

    conn.commit()
    conn.close()

    action = "would write" if dry_run else "written"
    logger.info(
        f"Part VIII complete: {written:,} {action}, "
        f"{skipped:,} skipped (EIN filter), {errors:,} null/error"
    )
    return {"rows": written, "processed": processed, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Parse Form 990 Part VIII (revenue sub-lines) from TEOS XML"
    )
    parser.add_argument("--db",      required=True, help="Path to 990_data.db")
    parser.add_argument("--xml-dir", default=str(XML_DIR),
                        help="Directory containing *_public.xml files")
    parser.add_argument("--ein",     nargs="+",
                        help="Filter to these EINs only (zero-padded, no hyphens)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print without writing to DB")
    args = parser.parse_args()

    target_eins = None
    if args.ein:
        target_eins = {e.replace("-", "").strip().zfill(9) for e in args.ein}

    run(
        db_path    = args.db,
        xml_dir    = Path(args.xml_dir),
        target_eins = target_eins,
        dry_run    = args.dry_run,
    )


if __name__ == "__main__":
    main()
