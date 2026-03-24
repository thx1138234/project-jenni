#!/usr/bin/env python3
"""
ingestion/scorecard/loader.py
------------------------------
Loads College Scorecard institution-level data into scorecard_data.db.

Usage:
    # Initialize schema and load a list of UNITIDs
    python3 ingestion/scorecard/loader.py --db data/databases/scorecard_data.db \
        --unitid 164580 164739 166027 166683

    # Load all UNITIDs present in institution_master (requires ipeds_data.db)
    python3 ingestion/scorecard/loader.py --db data/databases/scorecard_data.db \
        --from-ipeds data/databases/ipeds_data.db

    # Test mode — print rows without writing to DB
    python3 ingestion/scorecard/loader.py --db data/databases/scorecard_data.db \
        --unitid 164580 --dry-run

Environment:
    SCORECARD_API_KEY — required; set in .env
"""

import argparse
import logging
import sqlite3
import time
from pathlib import Path

from api_client import ScorecardClient, DEFAULT_FIELDS

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "scorecard_schema.sql"

# Mapping: API field → (table_column, transform)
# transform is None (keep as-is) or a callable
INST_FIELD_MAP = {
    "latest.student.size":                                      "student_size",
    "latest.student.enrollment.undergrad_12_month":             "enroll_undergrad",
    "latest.student.enrollment.grad_12_month":                  "enroll_grad",
    "latest.cost.tuition.in_state":                             "tuition_instate",
    "latest.cost.tuition.out_of_state":                         "tuition_outstate",
    "latest.cost.avg_net_price.public":                         "avg_net_price_pub",
    "latest.cost.avg_net_price.private":                        "avg_net_price_priv",
    "latest.cost.net_price.public.by_income_level.0-30000":     "np_pub_0_30k",
    "latest.cost.net_price.public.by_income_level.30001-48000": "np_pub_30_48k",
    "latest.cost.net_price.public.by_income_level.48001-75000": "np_pub_48_75k",
    "latest.cost.net_price.public.by_income_level.75001-110000":"np_pub_75_110k",
    "latest.cost.net_price.public.by_income_level.110001-plus": "np_pub_110k_plus",
    "latest.cost.net_price.private.by_income_level.0-30000":    "np_priv_0_30k",
    "latest.cost.net_price.private.by_income_level.30001-48000":"np_priv_30_48k",
    "latest.cost.net_price.private.by_income_level.48001-75000":"np_priv_48_75k",
    "latest.cost.net_price.private.by_income_level.75001-110000":"np_priv_75_110k",
    "latest.cost.net_price.private.by_income_level.110001-plus":"np_priv_110k_plus",
    "latest.aid.pell_grant_rate":                               "pell_grant_rate",
    "latest.aid.federal_loan_rate":                             "federal_loan_rate",
    "latest.aid.median_debt.completers.overall":                "median_debt",
    "latest.completion.completion_rate_4yr_150nt":              "completion_rate_4yr",
    "latest.completion.completion_rate_less_than_4yr_150nt":    "completion_rate_2yr",
    "latest.earnings.6_yrs_after_entry.median":                 "earnings_6yr_median",
    "latest.earnings.10_yrs_after_entry.median":                "earnings_10yr_median",
    "latest.repayment.3_yr_repayment.overall":                  "repayment_3yr",
}

# The Scorecard "latest" data resolves to a specific academic year.
# We fetch this year field to record which year the data represents.
YEAR_FIELD = "latest_cohort_year"   # returned as top-level key in some responses
FALLBACK_DATA_YEAR = 2023           # used when year field is absent


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def api_result_to_row(result: dict) -> dict:
    """Convert a raw API result dict to a scorecard_institution row dict."""
    row = {
        "unitid":    result["id"],
        "data_year": result.get(YEAR_FIELD) or FALLBACK_DATA_YEAR,
    }
    for api_field, col in INST_FIELD_MAP.items():
        row[col] = result.get(api_field)
    return row


def upsert_institution(conn: sqlite3.Connection, row: dict) -> None:
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in ("unitid", "data_year"))
    sql = (
        f"INSERT INTO scorecard_institution ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(unitid, data_year) DO UPDATE SET {updates}"
    )
    conn.execute(sql, list(row.values()))


def load_institutions(
    conn: sqlite3.Connection,
    unitids: list[int],
    client: ScorecardClient,
    sleep_between: float = 0.15,
    dry_run: bool = False,
) -> int:
    loaded = 0
    not_found = []

    for i, uid in enumerate(unitids):
        try:
            result = client.get_institution(uid)
        except Exception as e:
            logger.warning(f"  UNITID {uid}: API error — {e}")
            continue

        if result is None:
            not_found.append(uid)
            logger.debug(f"  UNITID {uid}: not found in Scorecard")
            continue

        row = api_result_to_row(result)
        if dry_run:
            name = result.get("school.name", "?")
            logger.info(f"  DRY RUN [{uid}] {name}: {row}")
        else:
            upsert_institution(conn, row)
            loaded += 1

        if i > 0 and i % 100 == 0:
            if not dry_run:
                conn.commit()
            logger.info(f"  Progress: {i}/{len(unitids)}")

        if i < len(unitids) - 1:
            time.sleep(sleep_between)

    if not dry_run:
        conn.commit()

    if not_found:
        logger.info(f"  Not found in Scorecard ({len(not_found)}): {not_found[:10]}"
                    + (" ..." if len(not_found) > 10 else ""))

    return loaded


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Load College Scorecard data into SQLite")
    parser.add_argument("--db", required=True, help="Path to scorecard_data.db")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--unitid", type=int, nargs="+", help="Specific UNITID(s) to load")
    group.add_argument("--from-ipeds", metavar="IPEDS_DB",
                       help="Load all UNITIDs from institution_master in given IPEDS db")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and print rows without writing to DB")
    args = parser.parse_args()

    # Resolve unitid list
    if args.unitid:
        unitids = args.unitid
    else:
        ipeds = sqlite3.connect(args.from_ipeds)
        unitids = [r[0] for r in ipeds.execute(
            "SELECT DISTINCT unitid FROM institution_master ORDER BY unitid"
        ).fetchall()]
        ipeds.close()
        logger.info(f"Loaded {len(unitids):,} UNITIDs from institution_master")

    # Connect and initialize
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    init_db(conn)

    client = ScorecardClient()

    logger.info(f"Loading {len(unitids):,} institutions into {db_path.name} ...")
    n = load_institutions(conn, unitids, client, dry_run=args.dry_run)
    conn.close()

    if not args.dry_run:
        logger.info(f"Done — {n:,} rows upserted into scorecard_institution")


if __name__ == "__main__":
    main()
