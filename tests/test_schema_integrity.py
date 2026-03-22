#!/usr/bin/env python3
"""
tests/test_schema_integrity.py
------------------------------
Schema integrity checks for ipeds_data.db.

Checks:
  1. No orphaned rows (unitid FK violations in each child table)
  2. No NULL unitids in any table
  3. GASB/FASB row counts balance in ipeds_finance
  4. Year coverage gaps — flag years missing from each table relative to its expected range
  5. Babson spot check — known values from confirmed 2022/2023 data

Exit 0 if all checks pass. Exit 1 if any fail.
"""

import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "databases", "ipeds_data.db")

# Babson College UNITID = 164580
BABSON_UNITID = 164580

# Known-good values confirmed during 2022/2023 build
BABSON_CHECKS = [
    # (description, sql, expected_value)
    (
        "Babson 2023 enrtot",
        "SELECT enrtot FROM ipeds_ef WHERE unitid=164580 AND survey_year=2023",
        3943,
    ),
    (
        "Babson 2022 enrtot",
        "SELECT enrtot FROM ipeds_ef WHERE unitid=164580 AND survey_year=2022",
        3989,
    ),
    (
        "Babson 2023 roomboard_oncampus",
        "SELECT roomboard_oncampus FROM ipeds_ic WHERE unitid=164580 AND survey_year=2023",
        18852,
    ),
    (
        "Babson 2022 roomboard_oncampus",
        "SELECT roomboard_oncampus FROM ipeds_ic WHERE unitid=164580 AND survey_year=2022",
        17920,
    ),
]

CHILD_TABLES = [
    "ipeds_ic",
    "ipeds_adm",
    "ipeds_ef",
    "ipeds_completions",
    "ipeds_gr",
    "ipeds_sfa",
    "ipeds_finance",
    "ipeds_hr",
]

# Expected year ranges per table (inclusive; gaps within these are flagged)
EXPECTED_YEAR_RANGES = {
    "ipeds_ic":          (2000, 2024),
    "ipeds_adm":         (2014, 2023),  # ADM standalone from 2014 only
    "ipeds_ef":          (2000, 2023),
    "ipeds_completions": (2000, 2024),
    "ipeds_gr":          (2000, 2023),
    "ipeds_sfa":         (2001, 2022),  # SFA 2023 not yet released
    "ipeds_finance":     (2000, 2022),  # Finance 2023 not yet released
    "ipeds_hr":          (2012, 2023),  # HR files start 2012 on NCES
}


def run_checks(conn):
    failures = []
    warnings = []

    # ------------------------------------------------------------------
    # 1. Orphaned rows
    # ------------------------------------------------------------------
    print("=== 1. Orphaned Row Check (unitid not in institution_master) ===")
    for tbl in CHILD_TABLES:
        n = conn.execute(
            f"SELECT count(*) FROM {tbl} "
            f"WHERE unitid NOT IN (SELECT unitid FROM institution_master)"
        ).fetchone()[0]
        status = "OK" if n == 0 else f"FAIL — {n:,} orphaned rows"
        print(f"  {tbl}: {status}")
        if n > 0:
            failures.append(f"{tbl}: {n:,} orphaned rows")

    # ------------------------------------------------------------------
    # 2. NULL unitids
    # ------------------------------------------------------------------
    print()
    print("=== 2. NULL unitid Check ===")
    all_tables = ["institution_master"] + CHILD_TABLES
    for tbl in all_tables:
        n = conn.execute(f"SELECT count(*) FROM {tbl} WHERE unitid IS NULL").fetchone()[0]
        status = "OK" if n == 0 else f"FAIL — {n:,} NULL unitids"
        print(f"  {tbl}: {status}")
        if n > 0:
            failures.append(f"{tbl}: {n:,} NULL unitids")

    # ------------------------------------------------------------------
    # 3. GASB/FASB balance
    # ------------------------------------------------------------------
    print()
    print("=== 3. GASB/FASB Balance ===")
    fasb = conn.execute(
        "SELECT count(*) FROM ipeds_finance WHERE reporting_framework='FASB'"
    ).fetchone()[0]
    gasb = conn.execute(
        "SELECT count(*) FROM ipeds_finance WHERE reporting_framework='GASB'"
    ).fetchone()[0]
    unknown = conn.execute(
        "SELECT count(*) FROM ipeds_finance "
        "WHERE reporting_framework NOT IN ('FASB','GASB') OR reporting_framework IS NULL"
    ).fetchone()[0]
    print(f"  FASB: {fasb:,}")
    print(f"  GASB: {gasb:,}")
    print(f"  Unknown/NULL: {unknown}")
    if fasb != gasb:
        failures.append(f"Finance imbalance: FASB={fasb:,} vs GASB={gasb:,}")
        print("  FAIL: counts do not balance")
    else:
        print("  OK: balanced")
    if unknown > 0:
        failures.append(f"Finance: {unknown} rows with unknown/NULL reporting_framework")

    # ------------------------------------------------------------------
    # 4. Year coverage gaps
    # ------------------------------------------------------------------
    print()
    print("=== 4. Year Coverage Gaps ===")
    for tbl, (yr_min, yr_max) in EXPECTED_YEAR_RANGES.items():
        present = {
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT survey_year FROM {tbl} "
                f"WHERE survey_year BETWEEN {yr_min} AND {yr_max}"
            ).fetchall()
        }
        expected = set(range(yr_min, yr_max + 1))
        missing = sorted(expected - present)
        if not missing:
            print(f"  {tbl} ({yr_min}–{yr_max}): OK")
        else:
            print(f"  {tbl} ({yr_min}–{yr_max}): WARNING — missing years {missing}")
            warnings.append(f"{tbl}: missing years {missing}")

    # ------------------------------------------------------------------
    # 5. Babson spot check
    # ------------------------------------------------------------------
    print()
    print("=== 5. Babson Spot Check (UNITID 164580) ===")

    # Confirm Babson exists in institution_master
    babson_name = conn.execute(
        "SELECT institution_name FROM institution_master WHERE unitid=?", (BABSON_UNITID,)
    ).fetchone()
    if not babson_name:
        failures.append("Babson (164580) missing from institution_master")
        print("  institution_master: FAIL — Babson not found")
    else:
        print(f"  institution_master: OK — '{babson_name[0]}'")

    for desc, sql, expected in BABSON_CHECKS:
        row = conn.execute(sql).fetchone()
        actual = row[0] if row else None
        if actual == expected:
            print(f"  {desc}: OK ({actual:,})")
        else:
            print(f"  {desc}: FAIL — expected {expected:,}, got {actual}")
            failures.append(f"{desc}: expected {expected}, got {actual}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    if not failures and not warnings:
        print("ALL CHECKS PASSED")
    else:
        if warnings:
            print(f"WARNINGS ({len(warnings)}):")
            for w in warnings:
                print(f"  ! {w}")
        if failures:
            print(f"FAILURES ({len(failures)}):")
            for f in failures:
                print(f"  x {f}")

    return len(failures)


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    try:
        n_failures = run_checks(conn)
    finally:
        conn.close()

    sys.exit(1 if n_failures > 0 else 0)


if __name__ == "__main__":
    main()
