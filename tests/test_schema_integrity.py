#!/usr/bin/env python3
"""
tests/test_schema_integrity.py
------------------------------
Schema integrity checks for ipeds_data.db.

Checks:
  1.  No orphaned rows (unitid FK violations in each child table)
  2.  No NULL unitids in any table
  3.  GASB/FASB both present in ipeds_finance (counts not required to match — GASB > FASB is normal)
  4.  Year coverage gaps — flag years missing from each table vs. expected range
  5.  NULL enrtot in ipeds_ef — suppresses known gaps (2000–2007),
      flags as failure if NULL rate > 1% in other years
  6.  Validation institution spot check — confirm all five institutions are
      present in institution_master, ipeds_ic (2022), ipeds_ef (2022),
      and ipeds_finance (2016, the most recent year all five reported)
      with non-NULL key fields
  7.  Babson known-good value spot check (confirmed during 2022/2023 build)

Exit 0 if all checks pass (warnings do not count as failures).
Exit 1 if any check fails.

Known gaps (suppressed as failures, reported as info):
  - ipeds_ef enrtot NULL for 2000–2001: pre-2002 EF Part A uses line/section
    column layout instead of efalevel. Loader does not handle old format.
  - ipeds_ef enrtot NULL for 2002–2007: efalevel column introduced in 2002
    but eftotlt (enrollment total) column not introduced until 2008.
    2004–2007 also use uppercase column names. All years require loader fix.
  - ipeds_finance incomplete coverage: NCES FASB/GASB survey participation is
    not universal. Well-known institutions (Babson, Harvard, etc.) are absent
    from NCES Finance submissions for many years. This is source data behavior,
    not a loader bug. Use 2016 for validation (most recent year all five
    validation institutions are present).
  - ipeds_hr starts 2012: NCES does not publish S{year}_SIS.zip before 2012.
  - ipeds_sfa starts 2001: no SFA file for 2000 on NCES.
"""

import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "databases", "ipeds_data.db")

# ---------------------------------------------------------------------------
# Validation institutions
# ---------------------------------------------------------------------------
VALIDATION_INSTITUTIONS = [
    {"name": "Babson College",                          "unitid": 164580, "ein": "042103544"},
    {"name": "Bentley University",                      "unitid": 164739, "ein": "041081650"},
    {"name": "Boston College",                          "unitid": 164924, "ein": "042103545"},
    {"name": "Harvard University",                      "unitid": 166027, "ein": "042103580"},
    {"name": "Massachusetts Institute of Technology",   "unitid": 166683, "ein": "042103594"},
]

# Known-good values confirmed during 2022/2023 build (Babson)
BABSON_UNITID = 164580
BABSON_SPOT_CHECKS = [
    ("Babson 2023 enrtot",            "SELECT enrtot             FROM ipeds_ef WHERE unitid=164580 AND survey_year=2023", 3943),
    ("Babson 2022 enrtot",            "SELECT enrtot             FROM ipeds_ef WHERE unitid=164580 AND survey_year=2022", 3989),
    ("Babson 2023 roomboard_oncampus","SELECT roomboard_oncampus FROM ipeds_ic WHERE unitid=164580 AND survey_year=2023", 18852),
    ("Babson 2022 roomboard_oncampus","SELECT roomboard_oncampus FROM ipeds_ic WHERE unitid=164580 AND survey_year=2022", 17920),
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

# Expected year ranges per table (inclusive). Gaps within are flagged.
EXPECTED_YEAR_RANGES = {
    "ipeds_ic":          (2000, 2024),
    "ipeds_adm":         (2014, 2023),  # ADM standalone from 2014 only
    "ipeds_ef":          (2000, 2023),
    "ipeds_completions": (2000, 2024),
    "ipeds_gr":          (2000, 2023),
    "ipeds_sfa":         (2001, 2022),  # AY 2023-24 not yet released; no 2000 file on NCES
    "ipeds_finance":     (2000, 2022),  # AY 2023-24 not yet released
    "ipeds_hr":          (2012, 2023),  # HR files start 2012 on NCES
}

# EF enrtot NULL gap — years excluded from the NULL enrtot check.
# 2000–2001: old line/section format, no efalevel.
# 2002–2007: efalevel present but eftotlt not yet introduced;
#            2004–2007 additionally use uppercase column names.
# All require loader updates to recover enrollment totals.
EF_ENRTOT_NULL_KNOWN_YEARS = set(range(2000, 2008))  # 2000–2007 inclusive

# Max acceptable NULL enrtot rate in years outside the known gap (0–1 scale)
EF_ENRTOT_NULL_THRESHOLD = 0.01  # 1% — allows for genuine non-reporters

# Survey years for validation institution table checks
VALIDATION_IC_EF_YEAR    = 2022  # All five institutions present in IC and EF
VALIDATION_FINANCE_YEAR  = 2016  # Most recent year all five are in ipeds_finance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _section(title):
    print(f"\n=== {title} ===")


def run_checks(conn):
    failures = []
    warnings = []

    # ------------------------------------------------------------------
    # 1. Orphaned rows
    # ------------------------------------------------------------------
    _section("1. Orphaned Row Check (unitid FK not in institution_master)")
    for tbl in CHILD_TABLES:
        n = conn.execute(
            f"SELECT count(*) FROM {tbl} "
            f"WHERE unitid NOT IN (SELECT unitid FROM institution_master)"
        ).fetchone()[0]
        if n == 0:
            print(f"  {tbl}: OK")
        else:
            print(f"  {tbl}: FAIL — {n:,} orphaned rows")
            failures.append(f"{tbl}: {n:,} orphaned rows")

    # ------------------------------------------------------------------
    # 2. NULL unitids
    # ------------------------------------------------------------------
    _section("2. NULL unitid Check")
    for tbl in ["institution_master"] + CHILD_TABLES:
        n = conn.execute(f"SELECT count(*) FROM {tbl} WHERE unitid IS NULL").fetchone()[0]
        if n == 0:
            print(f"  {tbl}: OK")
        else:
            print(f"  {tbl}: FAIL — {n:,} NULL unitids")
            failures.append(f"{tbl}: {n:,} NULL unitids")

    # ------------------------------------------------------------------
    # 3. GASB/FASB balance
    # ------------------------------------------------------------------
    _section("3. GASB/FASB Coverage (ipeds_finance)")
    fasb    = conn.execute("SELECT count(*) FROM ipeds_finance WHERE reporting_framework='FASB'").fetchone()[0]
    gasb    = conn.execute("SELECT count(*) FROM ipeds_finance WHERE reporting_framework='GASB'").fetchone()[0]
    unknown = conn.execute(
        "SELECT count(*) FROM ipeds_finance "
        "WHERE reporting_framework NOT IN ('FASB','GASB') OR reporting_framework IS NULL"
    ).fetchone()[0]
    print(f"  FASB (private nonprofits): {fasb:,}  |  GASB (public): {gasb:,}  |  Unknown/NULL: {unknown}")
    # GASB >= FASB is expected: more public institutions than private nonprofits report to NCES Finance.
    # Equality check removed — old equality was an artifact of the filename bug (both slots loading F1A).
    if fasb == 0:
        print(f"  FAIL: no FASB rows")
        failures.append(f"ipeds_finance: zero FASB rows")
    elif gasb == 0:
        print(f"  FAIL: no GASB rows")
        failures.append(f"ipeds_finance: zero GASB rows")
    else:
        print(f"  OK: both frameworks present")
    if unknown > 0:
        print(f"  FAIL: {unknown} rows with unknown/NULL reporting_framework")
        failures.append(f"ipeds_finance: {unknown} rows with unknown/NULL reporting_framework")

    # ------------------------------------------------------------------
    # 4. Year coverage gaps
    # ------------------------------------------------------------------
    _section("4. Year Coverage Gaps")
    for tbl, (yr_min, yr_max) in EXPECTED_YEAR_RANGES.items():
        present  = {r[0] for r in conn.execute(
            f"SELECT DISTINCT survey_year FROM {tbl} WHERE survey_year BETWEEN {yr_min} AND {yr_max}"
        ).fetchall()}
        missing = sorted(set(range(yr_min, yr_max + 1)) - present)
        if not missing:
            print(f"  {tbl} ({yr_min}–{yr_max}): OK")
        else:
            print(f"  {tbl} ({yr_min}–{yr_max}): WARNING — missing years {missing}")
            warnings.append(f"{tbl}: missing years {missing}")

    # ------------------------------------------------------------------
    # 5. NULL enrtot check (outside known 2000–2007 gap)
    # ------------------------------------------------------------------
    known_str = ",".join(str(y) for y in sorted(EF_ENRTOT_NULL_KNOWN_YEARS))
    _section(f"5. NULL enrtot in ipeds_ef (known gap: {min(EF_ENRTOT_NULL_KNOWN_YEARS)}–{max(EF_ENRTOT_NULL_KNOWN_YEARS)}; threshold >{EF_ENRTOT_NULL_THRESHOLD*100:.0f}%)")
    rows = conn.execute(f"""
        SELECT survey_year,
               count(*) as total,
               sum(case when enrtot is null then 1 else 0 end) as null_count
        FROM ipeds_ef
        WHERE survey_year NOT IN ({known_str})
        GROUP BY survey_year
        HAVING null_count > 0
        ORDER BY survey_year
    """).fetchall()
    any_issue = False
    for yr, total, null_n in rows:
        rate = null_n / total if total else 0
        if rate > EF_ENRTOT_NULL_THRESHOLD:
            print(f"  FAIL — {yr}: {null_n:,}/{total:,} NULL enrtot ({rate*100:.1f}%)")
            failures.append(f"ipeds_ef {yr}: {null_n:,} rows ({rate*100:.1f}%) with unexpected NULL enrtot")
            any_issue = True
        else:
            print(f"  WARN — {yr}: {null_n}/{total} NULL enrtot ({rate*100:.2f}%) — within threshold")
            warnings.append(f"ipeds_ef {yr}: {null_n} rows with NULL enrtot (within {EF_ENRTOT_NULL_THRESHOLD*100:.0f}% threshold)")
    if not any_issue and not rows:
        print(f"  OK — no unexpected NULL enrtot outside known gap")

    # ------------------------------------------------------------------
    # 6. Validation institution spot check
    # ------------------------------------------------------------------
    _section(f"6. Validation Institution Spot Check")

    for inst in VALIDATION_INSTITUTIONS:
        uid, name = inst["unitid"], inst["name"]
        print(f"\n  [{uid}] {name}")

        # institution_master
        im_row = conn.execute(
            "SELECT institution_name, state_abbr, control, ein FROM institution_master WHERE unitid=?",
            (uid,)
        ).fetchone()
        if not im_row:
            print(f"    institution_master: FAIL — not found")
            failures.append(f"{name} ({uid}): missing from institution_master")
        else:
            im_name, state, control, ein = im_row
            nulls = [f for f, v in zip(["institution_name","state_abbr","control","ein"],
                                        [im_name, state, control, ein]) if v is None]
            if nulls:
                print(f"    institution_master: FAIL — NULL fields: {nulls}")
                failures.append(f"{name} ({uid}) institution_master NULL: {nulls}")
            else:
                print(f"    institution_master: OK — '{im_name}', {state}, control={control}, EIN={ein}")

        # ipeds_ic
        ic = conn.execute(
            "SELECT tuition_instate, tuition_outstate FROM ipeds_ic WHERE unitid=? AND survey_year=?",
            (uid, VALIDATION_IC_EF_YEAR)
        ).fetchone()
        if not ic:
            print(f"    ipeds_ic {VALIDATION_IC_EF_YEAR}: FAIL — no row")
            failures.append(f"{name} ({uid}): missing from ipeds_ic {VALIDATION_IC_EF_YEAR}")
        else:
            nulls = [f for f, v in zip(["tuition_instate","tuition_outstate"], ic) if v is None]
            if nulls:
                print(f"    ipeds_ic {VALIDATION_IC_EF_YEAR}: WARN — NULL fields: {nulls}")
                warnings.append(f"{name} ({uid}) ipeds_ic {VALIDATION_IC_EF_YEAR} NULL: {nulls}")
            else:
                print(f"    ipeds_ic {VALIDATION_IC_EF_YEAR}: OK — instate=${ic[0]:,}, outstate=${ic[1]:,}")

        # ipeds_ef
        ef = conn.execute(
            "SELECT enrtot FROM ipeds_ef WHERE unitid=? AND survey_year=?",
            (uid, VALIDATION_IC_EF_YEAR)
        ).fetchone()
        if not ef:
            print(f"    ipeds_ef {VALIDATION_IC_EF_YEAR}: FAIL — no row")
            failures.append(f"{name} ({uid}): missing from ipeds_ef {VALIDATION_IC_EF_YEAR}")
        elif ef[0] is None:
            print(f"    ipeds_ef {VALIDATION_IC_EF_YEAR}: FAIL — enrtot is NULL")
            failures.append(f"{name} ({uid}): NULL enrtot in ipeds_ef {VALIDATION_IC_EF_YEAR}")
        else:
            print(f"    ipeds_ef {VALIDATION_IC_EF_YEAR}: OK — enrtot={ef[0]:,}")

        # ipeds_finance — use 2016, most recent year all 5 institutions reported
        fin = conn.execute(
            "SELECT reporting_framework, count(*) FROM ipeds_finance "
            "WHERE unitid=? AND survey_year=? GROUP BY reporting_framework",
            (uid, VALIDATION_FINANCE_YEAR)
        ).fetchall()
        frameworks = {r[0] for r in fin}
        if not fin:
            print(f"    ipeds_finance {VALIDATION_FINANCE_YEAR}: FAIL — no rows")
            failures.append(f"{name} ({uid}): missing from ipeds_finance {VALIDATION_FINANCE_YEAR}")
        else:
            print(f"    ipeds_finance {VALIDATION_FINANCE_YEAR}: OK — frameworks: {sorted(frameworks)}")

    # ------------------------------------------------------------------
    # 7. Babson known-good value spot check
    # ------------------------------------------------------------------
    _section("7. Babson Known-Good Value Spot Check (UNITID 164580)")
    for desc, sql, expected in BABSON_SPOT_CHECKS:
        row = conn.execute(sql).fetchone()
        actual = row[0] if row else None
        if actual == expected:
            print(f"  {desc}: OK ({actual:,})")
        else:
            print(f"  {desc}: FAIL — expected {expected:,}, got {actual}")
            failures.append(f"{desc}: expected {expected:,}, got {actual}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    if not failures and not warnings:
        print("ALL CHECKS PASSED")
    elif not failures:
        print(f"ALL CHECKS PASSED — {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  ! {w}")
    else:
        if warnings:
            print(f"WARNINGS ({len(warnings)}):")
            for w in warnings:
                print(f"  ! {w}")
        print(f"\nFAILURES ({len(failures)}):")
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
