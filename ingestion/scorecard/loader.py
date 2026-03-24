#!/usr/bin/env python3
"""
ingestion/scorecard/loader.py
------------------------------
Loads College Scorecard institution-level and program-level data into scorecard_data.db.

Institution load strategy: paginate the full Scorecard with per_page=100.
  - Total ~6,300 institutions → ~64 API requests (not one per institution).
  - Dramatically reduces API usage vs. per-UNITID fetching.
  - Rows not in institution_master are still loaded; use JOIN to filter.

Usage:
    # Full institution load (default — paginate all Scorecard institutions)
    python3 ingestion/scorecard/loader.py --db data/databases/scorecard_data.db

    # Load specific UNITIDs only
    python3 ingestion/scorecard/loader.py --db data/databases/scorecard_data.db \
        --unitid 164580 164739 166027

    # Program-level load for 2014-present
    python3 ingestion/scorecard/loader.py --db data/databases/scorecard_data.db \
        --programs --start-year 2014

    # Dry run — print rows without writing
    python3 ingestion/scorecard/loader.py --db data/databases/scorecard_data.db \
        --unitid 164580 --dry-run

Environment:
    SCORECARD_API_KEY — required; set in .env
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

BASE_URL    = "https://api.data.gov/ed/collegescorecard/v1/schools.json"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "scorecard_schema.sql"

# ---------------------------------------------------------------------------
# Field maps
# ---------------------------------------------------------------------------

INST_FIELD_MAP = {
    "latest.student.size":                                       "student_size",
    "latest.student.enrollment.undergrad_12_month":              "enroll_undergrad",
    "latest.student.enrollment.grad_12_month":                   "enroll_grad",
    "latest.cost.tuition.in_state":                              "tuition_instate",
    "latest.cost.tuition.out_of_state":                          "tuition_outstate",
    "latest.cost.avg_net_price.public":                          "avg_net_price_pub",
    "latest.cost.avg_net_price.private":                         "avg_net_price_priv",
    "latest.cost.net_price.public.by_income_level.0-30000":      "np_pub_0_30k",
    "latest.cost.net_price.public.by_income_level.30001-48000":  "np_pub_30_48k",
    "latest.cost.net_price.public.by_income_level.48001-75000":  "np_pub_48_75k",
    "latest.cost.net_price.public.by_income_level.75001-110000": "np_pub_75_110k",
    "latest.cost.net_price.public.by_income_level.110001-plus":  "np_pub_110k_plus",
    "latest.cost.net_price.private.by_income_level.0-30000":     "np_priv_0_30k",
    "latest.cost.net_price.private.by_income_level.30001-48000": "np_priv_30_48k",
    "latest.cost.net_price.private.by_income_level.48001-75000": "np_priv_48_75k",
    "latest.cost.net_price.private.by_income_level.75001-110000":"np_priv_75_110k",
    "latest.cost.net_price.private.by_income_level.110001-plus": "np_priv_110k_plus",
    "latest.aid.pell_grant_rate":                                "pell_grant_rate",
    "latest.aid.federal_loan_rate":                              "federal_loan_rate",
    "latest.aid.median_debt.completers.overall":                 "median_debt",
    "latest.completion.completion_rate_4yr_150nt":               "completion_rate_4yr",
    "latest.completion.completion_rate_less_than_4yr_150nt":     "completion_rate_2yr",
    "latest.earnings.6_yrs_after_entry.median":                  "earnings_6yr_median",
    "latest.earnings.10_yrs_after_entry.median":                 "earnings_10yr_median",
    "latest.repayment.3_yr_repayment.overall":                   "repayment_3yr",
}

INST_FIELDS = "id," + ",".join(INST_FIELD_MAP.keys())

# Program-level fields — nested arrays per institution (latest data only)
# Field name is cip_4_digit (underscore), not cip_4digit.
# Year-prefixed access (e.g. 2022.programs.*) returns HTTP 500 — unsupported.
PROG_FIELDS = ",".join([
    "id",
    "programs.cip_4_digit.code",
    "programs.cip_4_digit.title",
    "programs.cip_4_digit.credential.level",
    "programs.cip_4_digit.earnings.highest.1_yr.overall_median_earnings",
    "programs.cip_4_digit.earnings.highest.2_yr.overall_median_earnings",
    "programs.cip_4_digit.debt.staff_grad_plus.all.eval_inst.median",
    "programs.cip_4_digit.debt.staff_grad_plus.all.eval_inst.average",
    "programs.cip_4_digit.debt.staff_grad_plus.all.all_inst.median",
    "programs.cip_4_digit.counts.ipeds_awards1",
])

FALLBACK_DATA_YEAR = 2023


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def upsert_rows(conn: sqlite3.Connection, table: str, rows: list[dict],
                pk: list[str]) -> int:
    if not rows:
        return 0
    cols  = list(rows[0].keys())
    ph    = ", ".join("?" for _ in cols)
    upd   = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in pk)
    sql   = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph}) "
             f"ON CONFLICT({', '.join(pk)}) DO UPDATE SET {upd}")
    conn.executemany(sql, [list(r.values()) for r in rows])
    return len(rows)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _get(session: requests.Session, api_key: str, params: dict,
         retries: int = 4) -> dict:
    params = {**params, "api_key": api_key}
    delay = 2.0
    for attempt in range(retries):
        try:
            resp = session.get(BASE_URL, params=params, timeout=20)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                logger.warning(f"Rate limited — sleeping {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            # Mask API key in logged error messages
            safe_msg = str(e).replace(api_key, "***")
            if attempt == retries - 1:
                raise requests.RequestException(safe_msg) from None
            logger.warning(f"Request error ({safe_msg}) — retry in {delay}s")
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("Max retries exceeded")


# ---------------------------------------------------------------------------
# Institution load
# ---------------------------------------------------------------------------

def _api_to_inst_row(result: dict) -> dict:
    row = {"unitid": result["id"], "data_year": FALLBACK_DATA_YEAR}
    for api_field, col in INST_FIELD_MAP.items():
        row[col] = result.get(api_field)
    return row


def load_institutions_paginated(conn: sqlite3.Connection, api_key: str,
                                 dry_run: bool = False) -> int:
    """Fetch all Scorecard institutions via per_page=100 pagination."""
    session = requests.Session()
    session.headers["Accept"] = "application/json"

    page, per_page, total_loaded = 0, 100, 0

    # First call to get total
    data = _get(session, api_key, {"fields": INST_FIELDS, "per_page": per_page, "page": 0})
    total = data["metadata"]["total"]
    pages = -(-total // per_page)
    logger.info(f"Scorecard: {total:,} institutions, {pages} pages")

    results = data.get("results", [])
    rows = [_api_to_inst_row(r) for r in results]
    if not dry_run:
        upsert_rows(conn, "scorecard_institution", rows, ["unitid", "data_year"])
        conn.commit()
    total_loaded += len(rows)
    logger.info(f"  Page 0/{pages-1}: {len(rows)} rows")

    for page in range(1, pages):
        time.sleep(0.2)   # ~300 req/min well under 1,000/hr limit
        data = _get(session, api_key,
                    {"fields": INST_FIELDS, "per_page": per_page, "page": page})
        results = data.get("results", [])
        if not results:
            break
        rows = [_api_to_inst_row(r) for r in results]
        if not dry_run:
            upsert_rows(conn, "scorecard_institution", rows, ["unitid", "data_year"])
            conn.commit()
        total_loaded += len(rows)
        if page % 10 == 0 or page == pages - 1:
            logger.info(f"  Page {page}/{pages-1}: {total_loaded:,} rows so far")

    return total_loaded


def load_institutions_by_unitid(conn: sqlite3.Connection, api_key: str,
                                 unitids: list[int], dry_run: bool = False) -> int:
    """Fetch specific institutions by UNITID (one request each)."""
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    loaded, not_found = 0, []

    for i, uid in enumerate(unitids):
        data = _get(session, api_key, {"id": uid, "fields": INST_FIELDS})
        results = data.get("results", [])
        if not results:
            not_found.append(uid)
            continue
        row = _api_to_inst_row(results[0])
        if dry_run:
            logger.info(f"  DRY RUN {uid}: {row}")
        else:
            upsert_rows(conn, "scorecard_institution", [row], ["unitid", "data_year"])
        loaded += 1
        if i < len(unitids) - 1:
            time.sleep(0.15)

    if not dry_run:
        conn.commit()
    if not_found:
        logger.info(f"  Not found: {not_found}")
    return loaded


# ---------------------------------------------------------------------------
# Program load
# ---------------------------------------------------------------------------

def load_programs(conn: sqlite3.Connection, api_key: str,
                  start_year: int = 2014, dry_run: bool = False) -> int:
    """
    Load field-of-study data by paginating all Scorecard institutions (latest only).
    Year-prefixed field access is not supported by the API (returns HTTP 500).
    All rows are loaded with data_year = FALLBACK_DATA_YEAR.
    --start-year is accepted for CLI compatibility but has no effect on field selection.
    """
    session = requests.Session()
    session.headers["Accept"] = "application/json"

    data = _get(session, api_key,
                {"fields": PROG_FIELDS, "per_page": 100, "page": 0})
    total  = data["metadata"]["total"]
    pages  = -(-total // 100)
    logger.info(f"Program load: {total:,} institutions, {pages} pages (latest data only)")

    def _extract(results: list) -> list[dict]:
        rows = []
        for r in results:
            uid   = r.get("id")
            progs = r.get("latest.programs.cip_4_digit") or []
            if not isinstance(progs, list):
                continue
            for p in progs:
                if not p:
                    continue
                code = p.get("code")
                cred_raw = p.get("credential")
                cred = cred_raw.get("level") if isinstance(cred_raw, dict) else None
                if not code or cred is None:
                    continue
                earn = p.get("earnings") or {}
                highest = earn.get("highest") or {} if isinstance(earn, dict) else {}
                debt_d = p.get("debt") or {}
                sgp   = (debt_d.get("staff_grad_plus") or {}) if isinstance(debt_d, dict) else {}
                sgp_all = (sgp.get("all") or {}) if isinstance(sgp, dict) else {}
                eval_inst = (sgp_all.get("eval_inst") or {}) if isinstance(sgp_all, dict) else {}
                all_inst  = (sgp_all.get("all_inst")  or {}) if isinstance(sgp_all, dict) else {}
                counts = p.get("counts") or {}
                rows.append({
                    "unitid":            uid,
                    "data_year":         FALLBACK_DATA_YEAR,
                    "cip_code":          str(code),
                    "cip_title":         p.get("title"),
                    "credential_level":  cred,
                    "earnings_1yr_median": (highest.get("1_yr") or {}).get("overall_median_earnings"),
                    "earnings_2yr_median": (highest.get("2_yr") or {}).get("overall_median_earnings"),
                    "debt_inst_median":  eval_inst.get("median"),
                    "debt_inst_avg":     eval_inst.get("average"),
                    "debt_natl_median":  all_inst.get("median"),
                    "n_students":        counts.get("ipeds_awards1") if isinstance(counts, dict) else None,
                })
        return rows

    total_loaded = 0
    rows = _extract(data.get("results", []))
    if not dry_run and rows:
        upsert_rows(conn, "scorecard_programs", rows,
                    ["unitid", "data_year", "cip_code", "credential_level"])
        conn.commit()
    total_loaded += len(rows)
    logger.info(f"  Page 0/{pages-1}: {total_loaded:,} program rows")

    for pg in range(1, pages):
        time.sleep(0.2)
        data = _get(session, api_key,
                    {"fields": PROG_FIELDS, "per_page": 100, "page": pg})
        results = data.get("results", [])
        if not results:
            break
        rows = _extract(results)
        if not dry_run and rows:
            upsert_rows(conn, "scorecard_programs", rows,
                        ["unitid", "data_year", "cip_code", "credential_level"])
            conn.commit()
        total_loaded += len(rows)
        if pg % 10 == 0 or pg == pages - 1:
            logger.info(f"  Page {pg}/{pages-1}: {total_loaded:,} program rows so far")

    return total_loaded


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Load College Scorecard into SQLite")
    parser.add_argument("--db", required=True)
    parser.add_argument("--unitid", type=int, nargs="+",
                        help="Specific UNITIDs (omit for full paginated load)")
    parser.add_argument("--programs", action="store_true",
                        help="Load program-level data instead of institution-level")
    parser.add_argument("--start-year", type=int, default=2014,
                        help="First year for program load (default: 2014)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("SCORECARD_API_KEY")
    if not api_key:
        sys.exit("ERROR: SCORECARD_API_KEY not set in .env")

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    init_db(conn)

    if args.programs:
        logger.info("Starting program-level load ...")
        n = load_programs(conn, api_key,
                          start_year=args.start_year, dry_run=args.dry_run)
        logger.info(f"Program load complete: {n:,} rows")
    elif args.unitid:
        logger.info(f"Loading {len(args.unitid)} specific institutions ...")
        n = load_institutions_by_unitid(conn, api_key, args.unitid,
                                        dry_run=args.dry_run)
        logger.info(f"Done: {n:,} rows upserted")
    else:
        logger.info("Starting full paginated institution load ...")
        n = load_institutions_paginated(conn, api_key, dry_run=args.dry_run)
        logger.info(f"Institution load complete: {n:,} rows")

    conn.close()


if __name__ == "__main__":
    main()
