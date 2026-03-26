#!/usr/bin/env python3
"""
ingestion/eada/sports_loader.py
---------------------------------
Load EADA Schools (sport-level) data from downloaded ZIPs into eada_sports.

Each EADA ZIP contains a Schools.xlsx (or schools.xls for 2000-2011) with one
row per sport per institution. This loader reads all 24 years (2000-01 through
2023-24) and produces one row per (unitid, survey_year, sport_code).

survey_year convention: END year of academic year.
  "EADA 2022-2023.zip" → survey_year = 2023.
  Matches eada_instlevel. Join on (unitid, survey_year).

COACHING SALARY NOTE: The Schools file has coach COUNT columns (FT/PT, male/female)
but NO salary dollar amounts at the sport level. Per-sport coaching salary is not
collected by the Dept of Education in EADA reporting. Institutional totals
(hdcoach_salary_men, hdcoach_salary_women) are in eada_instlevel.

Usage:
    .venv/bin/python3 ingestion/eada/sports_loader.py \\
        --db data/databases/eada_data.db \\
        --zip-dir data/raw/eada_csv

    # Single year
    .venv/bin/python3 ingestion/eada/sports_loader.py \\
        --db data/databases/eada_data.db \\
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

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "eada_sports_schema.sql"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _year_from_filename(filename: str) -> int | None:
    """
    Extract survey_year (end year) from EADA ZIP filename.
    "EADA 2022-2023.zip" → 2023
    "EADA_2016-2017.zip" → 2017
    """
    m = re.search(r"(\d{4})-(\d{4})", filename)
    if m:
        return int(m.group(2))
    return None


def _int(val) -> int | None:
    if val is None or val == "":
        return None
    try:
        v = int(float(str(val).strip().replace(",", "")))
        return None if v < 0 else v
    except (ValueError, TypeError):
        return None


def _sport_code(val) -> int | None:
    try:
        return int(float(str(val).strip()))  # xlrd returns floats; int("5.0") fails
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# File readers — returns list of dicts with normalized keys
# ---------------------------------------------------------------------------

def _read_xlsx(data: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        wb.close()
        return []
    # Normalize headers: strip whitespace, preserve case for map lookup
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    result = [dict(zip(headers, row)) for row in rows[1:]]
    wb.close()
    return result


def _read_xls(data: bytes) -> list[dict]:
    wb = xlrd.open_workbook(file_contents=data)
    ws = wb.sheet_by_index(0)
    if ws.nrows < 2:
        return []
    headers = [str(ws.cell_value(0, c)).strip() for c in range(ws.ncols)]
    result = []
    for r in range(1, ws.nrows):
        result.append({headers[c]: ws.cell_value(r, c) for c in range(ws.ncols)})
    return result


def _get_schools_data(zf: zipfile.ZipFile) -> list[dict] | None:
    """Find and read the Schools file from an open ZIP. Returns None if not found."""
    names_lower = {n.lower(): n for n in zf.namelist()}

    for candidate in ["schools.xlsx", "schools.xls"]:
        if candidate in names_lower:
            actual = names_lower[candidate]
            data = zf.read(actual)
            if candidate.endswith(".xlsx"):
                return _read_xlsx(data)
            else:
                return _read_xls(data)
    return None


# ---------------------------------------------------------------------------
# Row mapper
# ---------------------------------------------------------------------------

# Header aliases across years (some headers have minor spelling variants)
_COL_ALIASES: dict[str, list[str]] = {
    "unitid":               ["unitid"],
    "sport_code":           ["SPORTSCODE"],
    "sport_name":           ["Sports"],
    "classification_name":  ["classification_name"],
    "participants_men":     ["PARTIC_MEN"],
    "participants_women":   ["PARTIC_WOMEN"],
    "total_revenue":        ["TOTAL_REVENUE_ALL"],
    "rev_men":              ["REV_MEN"],
    "rev_women":            ["REV_WOMEN"],
    "total_expenses":       ["TOTAL_EXPENSE_ALL"],
    "exp_men":              ["EXP_MEN"],
    "exp_women":            ["EXP_WOMEN"],
    "total_opexp":          ["TOTAL_OPEXP_INCLCOED"],
    "headcoach_count_men":  ["MEN_TOTAL_HEADCOACH"],
    "headcoach_count_women":["WOMEN_TOTAL_HDCOACH"],
}


def _make_lookup(raw_headers: list[str]) -> dict[str, str]:
    """Build case-insensitive alias → actual header mapping."""
    upper_map = {h.upper(): h for h in raw_headers}
    result = {}
    for field, aliases in _COL_ALIASES.items():
        for alias in aliases:
            if alias.upper() in upper_map:
                result[field] = upper_map[alias.upper()]
                break
    return result


def map_row(raw: dict, lookup: dict, survey_year: int) -> dict | None:
    """Map a raw Schools row to eada_sports schema. Returns None if no unitid."""
    def get(field):
        col = lookup.get(field)
        return raw.get(col) if col else None

    unitid    = _int(get("unitid"))
    sportcode = _sport_code(get("sport_code"))
    if unitid is None or sportcode is None:
        return None

    return {
        "unitid":               unitid,
        "survey_year":          survey_year,
        "sport_code":           sportcode,
        "sport_name":           (str(get("sport_name") or "")).strip() or None,
        "classification_name":  (str(get("classification_name") or "")).strip() or None,
        "participants_men":     _int(get("participants_men")),
        "participants_women":   _int(get("participants_women")),
        "total_revenue":        _int(get("total_revenue")),
        "rev_men":              _int(get("rev_men")),
        "rev_women":            _int(get("rev_women")),
        "total_expenses":       _int(get("total_expenses")),
        "exp_men":              _int(get("exp_men")),
        "exp_women":            _int(get("exp_women")),
        "total_opexp":          _int(get("total_opexp")),
        "headcoach_count_men":  _int(get("headcoach_count_men")),
        "headcoach_count_women":_int(get("headcoach_count_women")),
    }


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO eada_sports (
    unitid, survey_year, sport_code, sport_name, classification_name,
    participants_men, participants_women,
    total_revenue, rev_men, rev_women,
    total_expenses, exp_men, exp_women, total_opexp,
    headcoach_count_men, headcoach_count_women
) VALUES (
    :unitid, :survey_year, :sport_code, :sport_name, :classification_name,
    :participants_men, :participants_women,
    :total_revenue, :rev_men, :rev_women,
    :total_expenses, :exp_men, :exp_women, :total_opexp,
    :headcoach_count_men, :headcoach_count_women
)
ON CONFLICT(unitid, survey_year, sport_code) DO UPDATE SET
    sport_name              = excluded.sport_name,
    classification_name     = excluded.classification_name,
    participants_men        = excluded.participants_men,
    participants_women      = excluded.participants_women,
    total_revenue           = excluded.total_revenue,
    rev_men                 = excluded.rev_men,
    rev_women               = excluded.rev_women,
    total_expenses          = excluded.total_expenses,
    exp_men                 = excluded.exp_men,
    exp_women               = excluded.exp_women,
    total_opexp             = excluded.total_opexp,
    headcoach_count_men     = excluded.headcoach_count_men,
    headcoach_count_women   = excluded.headcoach_count_women,
    loaded_at               = datetime('now')
"""


def init_db(conn: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        raise FileNotFoundError(f"Schema not found: {SCHEMA_PATH}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(zip_dir: Path, db_path: str, year_filter: int | None = None) -> None:
    conn = sqlite3.connect(db_path)
    init_db(conn)

    zip_files = sorted(zip_dir.glob("EADA*.zip"))
    total_rows = 0
    years_loaded = []

    for zpath in zip_files:
        survey_year = _year_from_filename(zpath.name)
        if survey_year is None:
            logger.warning(f"Cannot parse year from {zpath.name} — skipping")
            continue
        if year_filter and survey_year != year_filter:
            continue

        try:
            with zipfile.ZipFile(zpath) as zf:
                rows_data = _get_schools_data(zf)
        except Exception as e:
            logger.error(f"{zpath.name}: {e}")
            continue

        if rows_data is None:
            logger.warning(f"{zpath.name}: no Schools file found")
            continue

        if not rows_data:
            logger.warning(f"{zpath.name}: Schools file is empty")
            continue

        lookup = _make_lookup(list(rows_data[0].keys()))
        written = 0
        for raw in rows_data:
            row = map_row(raw, lookup, survey_year)
            if row is None:
                continue
            conn.execute(UPSERT_SQL, row)
            written += 1

        conn.commit()
        total_rows += written
        years_loaded.append(survey_year)
        logger.info(f"{zpath.name}: {written:,} rows")

    conn.close()
    if years_loaded:
        logger.info(
            f"Done — {total_rows:,} total rows, "
            f"{len(years_loaded)} years ({min(years_loaded)}–{max(years_loaded)})"
        )
    else:
        logger.warning("No years loaded.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Load EADA sport-level data (Schools file)")
    parser.add_argument("--db", required=True, help="Path to eada_data.db")
    parser.add_argument("--zip-dir", required=True, help="Path to data/raw/eada_csv/")
    parser.add_argument("--year", type=int, help="Single survey year (end year) to load")
    args = parser.parse_args()

    run(Path(args.zip_dir), args.db, year_filter=args.year)


if __name__ == "__main__":
    main()
