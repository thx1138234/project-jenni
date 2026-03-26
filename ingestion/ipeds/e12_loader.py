#!/usr/bin/env python3
"""
ingestion/ipeds/e12_loader.py
------------------------------
Load IPEDS EFIA 12-month enrollment data into ipeds_e12.

Source: data/raw/ipeds_csv/E12/{year}/efia{year}.csv (2012+).

FTE fields are the NCES-computed values:
  ugfte12  = EFTEUG  (undergraduate credit hours / 30)
  grfte12  = EFTEGD  (graduate credit hours / 24)
  dpp_fte12 = FTEDPP (doctoral/professional practice credit hours / 24)
  fte12     = sum of the above (computed here at load time)

Headcount fields (ug12, gr12, total12) are NOT in the EFIA format.
CDACTUA and CDACTGA are total credit hours (the FTE denominator inputs),
not unduplicated headcounts.

Usage:
    .venv/bin/python3 ingestion/ipeds/e12_loader.py \\
        --db data/databases/ipeds_data.db \\
        --dir data/raw/ipeds_csv/E12
"""

import argparse
import csv
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "ipeds_e12_schema.sql"


def _int(val) -> int | None:
    if val is None:
        return None
    try:
        v = int(str(val).strip())
        return None if v < 0 else v   # NCES uses -1/-2 for suppressed/N/A
    except (ValueError, TypeError):
        return None


def _acttype(val) -> int | None:
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return None


UPSERT_SQL = """
INSERT INTO ipeds_e12 (
    unitid, survey_year,
    ug_credit_hrs, gr_credit_hrs,
    ugfte12, grfte12, dpp_fte12, fte12,
    acttype
) VALUES (
    :unitid, :survey_year,
    :ug_credit_hrs, :gr_credit_hrs,
    :ugfte12, :grfte12, :dpp_fte12, :fte12,
    :acttype
)
ON CONFLICT(unitid, survey_year) DO UPDATE SET
    ug_credit_hrs = excluded.ug_credit_hrs,
    gr_credit_hrs = excluded.gr_credit_hrs,
    ugfte12       = excluded.ugfte12,
    grfte12       = excluded.grfte12,
    dpp_fte12     = excluded.dpp_fte12,
    fte12         = excluded.fte12,
    acttype       = excluded.acttype,
    loaded_at     = datetime('now')
"""


def load_year(conn: sqlite3.Connection, csv_path: Path, survey_year: int) -> int:
    """Load one EFIA CSV file. Returns number of rows written."""
    written = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Normalize headers: strip whitespace, uppercase for lookup
        raw_headers = reader.fieldnames or []
        header_map = {h.strip().upper(): h for h in raw_headers}

        def get(row, *candidates):
            for c in candidates:
                if c in header_map:
                    return row.get(header_map[c])
            return None

        for row in reader:
            unitid = _int(get(row, "UNITID"))
            if unitid is None:
                continue

            ugfte12  = _int(get(row, "EFTEUG"))
            grfte12  = _int(get(row, "EFTEGD"))
            dpp_fte12 = _int(get(row, "FTEDPP"))

            # fte12 = sum of the three FTE components; NULL if all three are NULL
            components = [v for v in [ugfte12, grfte12, dpp_fte12] if v is not None]
            fte12 = sum(components) if components else None

            conn.execute(UPSERT_SQL, {
                "unitid":        unitid,
                "survey_year":   survey_year,
                "ug_credit_hrs": _int(get(row, "CDACTUA")),
                "gr_credit_hrs": _int(get(row, "CDACTGA")),
                "ugfte12":       ugfte12,
                "grfte12":       grfte12,
                "dpp_fte12":     dpp_fte12,
                "fte12":         fte12,
                "acttype":       _acttype(get(row, "ACTTYPE")),
            })
            written += 1

    return written


def run(e12_dir: Path, db_path: str, year_filter: list[int] | None = None) -> None:
    conn = sqlite3.connect(db_path)
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        raise FileNotFoundError(f"Schema not found: {SCHEMA_PATH}")

    total_written = 0
    years_loaded = []

    year_dirs = sorted(e12_dir.iterdir())
    for year_dir in year_dirs:
        if not year_dir.is_dir():
            continue
        try:
            survey_year = int(year_dir.name)
        except ValueError:
            continue

        if year_filter and survey_year not in year_filter:
            continue

        # Find main CSV — prefer non-revision file
        csvs = sorted(year_dir.glob("*.csv"))
        main_csvs = [c for c in csvs if "_rv" not in c.name.lower()]
        if not main_csvs:
            main_csvs = csvs
        if not main_csvs:
            logger.warning(f"No CSV in E12/{survey_year} — skipping")
            continue

        csv_path = main_csvs[0]
        try:
            n = load_year(conn, csv_path, survey_year)
            conn.commit()
            total_written += n
            years_loaded.append(survey_year)
            logger.info(f"E12 {survey_year}: {n:,} rows from {csv_path.name}")
        except Exception as e:
            logger.error(f"E12 {survey_year}: {e}")

    conn.close()
    logger.info(
        f"Done — {total_written:,} rows written across {len(years_loaded)} years "
        f"({min(years_loaded) if years_loaded else '?'}–{max(years_loaded) if years_loaded else '?'})"
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Load IPEDS E12 (EFIA) enrollment data")
    parser.add_argument("--db",  required=True, help="Path to ipeds_data.db")
    parser.add_argument("--dir", required=True, help="Path to data/raw/ipeds_csv/E12/")
    parser.add_argument("--year", nargs="+", type=int, help="Specific survey years to load")
    args = parser.parse_args()

    run(Path(args.dir), args.db, year_filter=args.year)


if __name__ == "__main__":
    main()
