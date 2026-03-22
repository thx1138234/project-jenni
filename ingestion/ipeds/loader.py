#!/usr/bin/env python3
"""
ipeds_loader.py
---------------
Normalizes IPEDS CSV files and loads them into the SQLite database.
Handles the full complexity of IPEDS data across 25 years:
  - Variable name changes across years
  - GASB vs FASB finance split
  - Multi-part component files (EF has 4 parts)
  - Missing/suppressed data (privacy protection)
  - Imputed values flagged by NCES

Usage:
    python loader.py --db path/to/ipeds_data.db
    python loader.py --db path/to/ipeds_data.db --component IC EF
    python loader.py --db path/to/ipeds_data.db --year 2022 2023
    python loader.py --db path/to/ipeds_data.db --component IC --year 2022

Architecture:
    Each component has a dedicated loader class that:
    1. Reads the raw CSV
    2. Maps NCES variable names to our schema columns (handles year-to-year changes)
    3. Cleans and coerces data types
    4. Upserts into the target table
"""

import os
import re
import csv
import json
import sqlite3
import logging
import argparse
import traceback
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RAW_DIR  = Path(__file__).parent.parent.parent / "data" / "raw" / "ipeds_csv"
SCHEMA   = Path(__file__).parent.parent.parent / "schema" / "ipeds_schema.sql"
LOG_FILE = Path(__file__).parent.parent.parent / "data" / "raw" / "ipeds_csv" / "loader.log"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database Utilities
# ---------------------------------------------------------------------------

def get_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")   # 64MB cache
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_db(db_path):
    """Create all tables from schema file if they don't exist."""
    conn = get_connection(db_path)
    with open(SCHEMA) as f:
        conn.executescript(f.read())
    conn.commit()
    logger.info(f"Database initialized: {db_path}")
    return conn


def upsert_rows(conn, table, rows, conflict_cols):
    """
    Generic upsert — INSERT OR REPLACE for SQLite.
    rows: list of dicts
    """
    if not rows:
        return 0

    cols     = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(cols)
    sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"

    data = [tuple(row.get(c) for c in cols) for row in rows]

    with conn:
        conn.executemany(sql, data)
    return len(rows)


# ---------------------------------------------------------------------------
# Data Cleaning Utilities
# ---------------------------------------------------------------------------

def to_int(val):
    """Convert to int, returning None for blanks, dots, and suppressed values."""
    if val is None:
        return None
    val = str(val).strip()
    if val in ("", ".", "-1", "-2"):   # NCES uses -1/-2 for suppressed/not applicable
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def to_float(val):
    if val is None:
        return None
    val = str(val).strip()
    if val in ("", ".", "-1", "-2"):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def read_csv(filepath):
    """Read a CSV file, returning list of dicts with lowercased column names."""
    rows = []
    try:
        with open(filepath, encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Lowercase all column names for consistent access
                rows.append({k.lower().strip(): v for k, v in row.items()})
    except FileNotFoundError:
        logger.warning(f"File not found: {filepath}")
    except Exception as e:
        logger.error(f"Error reading {filepath}: {e}")
    return rows


def find_csv(component_key, year, pattern_hints):
    """
    Locate a CSV file for a given component/year, handling NCES naming quirks.
    Returns Path or None.
    """
    base = RAW_DIR / component_key / str(year)
    if not base.exists():
        return None

    for hint in pattern_hints:
        # Direct filename match
        candidate = base / hint
        if candidate.exists():
            return candidate

        # Case-insensitive search
        for f in base.iterdir():
            if f.name.lower() == hint.lower():
                return f
            if hint.lower() in f.name.lower() and f.suffix.lower() == ".csv":
                return f

    # Fallback: return first CSV found
    csvs = list(base.glob("*.csv"))
    if csvs:
        logger.debug(f"Fallback CSV: {csvs[0]}")
        return csvs[0]
    return None


# ---------------------------------------------------------------------------
# COMPONENT LOADERS
# Each loader handles one IPEDS survey component.
# ---------------------------------------------------------------------------

class ICLoader:
    """
    Institutional Characteristics (IC) — merges two NCES files per year:
      - IC{year}.csv      : program offerings, calendar, admissions policy
      - IC{year}_AY.csv   : academic year charges (tuition, fees, room & board)

    NCES splits these into separate files. We merge by unitid before loading.

    Variable name evolution:
      - Pre-2014: admissions data was part of IC
      - Post-2014: admissions split into ADM component
      - Room & board: IC_AY uses chg4ay0 (on-campus, current year)
    """
    TABLE = "ipeds_ic"
    COMPONENT = "IC"

    # Fields from IC{year}.csv (program offerings, calendar)
    IC_FIELDS = {
        "calendar_system":  ["calsys", "calendaryr", "calendar"],
        "offers_undergrad": ["ugoffer", "level1"],
        "offers_graduate":  ["groffer", "level3"],
        "offers_distance_ed": ["distnced"],
        "openadmp":         ["openadmp"],
        "sat_act_req":      ["admcon7"],
        "credit_ap":        ["credits1"],
        "credit_clep":      ["credits2"],
    }

    # Fields from IC{year}_AY.csv (academic year charges)
    AY_FIELDS = {
        "tuition_indistrict":    ["tuition1", "tuiindc"],
        "tuition_instate":       ["tuition2", "tuition"],
        "tuition_outstate":      ["tuition3", "tuitionout"],
        "fee_indistrict":        ["fee1", "fee"],
        "fee_instate":           ["fee2"],
        "fee_outstate":          ["fee3"],
        "tuition_grad_instate":  ["tuition5", "gradtuition"],
        "tuition_grad_outstate": ["tuition6"],
        # roomboard_oncampus is computed below by summing chg4ay0 + chg5ay0
        # (room charge + board charge separately reported in IC_AY)
        "books_oncampus":        ["chg3ay0", "books"],
        # otherexp not summed here — chg6ay0 is off-campus other, not on-campus
        "otherexp_oncampus":     ["otherex"],
    }

    def _apply_map(self, raw, field_map):
        result = {}
        for col, candidates in field_map.items():
            result[col] = None
            for c in candidates:
                if c in raw and raw[c] not in ("", None):
                    result[col] = raw[c]
                    break
        return result

    def load(self, conn, year):
        # Load IC (program offerings)
        ic_path = find_csv(self.COMPONENT, year,
                           [f"ic{year}.csv", f"IC{year}.csv"])
        # Load IC_AY (charges)
        ay_path = find_csv(self.COMPONENT, year,
                           [f"ic{year}_ay.csv", f"IC{year}_AY.csv"])

        if not ic_path and not ay_path:
            logger.warning(f"IC {year}: no CSV found")
            return 0

        # Build lookup dicts keyed by unitid
        ic_by_unitid = {}
        if ic_path:
            for raw in read_csv(ic_path):
                uid = to_int(raw.get("unitid"))
                if uid:
                    ic_by_unitid[uid] = raw

        ay_by_unitid = {}
        if ay_path:
            for raw in read_csv(ay_path):
                uid = to_int(raw.get("unitid"))
                if uid:
                    ay_by_unitid[uid] = raw

        all_unitids = set(ic_by_unitid) | set(ay_by_unitid)
        logger.info(f"IC {year}: {len(all_unitids)} institutions "
                    f"(IC={len(ic_by_unitid)}, AY={len(ay_by_unitid)})")

        out_rows = []
        for uid in all_unitids:
            ic_raw = ic_by_unitid.get(uid, {})
            ay_raw = ay_by_unitid.get(uid, {})

            row = {"unitid": uid, "survey_year": year}
            row.update(self._apply_map(ic_raw, self.IC_FIELDS))
            row.update(self._apply_map(ay_raw, self.AY_FIELDS))

            # Room & board: sum room charge (chg4ay0) + board charge (chg5ay0).
            # IC_AY reports them separately; legacy files may have a combined field.
            room  = to_int(ay_raw.get("chg4ay0"))
            board = to_int(ay_raw.get("chg5ay0"))
            if room is not None or board is not None:
                row["roomboard_oncampus"] = (room or 0) + (board or 0)
            else:
                row["roomboard_oncampus"] = to_int(ay_raw.get("roomboard") or ay_raw.get("room"))

            # Type coercion
            row["tuition_indistrict"]    = to_int(row["tuition_indistrict"])
            row["tuition_instate"]       = to_int(row["tuition_instate"])
            row["tuition_outstate"]      = to_int(row["tuition_outstate"])
            row["fee_indistrict"]        = to_int(row["fee_indistrict"])
            row["fee_instate"]           = to_int(row["fee_instate"])
            row["fee_outstate"]          = to_int(row["fee_outstate"])
            row["tuition_grad_instate"]  = to_int(row["tuition_grad_instate"])
            row["tuition_grad_outstate"] = to_int(row["tuition_grad_outstate"])
            row["books_oncampus"]        = to_int(row["books_oncampus"])
            row["otherexp_oncampus"]     = to_int(row["otherexp_oncampus"])
            row["calendar_system"]       = to_int(row["calendar_system"])
            row["offers_undergrad"]      = to_int(row["offers_undergrad"])
            row["offers_graduate"]       = to_int(row["offers_graduate"])
            row["openadmp"]              = to_int(row["openadmp"])
            row["sat_act_req"]           = to_int(row["sat_act_req"])

            out_rows.append(row)

        n = upsert_rows(conn, self.TABLE, out_rows, ["unitid", "survey_year"])
        logger.info(f"IC {year}: {n} rows loaded")
        return n


class EFLoader:
    """
    Fall Enrollment (EF) — Multi-part component.
    Part A: Student counts by race/ethnicity, gender, level
    Part B: Age distribution (less frequently used)
    Part C: Residence of first-time students (even years only)
    Part D: Total enrollment summary
    """
    TABLE = "ipeds_ef"
    COMPONENT = "EF"

    def load(self, conn, year):
        rows_d = self._load_part_d(conn, year)   # Summary totals
        rows_a = self._load_part_a(conn, year)   # Race/ethnicity detail
        return rows_d + rows_a

    def _load_part_d(self, conn, year):
        """Part D: enrollment totals and student-faculty ratio."""
        csv_path = find_csv(self.COMPONENT, year,
                            [f"ef{year}d.csv", f"EF{year}D.csv"])
        if not csv_path:
            return 0

        raw_rows = read_csv(csv_path)
        out_rows = []
        for raw in raw_rows:
            row = {
                "unitid":       to_int(raw.get("unitid")),
                "survey_year":  year,
                "enrtot":       to_int(raw.get("efytotlt") or raw.get("eftotlt")),
                "enrugrd":      to_int(raw.get("efyugrdlt") or raw.get("efugrdlt")),
                "enrgrad":      to_int(raw.get("efygradlt") or raw.get("efgradlt")),
                "enrft":        to_int(raw.get("efyftlt") or raw.get("efftlt")),
                "enrpt":        to_int(raw.get("efyptlt") or raw.get("efptlt")),
                "stufacr":      to_float(raw.get("stufacr")),
            }
            if row["unitid"]:
                out_rows.append(row)

        n = upsert_rows(conn, self.TABLE, out_rows, ["unitid", "survey_year"])
        logger.info(f"EF-D {year}: {n} rows")
        return n

    def _load_part_a(self, conn, year):
        """
        Part A: enrollment totals + race/ethnicity by efalevel (student level category).

        efalevel = 1  → all students total (enrtot, enrtotm/w, all race cols)
        efalevel = 2  → all undergraduate students (enrugrd)
        efalevel = 12 → all graduate students (enrgrad)

        NOTE: Part D (ef{year}d.csv) contains retention/cohort data, NOT enrollment
        totals. Enrollment totals live here in Part A. Do not look for eftotlt in
        Part D — it won't be there.

        Uses UPDATE to merge into rows seeded by Part D (which loads stufacr).
        Falls back to INSERT for any unitid not already present.
        """
        csv_path = find_csv(self.COMPONENT, year,
                            [f"ef{year}a.csv", f"EF{year}A.csv"])
        if not csv_path:
            return 0

        raw_rows = read_csv(csv_path)

        # Index all rows by (unitid, efalevel) for efficient lookup
        by_level = {}
        for raw in raw_rows:
            uid = to_int(raw.get("unitid"))
            lvl = raw.get("efalevel", "").strip()
            if uid and lvl:
                by_level[(uid, lvl)] = raw

        # Collect unique unitids
        all_unitids = {uid for uid, _ in by_level}

        out_rows = []
        for uid in all_unitids:
            total_raw = by_level.get((uid, "1"), {})
            ugrd_raw  = by_level.get((uid, "2"), {})
            grad_raw  = by_level.get((uid, "12"), {})

            row = {
                "unitid":       uid,
                "survey_year":  year,
                # Enrollment totals from efalevel=1 (all students)
                "enrtot":       to_int(total_raw.get("eftotlt")),
                "enrtotm":      to_int(total_raw.get("eftotlm")),
                "enrtotw":      to_int(total_raw.get("eftotlw")),
                # Sub-totals by level
                "enrugrd":      to_int(ugrd_raw.get("eftotlt")),
                "enrgrad":      to_int(grad_raw.get("eftotlt")),
                # Race/ethnicity from efalevel=1 total row
                "enr_white":    to_int(total_raw.get("efwhitt") or total_raw.get("efwhitlt")),
                "enr_black":    to_int(total_raw.get("efbkaat") or total_raw.get("efbkaalt")),
                "enr_hispanic": to_int(total_raw.get("efhispt") or total_raw.get("efhisplt")),
                "enr_asian":    to_int(total_raw.get("efasiat") or total_raw.get("efasialt")),
                "enr_aian":     to_int(total_raw.get("efaiant") or total_raw.get("efaianlt")),
                "enr_nhpi":     to_int(total_raw.get("efnhpit") or total_raw.get("efnhpilt")),
                "enr_twomore":  to_int(total_raw.get("ef2mort") or total_raw.get("ef2morlt")),
                "enr_unknrace": to_int(total_raw.get("efunknt") or total_raw.get("efunknlt")),
                "enr_nonres":   to_int(total_raw.get("efnralt") or total_raw.get("efnrallt")),
            }
            out_rows.append(row)

        # UPDATE only — do not INSERT OR REPLACE, which would clobber stufacr
        # loaded by Part D.
        race_cols = [
            "enrtot", "enrtotm", "enrtotw", "enrugrd", "enrgrad",
            "enr_white", "enr_black", "enr_hispanic", "enr_asian", "enr_aian",
            "enr_nhpi", "enr_twomore", "enr_unknrace", "enr_nonres",
        ]
        set_clause = ", ".join(f"{c} = ?" for c in race_cols)
        sql = (f"UPDATE {self.TABLE} SET {set_clause} "
               f"WHERE unitid = ? AND survey_year = ?")

        updated = 0
        inserted = 0
        with conn:
            for row in out_rows:
                vals = [row.get(c) for c in race_cols] + [row["unitid"], row["survey_year"]]
                cursor = conn.execute(sql, vals)
                if cursor.rowcount:
                    updated += 1
                else:
                    # Part D row missing (institution not in EF-D) — insert full row
                    upsert_rows(conn, self.TABLE, [row], ["unitid", "survey_year"])
                    inserted += 1

        n = updated + inserted
        logger.info(f"EF-A {year}: {n} rows (updated={updated}, inserted={inserted})")
        return n


class ADMLoader:
    """Admissions (ADM) — standalone from 2014, extracted from IC before that."""
    TABLE = "ipeds_adm"
    COMPONENT = "ADM"

    def load(self, conn, year):
        if year < 2014:
            logger.debug(f"ADM {year}: pre-2014, skip (data in IC)")
            return 0

        csv_path = find_csv(self.COMPONENT, year,
                            [f"adm{year}.csv", f"ADM{year}.csv"])
        if not csv_path:
            return 0

        raw_rows = read_csv(csv_path)
        out_rows = []
        for raw in raw_rows:
            unitid = to_int(raw.get("unitid"))
            if not unitid:
                continue

            applcn = to_int(raw.get("applcn"))
            admssn = to_int(raw.get("admssn"))
            enrlt  = to_int(raw.get("enrlt"))

            row = {
                "unitid":       unitid,
                "survey_year":  year,
                "applcn":       applcn,
                "applcnm":      to_int(raw.get("applcnm")),
                "applcnw":      to_int(raw.get("applcnw")),
                "admssn":       admssn,
                "admssnm":      to_int(raw.get("admssnm")),
                "admssnw":      to_int(raw.get("admssnw")),
                "enrlt":        enrlt,
                "enrlm":        to_int(raw.get("enrlm")),
                "enrlw":        to_int(raw.get("enrlw")),
                "enrlft":       to_int(raw.get("enrlft")),
                "enrlpt":       to_int(raw.get("enrlpt")),

                # Calculated rates
                "admit_rate":   round(admssn / applcn, 4) if applcn else None,
                "yield_rate":   round(enrlt / admssn, 4) if admssn else None,

                # SAT/ACT
                "sat_reading_25": to_int(raw.get("satvr25")),
                "sat_reading_75": to_int(raw.get("satvr75")),
                "sat_math_25":    to_int(raw.get("satmt25")),
                "sat_math_75":    to_int(raw.get("satmt75")),
                "act_composite_25": to_int(raw.get("actcm25")),
                "act_composite_75": to_int(raw.get("actcm75")),
                "act_english_25":   to_int(raw.get("acten25")),
                "act_english_75":   to_int(raw.get("acten75")),
                "act_math_25":      to_int(raw.get("actmt25")),
                "act_math_75":      to_int(raw.get("actmt75")),

                "pct_submitting_sat": to_int(raw.get("satpct")),
                "pct_submitting_act": to_int(raw.get("actpct")),
                "sat_act_required":   to_int(raw.get("admcon7")),
            }
            out_rows.append(row)

        n = upsert_rows(conn, self.TABLE, out_rows, ["unitid", "survey_year"])
        logger.info(f"ADM {year}: {n} rows loaded")
        return n


class CompletionsLoader:
    """
    Completions (C) — highest row count table.
    One row per institution × CIP code × award level.
    Full build: ~50M+ rows.
    """
    TABLE = "ipeds_completions"
    COMPONENT = "C"
    BATCH_SIZE = 10000   # Insert in batches for memory efficiency

    def load(self, conn, year):
        # Try Part A first (race/gender detail), fall back to combined file
        csv_path = find_csv(self.COMPONENT, year,
                            [f"c{year}_a.csv", f"C{year}_A.csv",
                             f"c{year}a.csv",  f"c{year}.csv"])
        if not csv_path:
            logger.warning(f"C {year}: no CSV found")
            return 0

        raw_rows = read_csv(csv_path)
        logger.info(f"C {year}: {len(raw_rows)} raw rows")

        out_rows = []
        inserted = 0

        for raw in raw_rows:
            unitid = to_int(raw.get("unitid"))
            cipcode = raw.get("cipcode", "").strip()
            awlevel = to_int(raw.get("awlevel"))

            if not all([unitid, cipcode, awlevel]):
                continue

            # Derive 2-digit series
            cip2 = cipcode.split(".")[0] if "." in cipcode else cipcode[:2]

            row = {
                "unitid":       unitid,
                "survey_year":  year,
                "cipcode":      cipcode,
                "cip2digit":    cip2,
                "awlevel":      awlevel,

                # Totals
                "ctotalt":  to_int(raw.get("ctotalt")),
                "ctotalm":  to_int(raw.get("ctotalm")),
                "ctotalw":  to_int(raw.get("ctotalw")),

                # Race/ethnicity
                "caiant":   to_int(raw.get("caiant")),
                "casiat":   to_int(raw.get("casiat")),
                "cbkaat":   to_int(raw.get("cbkaat")),
                "chispt":   to_int(raw.get("chispt")),
                "cnhpit":   to_int(raw.get("cnhpit")),
                "cwhitt":   to_int(raw.get("cwhitt")),
                "c2mort":   to_int(raw.get("c2mort")),
                "cunknt":   to_int(raw.get("cunknt")),
                "cnralt":   to_int(raw.get("cnralt")),
                "distance_ed": to_int(raw.get("distanceapp")),
            }
            out_rows.append(row)

            # Batch insert
            if len(out_rows) >= self.BATCH_SIZE:
                inserted += upsert_rows(conn, self.TABLE, out_rows,
                                        ["unitid", "survey_year", "cipcode", "awlevel"])
                out_rows = []

        # Final batch
        if out_rows:
            inserted += upsert_rows(conn, self.TABLE, out_rows,
                                    ["unitid", "survey_year", "cipcode", "awlevel"])

        logger.info(f"C {year}: {inserted} rows loaded")
        return inserted


class GRLoader:
    """Graduation Rates (GR) — 150% time."""
    TABLE = "ipeds_gr"
    COMPONENT = "GR"

    def load(self, conn, year):
        csv_path = find_csv(self.COMPONENT, year,
                            [f"gr{year}.csv", f"GR{year}.csv"])
        if not csv_path:
            return 0

        raw_rows = read_csv(csv_path)
        out_rows = []

        for raw in raw_rows:
            unitid = to_int(raw.get("unitid"))
            if not unitid:
                continue

            # NCES variable names vary; try multiple candidates
            cohort   = to_int(raw.get("bagr100") or raw.get("grcohrt"))
            grad_150 = to_int(raw.get("grtotlt") or raw.get("bagr150"))

            row = {
                "unitid":       unitid,
                "survey_year":  year,
                "gba_cohort":   cohort,
                "gba_grad_150": grad_150,
                "gba_rate_150": round(grad_150 / cohort, 4) if cohort else None,
                "pell_cohort":  to_int(raw.get("pgadjct")),
                "pell_grad_150":to_int(raw.get("pgcmbac")),
                "loan_cohort":  to_int(raw.get("ssadjct")),
                "loan_grad_150":to_int(raw.get("sscmbac")),
            }

            # Pell/loan rates
            if row["pell_cohort"]:
                row["pell_rate_150"] = round(
                    (row["pell_grad_150"] or 0) / row["pell_cohort"], 4)
            if row["loan_cohort"]:
                row["loan_rate_150"] = round(
                    (row["loan_grad_150"] or 0) / row["loan_cohort"], 4)

            out_rows.append(row)

        n = upsert_rows(conn, self.TABLE, out_rows, ["unitid", "survey_year"])
        logger.info(f"GR {year}: {n} rows loaded")
        return n


class FinanceLoader:
    """
    Finance (F) — GASB and FASB in separate files.
    Normalizes into unified ipeds_finance table with reporting_framework flag.
    """
    TABLE = "ipeds_finance"
    COMPONENT = "F"

    def load(self, conn, year):
        year2 = str(year + 1)[-2:]
        total = 0
        total += self._load_fasb(conn, year, year2)
        total += self._load_gasb(conn, year, year2)
        return total

    def _load_fasb(self, conn, year, year2):
        """Public institutions (GASB) — F1A file. Despite the method name,
        empirically F1A contains public/GASB institutions. reporting_framework
        is set to 'GASB'. See CLAUDE.md §0 (Empirical Evidence Beats Documentation)."""
        yr1 = str(year)[-2:]
        csv_path = find_csv(self.COMPONENT, year, [
            f"f{yr1}{year2}_f1a.csv", f"F{yr1}{year2}_F1A.csv",
            f"f{yr1}{year2}_f1a23.csv"   # Some years have extra suffix
        ])
        if not csv_path:
            return 0

        raw_rows = read_csv(csv_path)
        out_rows = []

        for raw in raw_rows:
            unitid = to_int(raw.get("unitid"))
            if not unitid:
                continue

            row = {
                "unitid":              unitid,
                "survey_year":         year,
                "reporting_framework": "GASB",

                # Revenue
                "rev_tuition_fees":    to_int(raw.get("f1b01") or raw.get("tuitionrev")),
                "tuition_discounts":   to_int(raw.get("f1b04") or raw.get("discounts")),
                "rev_fed_grants":      to_int(raw.get("f1b07")),
                "rev_state_grants":    to_int(raw.get("f1b08")),
                "rev_private_grants":  to_int(raw.get("f1b09")),
                "rev_private_gifts":   to_int(raw.get("f1b06")),
                "rev_investment":      to_int(raw.get("f1b11")),
                "rev_auxiliary":       to_int(raw.get("f1b12")),
                "rev_hospitals":       to_int(raw.get("f1b13")),
                "rev_other":           to_int(raw.get("f1b14")),
                "rev_total":           to_int(raw.get("f1c02") or raw.get("f1b17")),

                # Expenses
                "exp_instruction":       to_int(raw.get("f1d01")),
                "exp_research":          to_int(raw.get("f1d02")),
                "exp_public_service":    to_int(raw.get("f1d03")),
                "exp_academic_support":  to_int(raw.get("f1d04")),
                "exp_student_services":  to_int(raw.get("f1d05")),
                "exp_institutional_support": to_int(raw.get("f1d06")),
                "exp_net_scholarships":  to_int(raw.get("f1d09")),
                "exp_aux_enterprises":   to_int(raw.get("f1d11")),
                "exp_hospitals":         to_int(raw.get("f1d12")),
                "exp_total":             to_int(raw.get("f1e01") or raw.get("f1d15")),

                # Balance Sheet
                "assets_total":          to_int(raw.get("f1h01")),
                "assets_endowment":      to_int(raw.get("f1h10")),
                "liab_total":            to_int(raw.get("f1h18")),
                "liab_longterm_debt":    to_int(raw.get("f1h16")),
                "netassets_total":       to_int(raw.get("f1h27") or raw.get("f1h29")),
                "netassets_unrestricted":     to_int(raw.get("f1h24")),
                "netassets_restricted_temp":  to_int(raw.get("f1h25")),
                "netassets_restricted_perm":  to_int(raw.get("f1h26")),
            }
            out_rows.append(row)

        n = upsert_rows(conn, self.TABLE, out_rows, ["unitid", "survey_year"])
        logger.info(f"F-F1A (GASB/public) {year}: {n} rows loaded")
        return n

    def _load_gasb(self, conn, year, year2):
        """Private nonprofit institutions (FASB) — F2 file. Despite the method
        name, empirically F2 contains private/FASB institutions. reporting_framework
        is set to 'FASB'. See CLAUDE.md §0 (Empirical Evidence Beats Documentation)."""
        yr1 = str(year)[-2:]
        csv_path = find_csv(self.COMPONENT, year, [
            f"f{yr1}{year2}_f2.csv", f"F{yr1}{year2}_F2.csv"
        ])
        if not csv_path:
            return 0

        raw_rows = read_csv(csv_path)
        out_rows = []

        for raw in raw_rows:
            unitid = to_int(raw.get("unitid"))
            if not unitid:
                continue

            row = {
                "unitid":              unitid,
                "survey_year":         year,
                "reporting_framework": "FASB",

                # Revenue (GASB line items differ from FASB)
                "rev_tuition_fees":    to_int(raw.get("f2d01")),
                "rev_fed_approp":      to_int(raw.get("f2d02")),
                "rev_state_approp":    to_int(raw.get("f2d03")),
                "rev_local_approp":    to_int(raw.get("f2d04")),
                "rev_fed_grants":      to_int(raw.get("f2d05")),
                "rev_state_grants":    to_int(raw.get("f2d06")),
                "rev_private_grants":  to_int(raw.get("f2d07")),
                "rev_private_gifts":   to_int(raw.get("f2d08")),
                "rev_investment":      to_int(raw.get("f2d09")),
                "rev_auxiliary":       to_int(raw.get("f2d11")),
                "rev_hospitals":       to_int(raw.get("f2d12")),
                "rev_other":           to_int(raw.get("f2d13")),
                "rev_total":           to_int(raw.get("f2d16") or raw.get("f2d15")),

                # Expenses
                "exp_instruction":       to_int(raw.get("f2e01")),
                "exp_research":          to_int(raw.get("f2e02")),
                "exp_public_service":    to_int(raw.get("f2e03")),
                "exp_academic_support":  to_int(raw.get("f2e04")),
                "exp_student_services":  to_int(raw.get("f2e05")),
                "exp_institutional_support": to_int(raw.get("f2e06")),
                "exp_net_scholarships":  to_int(raw.get("f2e07")),
                "exp_aux_enterprises":   to_int(raw.get("f2e09")),
                "exp_hospitals":         to_int(raw.get("f2e10")),
                "exp_depreciation":      to_int(raw.get("f2e11")),
                "exp_other":             to_int(raw.get("f2e12")),
                "exp_total":             to_int(raw.get("f2e14") or raw.get("f2e13")),

                # Balance Sheet
                "assets_total":          to_int(raw.get("f2h01")),
                "assets_current":        to_int(raw.get("f2h02")),
                "assets_capital_net":    to_int(raw.get("f2h04")),
                "assets_endowment":      to_int(raw.get("f2h05")),
                "liab_total":            to_int(raw.get("f2h12")),
                "liab_current":          to_int(raw.get("f2h13")),
                "liab_longterm_debt":    to_int(raw.get("f2h15")),
                "netassets_total":       to_int(raw.get("f2h20")),
                "netassets_invested_capital": to_int(raw.get("f2h17")),
            }
            out_rows.append(row)

        n = upsert_rows(conn, self.TABLE, out_rows, ["unitid", "survey_year"])
        logger.info(f"F-GASB {year}: {n} rows loaded")
        return n


class SFALoader:
    """Student Financial Aid (SFA)."""
    TABLE = "ipeds_sfa"
    COMPONENT = "SFA"

    def load(self, conn, year):
        year2 = str(year + 1)[-2:]
        csv_path = find_csv(self.COMPONENT, year, [
            f"sfa{year}{year2}.csv", f"SFA{year}{year2}.csv"
        ])
        if not csv_path:
            return 0

        raw_rows = read_csv(csv_path)
        out_rows = []

        for raw in raw_rows:
            unitid = to_int(raw.get("unitid"))
            if not unitid:
                continue

            row = {
                "unitid":       unitid,
                "survey_year":  year,
                "scugffn":      to_int(raw.get("scugffn")),
                "pct_any_grant":  to_float(raw.get("upgrntp")),
                "pct_fed_grant":  to_float(raw.get("uagrntp")),
                "pct_pell":       to_float(raw.get("upgrntp")),
                "avg_any_grant":  to_int(raw.get("npgrn2") or raw.get("grntof2")),
                "avg_pell":       to_int(raw.get("grntwf2") or raw.get("pellofr")),
                "pct_loan":       to_float(raw.get("ufloanp")),
                "avg_loan":       to_int(raw.get("floanof2")),
                "netprice":       to_int(raw.get("npis412") or raw.get("netprice")),
                # Net price by income
                "netprice_0_30k":    to_int(raw.get("npis41")),
                "netprice_30_48k":   to_int(raw.get("npis42")),
                "netprice_48_75k":   to_int(raw.get("npis43")),
                "netprice_75_110k":  to_int(raw.get("npis44")),
                "netprice_over110k": to_int(raw.get("npis45")),
            }
            out_rows.append(row)

        n = upsert_rows(conn, self.TABLE, out_rows, ["unitid", "survey_year"])
        logger.info(f"SFA {year}: {n} rows loaded")
        return n


class HRLoader:
    """
    Human Resources (HR) — merges two NCES files per year:
      - S{year}_SIS.csv  : fall staff survey (instructional staff counts by rank)
      - SAL{year}_IS.csv : instructional staff salaries (one row per institution × rank)

    There is no single HR{year}.zip — do not look for it.
    Salary: SAL file has arank column. arank=1 = professors. We aggregate all ranks
    for avg salary using total 9-month contract amount / total staff count.
    """
    TABLE = "ipeds_hr"
    COMPONENT = "HR"

    def load(self, conn, year):
        sis_path = find_csv(self.COMPONENT, year,
                            [f"s{year}_sis.csv", f"S{year}_SIS.csv"])
        sal_path = find_csv(self.COMPONENT, year,
                            [f"sal{year}_is.csv", f"SAL{year}_IS.csv"])

        if not sis_path and not sal_path:
            logger.warning(f"HR {year}: no SIS or SAL files found")
            return 0

        # Build salary lookup: unitid -> avg 9-month salary across all ranks
        sal_by_unitid = {}
        if sal_path:
            for raw in read_csv(sal_path):
                uid = to_int(raw.get("unitid"))
                if not uid:
                    continue
                # sa09mct = 9-month contract total salary; satotlt = total staff count
                total_sal = to_int(raw.get("sa09mct"))
                total_n   = to_int(raw.get("satotlt"))
                if uid not in sal_by_unitid:
                    sal_by_unitid[uid] = {"sal": 0, "n": 0}
                if total_sal:
                    sal_by_unitid[uid]["sal"] += total_sal
                if total_n:
                    sal_by_unitid[uid]["n"] += total_n

        out_rows = []
        if sis_path:
            raw_rows = read_csv(sis_path)
            for raw in raw_rows:
                unitid = to_int(raw.get("unitid"))
                if not unitid:
                    continue

                sal_data = sal_by_unitid.get(unitid, {})
                sal_total = sal_data.get("sal")
                sal_n     = sal_data.get("n")
                avg_sal   = round(sal_total / sal_n) if sal_total and sal_n else None

                row = {
                    "unitid":          unitid,
                    "survey_year":     year,
                    "ft_instr_total":  to_int(raw.get("sistotl")),
                    "ft_instr_male":   None,   # Not in SIS; available in SAL by rank
                    "ft_instr_female": None,
                    "ft_prof":         to_int(raw.get("sisprof")),
                    "ft_assoc":        to_int(raw.get("sisascp")),
                    "ft_asst":         to_int(raw.get("sisastp")),
                    "sal_prof_9mo":    avg_sal,
                    "emp_total":       to_int(raw.get("sistotl")),
                }
                out_rows.append(row)

        n = upsert_rows(conn, self.TABLE, out_rows, ["unitid", "survey_year"])
        logger.info(f"HR {year}: {n} rows loaded")
        return n


class InstitutionMasterLoader:
    """
    Loads/refreshes the institution_master table from HD (Header/Directory) data.
    HD contains institutional metadata: name, control, Carnegie class, EIN, OPEID.
    Should be run first, before any component loaders.

    Note: IC contains tuition/program data, not institutional metadata.
    The HD file is the authoritative source for institution_master.
    """
    TABLE = "institution_master"

    def load(self, conn, year):
        """Load from HD file for the given year.

        If HD is unavailable (pre-2002 years), seeds institution_master with
        unitid-only stubs from the IC file so FK constraints are satisfied for
        other component loads. Stubs have is_active=0 and NULL metadata.
        """
        csv_path = find_csv("HD", year, [f"hd{year}.csv", f"HD{year}.csv"])
        if not csv_path:
            # HD not available — seed stubs from IC so FK constraints don't block
            # component loads for years before HD files existed on NCES.
            ic_path = find_csv("IC", year, [f"ic{year}.csv", f"IC{year}.csv"])
            if not ic_path:
                logger.warning(f"institution_master {year}: neither HD nor IC found, skipping")
                return 0

            existing = {r[0] for r in conn.execute(
                "SELECT unitid FROM institution_master").fetchall()}
            stubs = []
            for raw in read_csv(ic_path):
                uid = to_int(raw.get("unitid"))
                if uid and uid not in existing:
                    stubs.append({"unitid": uid, "is_active": 0})

            if stubs:
                with conn:
                    conn.executemany(
                        "INSERT OR IGNORE INTO institution_master (unitid, is_active) VALUES (?, ?)",
                        [(s["unitid"], s["is_active"]) for s in stubs]
                    )
                logger.info(f"institution_master {year}: seeded {len(stubs)} stubs "
                            f"(HD unavailable, IC fallback)")
            return len(stubs)

        raw_rows = read_csv(csv_path)
        out_rows = []

        for raw in raw_rows:
            unitid = to_int(raw.get("unitid"))
            if not unitid:
                continue

            control = to_int(raw.get("control"))
            control_labels = {1: "Public", 2: "Private nonprofit", 3: "Private for-profit"}
            iclevel = to_int(raw.get("iclevel"))
            iclevel_labels = {1: "4-year", 2: "2-year", 3: "Less-than-2-year"}

            # Carnegie classification: NCES updates field name with each release
            # c21basic (2021 update) > c18basic (2018) > carnegie (legacy)
            carnegie = to_int(
                raw.get("c21basic") or raw.get("c18basic") or raw.get("carnegie")
            )

            row = {
                "unitid":           unitid,
                "institution_name": raw.get("instnm", "").strip(),
                "city":             raw.get("city", "").strip(),
                "state_abbr":       raw.get("stabbr", "").strip(),
                "state_fips":       to_int(raw.get("fips")),
                "zip":              raw.get("zip", "").strip(),
                "region":           to_int(raw.get("obereg")),
                "locale":           to_int(raw.get("locale")),
                "control":          control,
                "control_label":    control_labels.get(control),
                "reporting_framework": "GASB" if control == 1 else "FASB",
                "hbcu":             to_int(raw.get("hbcu")),
                "tribal_college":   to_int(raw.get("tribal")),
                "hospital":         to_int(raw.get("hospital")),
                "medical_degree":   to_int(raw.get("medical")),
                "land_grant":       to_int(raw.get("landgrnt")),
                "iclevel":          iclevel,
                "iclevel_label":    iclevel_labels.get(iclevel),
                "degree_granting":  to_int(raw.get("deggrant")),
                "carnegie_basic":   carnegie,
                "website":          raw.get("webaddr", "").strip(),
                "ein":              raw.get("ein", "").strip() or None,
                "opeid":            raw.get("opeid", "").strip() or None,
                "is_active":        1,
            }
            out_rows.append(row)

        n = upsert_rows(conn, self.TABLE, out_rows, ["unitid"])
        logger.info(f"institution_master: {n} institutions loaded from HD {year}")
        return n


# ---------------------------------------------------------------------------
# Loader Registry & Orchestration
# ---------------------------------------------------------------------------

LOADERS = {
    "INST":  InstitutionMasterLoader,   # Run first
    "IC":    ICLoader,
    "ADM":   ADMLoader,
    "EF":    EFLoader,
    "C":     CompletionsLoader,
    "GR":    GRLoader,
    "SFA":   SFALoader,
    "F":     FinanceLoader,
    "HR":    HRLoader,
    # GR200, OM, E12, AL — add loaders following same pattern
}

# Recommended load order — institution_master must come first
LOAD_ORDER = ["INST", "IC", "ADM", "EF", "C", "GR", "SFA", "F", "HR"]


def load_all(db_path, components=None, years=None):
    """Main orchestration: load all components for all years."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )

    conn = initialize_db(db_path)

    if components is None:
        components = LOAD_ORDER
    if years is None:
        years = list(range(2000, 2025))   # Update annually

    total_rows = 0
    errors = []

    for component in components:
        if component not in LOADERS:
            logger.warning(f"No loader for component: {component}")
            continue

        loader = LOADERS[component]()

        for year in sorted(years):
            try:
                n = loader.load(conn, year)
                total_rows += n
            except Exception as e:
                msg = f"{component} {year}: {e}"
                logger.error(msg)
                logger.debug(traceback.format_exc())
                errors.append(msg)

    logger.info(f"\n{'='*60}")
    logger.info(f"Load complete: {total_rows:,} total rows inserted/updated")
    if errors:
        logger.warning(f"{len(errors)} errors:")
        for e in errors:
            logger.warning(f"  {e}")

    conn.close()
    return total_rows, errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load IPEDS CSV data into the higher-ed database"
    )
    parser.add_argument("--db", required=True,
                        help="Path to SQLite database file")
    parser.add_argument("--component", nargs="+",
                        help=f"Components to load. Choices: {', '.join(LOAD_ORDER)}")
    parser.add_argument("--year", nargs="+", type=int,
                        help="Specific years to load (fall start year, e.g., 2022)")

    args = parser.parse_args()

    total, errors = load_all(
        db_path    = args.db,
        components = args.component,
        years      = args.year
    )

    exit(1 if errors else 0)
