#!/usr/bin/env python3
"""
ingestion/eada/loader.py
-------------------------
Loads EADA InstLevel.xlsx from downloaded ZIPs into eada_data.db.

Each ZIP contains InstLevel.xlsx (or instLevel.xlsx in older files).
One row per institution per year. PRIMARY KEY is (unitid, survey_year).

survey_year convention: END year of the academic year.
  EADA file "EADA_2022-2023.zip" → survey_year = 2023.
Join conventions:
  eada ↔ 990:   eada.survey_year = form990_filings.fiscal_year_end
  eada ↔ IPEDS: eada.survey_year = ipeds.survey_year + 1

Columns loaded from InstLevel.xlsx (key subset of 167-168 available):
  unitid, institution_name, state_cd, ClassificationCode, classification_name,
  sector_cd, sector_name, EFTotalCount,
  GRND_TOTAL_REVENUE, GRND_TOTAL_EXPENSE,
  IL_TOTAL_REVENUE_ALL, IL_TOTAL_EXPENSE_ALL,
  IL_TOTAL_REV_COED, IL_TOTAL_EXP_COED,
  TOT_REVENUE_ALL_NOTALLOC, TOT_EXPENSE_ALL_NOTALLOC,
  STUDENTAID_TOTAL, RECRUITEXP_TOTAL,
  HDCOACH_SALARY_MEN, HDCOACH_SALARY_WOMEN,
  IL_SUM_PARTIC_MEN, IL_SUM_PARTIC_WOMEN

Usage:
    python3 ingestion/eada/loader.py --db data/databases/eada_data.db \\
        --zip-dir data/raw/eada_csv

    # Single year only
    python3 ingestion/eada/loader.py --db data/databases/eada_data.db \\
        --zip-dir data/raw/eada_csv --year 2023
"""

import argparse
import io
import logging
import re
import sqlite3
import zipfile
from pathlib import Path

import openpyxl
import xlrd

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "eada_schema.sql"

# Map from EADA Excel column header → schema column name.
# Missing headers in older files are silently skipped (→ NULL).
COLUMN_MAP = {
    "unitid":                   "unitid",
    "institution_name":         "institution_name",
    "state_cd":                 "state_cd",
    "ClassificationCode":       "classification_code",
    "classification_name":      "classification_name",
    "sector_cd":                "sector_cd",
    "sector_name":              "sector_name",
    "EFTotalCount":             "ef_total_count",
    "GRND_TOTAL_REVENUE":       "grnd_total_revenue",
    "GRND_TOTAL_EXPENSE":       "grnd_total_expense",
    "IL_TOTAL_REVENUE_ALL":     "il_total_revenue_all",
    "IL_TOTAL_EXPENSE_ALL":     "il_total_expense_all",
    "IL_TOTAL_REV_COED":        "il_total_rev_coed",
    "IL_TOTAL_EXP_COED":        "il_total_exp_coed",
    "TOT_REVENUE_ALL_NOTALLOC": "tot_revenue_not_alloc",
    "TOT_EXPENSE_ALL_NOTALLOC": "tot_expense_not_alloc",
    "STUDENTAID_TOTAL":         "studentaid_total",
    "RECRUITEXP_TOTAL":         "recruitexp_total",
    "HDCOACH_SALARY_MEN":       "hdcoach_salary_men",
    "HDCOACH_SALARY_WOMEN":     "hdcoach_salary_women",
    "IL_SUM_PARTIC_MEN":        "partic_men",
    "IL_SUM_PARTIC_WOMEN":      "partic_women",
}

UPSERT_SQL = """
INSERT INTO eada_instlevel (
    unitid, survey_year, institution_name, state_cd,
    classification_code, classification_name, sector_cd, sector_name,
    ef_total_count,
    grnd_total_revenue, grnd_total_expense,
    il_total_revenue_all, il_total_expense_all,
    il_total_rev_coed, il_total_exp_coed,
    tot_revenue_not_alloc, tot_expense_not_alloc,
    studentaid_total, recruitexp_total,
    hdcoach_salary_men, hdcoach_salary_women,
    partic_men, partic_women
) VALUES (
    :unitid, :survey_year, :institution_name, :state_cd,
    :classification_code, :classification_name, :sector_cd, :sector_name,
    :ef_total_count,
    :grnd_total_revenue, :grnd_total_expense,
    :il_total_revenue_all, :il_total_expense_all,
    :il_total_rev_coed, :il_total_exp_coed,
    :tot_revenue_not_alloc, :tot_expense_not_alloc,
    :studentaid_total, :recruitexp_total,
    :hdcoach_salary_men, :hdcoach_salary_women,
    :partic_men, :partic_women
)
ON CONFLICT(unitid, survey_year) DO UPDATE SET
    institution_name        = excluded.institution_name,
    state_cd                = excluded.state_cd,
    classification_code     = excluded.classification_code,
    classification_name     = excluded.classification_name,
    sector_cd               = excluded.sector_cd,
    sector_name             = excluded.sector_name,
    ef_total_count          = excluded.ef_total_count,
    grnd_total_revenue      = excluded.grnd_total_revenue,
    grnd_total_expense      = excluded.grnd_total_expense,
    il_total_revenue_all    = excluded.il_total_revenue_all,
    il_total_expense_all    = excluded.il_total_expense_all,
    il_total_rev_coed       = excluded.il_total_rev_coed,
    il_total_exp_coed       = excluded.il_total_exp_coed,
    tot_revenue_not_alloc   = excluded.tot_revenue_not_alloc,
    tot_expense_not_alloc   = excluded.tot_expense_not_alloc,
    studentaid_total        = excluded.studentaid_total,
    recruitexp_total        = excluded.recruitexp_total,
    hdcoach_salary_men      = excluded.hdcoach_salary_men,
    hdcoach_salary_women    = excluded.hdcoach_salary_women,
    partic_men              = excluded.partic_men,
    partic_women            = excluded.partic_women,
    loaded_at               = datetime('now')
"""


def init_db(conn: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        raise FileNotFoundError(f"Schema not found: {SCHEMA_PATH}")


def _year_from_filename(filename: str) -> int | None:
    """
    Extract the survey_year (end year) from a filename like:
        EADA_2022-2023.zip   → 2023
        EADA 2012-2013.zip   → 2013
    """
    m = re.search(r"(\d{4})-(\d{4})", filename)
    if m:
        return int(m.group(2))
    return None


def _open_instlevel(zf: zipfile.ZipFile) -> list[list] | None:
    """
    Return InstLevel data as list-of-rows (including header row) from a ZipFile.
    Handles both .xlsx (2013+) and .xls (2001-2012) formats.
    """
    names = {n.lower(): n for n in zf.namelist()}

    # Try .xlsx first
    xlsx_key = next((k for k in names if "instlevel" in k and k.endswith(".xlsx")), None)
    if xlsx_key:
        with zf.open(names[xlsx_key]) as f:
            wb = openpyxl.load_workbook(io.BytesIO(f.read()), read_only=True)
            return list(wb.active.iter_rows(values_only=True))

    # Fall back to .xls
    xls_key = next((k for k in names if "instlevel" in k and k.endswith(".xls")), None)
    if xls_key:
        with zf.open(names[xls_key]) as f:
            wb = xlrd.open_workbook(file_contents=f.read())
            ws = wb.sheet_by_index(0)
            return [tuple(ws.cell_value(r, c) for c in range(ws.ncols))
                    for r in range(ws.nrows)]

    return None


def load_zip(conn: sqlite3.Connection, zip_path: Path) -> tuple[int, int]:
    """
    Load one EADA ZIP into the DB.
    Returns (loaded, skipped) counts.
    """
    survey_year = _year_from_filename(zip_path.name)
    if survey_year is None:
        logger.warning(f"Cannot parse year from filename: {zip_path.name} — skipping")
        return 0, 0

    with zipfile.ZipFile(zip_path) as zf:
        rows = _open_instlevel(zf)
        if rows is None:
            logger.warning(f"No InstLevel file in {zip_path.name} — skipping")
            return 0, 0

    if not rows:
        return 0, 0

    headers = [str(h) if h is not None else "" for h in rows[0]]

    # Build index: schema_col → position in Excel row
    col_idx: dict[str, int] = {}
    for xls_col, db_col in COLUMN_MAP.items():
        if xls_col in headers:
            col_idx[db_col] = headers.index(xls_col)

    if "unitid" not in col_idx:
        logger.error(f"No 'unitid' column in {zip_path.name} — skipping")
        return 0, 0

    loaded = skipped = 0
    for data_row in rows[1:]:
        uid = data_row[col_idx["unitid"]]
        if uid is None:
            skipped += 1
            continue

        row: dict = {"survey_year": survey_year}
        for db_col, idx in col_idx.items():
            val = data_row[idx]
            # Coerce to int where numeric columns have float representation
            if isinstance(val, float) and val == int(val):
                val = int(val)
            row[db_col] = val

        # Fill any missing optional columns with None
        for db_col in COLUMN_MAP.values():
            row.setdefault(db_col, None)

        conn.execute(UPSERT_SQL, row)
        loaded += 1

    conn.commit()
    return loaded, skipped


def run(zip_dir: Path, db_path: str, target_year: int | None = None) -> None:
    conn = sqlite3.connect(db_path)
    init_db(conn)

    # Find ZIPs matching the primary per-year pattern
    zip_files = sorted(
        p for p in zip_dir.glob("EADA*.zip")
        if "combined" not in p.name.lower() and "all_data" not in p.name.lower() and "all data" not in p.name.lower()
    )

    if target_year is not None:
        zip_files = [p for p in zip_files if _year_from_filename(p.name) == target_year]

    logger.info(f"EADA LOAD — {len(zip_files)} ZIP file(s) in {zip_dir}")

    total_loaded = total_skipped = 0
    for zip_path in zip_files:
        yr = _year_from_filename(zip_path.name)
        loaded, skipped = load_zip(conn, zip_path)
        logger.info(f"  Year {yr} ({zip_path.name}): {loaded:,} rows loaded, {skipped} skipped")
        total_loaded  += loaded
        total_skipped += skipped

    conn.close()
    logger.info(f"Load complete — {total_loaded:,} rows loaded, {total_skipped} skipped")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Load EADA InstLevel data into eada_data.db")
    parser.add_argument("--db", default="data/databases/eada_data.db",
                        help="Path to eada_data.db")
    parser.add_argument("--zip-dir", default="data/raw/eada_csv",
                        help="Directory containing downloaded EADA ZIPs")
    parser.add_argument("--year", type=int, default=None,
                        help="Load only this end-year (e.g. 2023 for AY 2022-23)")
    args = parser.parse_args()

    run(Path(args.zip_dir), args.db, target_year=args.year)


if __name__ == "__main__":
    main()
