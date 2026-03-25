#!/usr/bin/env python3
"""
ingestion/990/propublica_loader.py
------------------------------------
ProPublica Nonprofit Explorer Mode 2 loader.
Pulls IRS Form 990 filings for FY2012–FY2019 for institutions whose EINs
are provided (or the hardcoded validation set) and loads them into 990_data.db.

Source:
    https://projects.propublica.org/nonprofits/api/v2/organizations/{EIN}.json
    Returns filings_with_data — structured financial fields per filing year.
    No authentication required.

Note: ProPublica does not expose a separate filing-detail endpoint.
The organization endpoint is the only structured data source. The
filings_with_data array contains all available financial fields.

Field mapping: see ingestion/990/field_map.py for explicit source → schema column
documentation.

Usage:
    # Test mode — Babson FY2018 only, no DB write
    python3 ingestion/990/propublica_loader.py --db data/databases/990_data.db \\
        --ein 042103544 --start-year 2018 --end-year 2018 --dry-run

    # Load all five validation institutions FY2012–FY2019
    python3 ingestion/990/propublica_loader.py --db data/databases/990_data.db

    # Single institution
    python3 ingestion/990/propublica_loader.py --db data/databases/990_data.db \\
        --ein 042103580 --start-year 2015 --end-year 2019

Rate limit: 0.2s between requests (~5 req/sec).
ProPublica is a public service — do not increase the rate.
"""

import argparse
import logging
import sqlite3
import time
from pathlib import Path

import importlib.util

import requests


def _load_field_map():
    spec = importlib.util.spec_from_file_location(
        "field_map", Path(__file__).parent / "field_map.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fm = _load_field_map()
PROPUBLICA_DIRECT    = _fm.PROPUBLICA_DIRECT
PROPUBLICA_COMPOSITE = _fm.PROPUBLICA_COMPOSITE

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "990_schema.sql"
ORG_URL     = "https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json"
RATE_LIMIT  = 0.2   # seconds between requests

VALIDATION_EINS = {
    "042103544",   # Babson College
    "041081650",   # Bentley University
    "042103545",   # Trustees of Boston College
    "042103580",   # President and Fellows of Harvard College
    "042103594",   # Massachusetts Institute of Technology
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        logger.warning("990_schema.sql not found — tables may not exist")


UPSERT_SQL = """
INSERT INTO form990_filings (
    object_id, ein, fiscal_year_end, org_name,
    total_revenue, contributions_grants, program_service_revenue,
    investment_income, net_gain_investments, other_revenue,
    total_expenses, total_program_expenses,
    salaries_comp, other_salaries_wages, pension_contributions,
    other_employee_benefits, payroll_taxes, depreciation,
    interest_expense, occupancy, total_functional_expenses,
    total_assets_boy, total_assets_eoy,
    total_liabilities_boy, total_liabilities_eoy,
    net_assets_boy, net_assets_eoy,
    cash_and_equivalents, investments_securities, land_bldg_equip_net,
    net_unrealized_gains, other_changes_net_assets, reconciliation_surplus,
    data_source
) VALUES (
    :object_id, :ein, :fiscal_year_end, :org_name,
    :total_revenue, :contributions_grants, :program_service_revenue,
    :investment_income, :net_gain_investments, :other_revenue,
    :total_expenses, :total_program_expenses,
    :salaries_comp, :other_salaries_wages, :pension_contributions,
    :other_employee_benefits, :payroll_taxes, :depreciation,
    :interest_expense, :occupancy, :total_functional_expenses,
    :total_assets_boy, :total_assets_eoy,
    :total_liabilities_boy, :total_liabilities_eoy,
    :net_assets_boy, :net_assets_eoy,
    :cash_and_equivalents, :investments_securities, :land_bldg_equip_net,
    :net_unrealized_gains, :other_changes_net_assets, :reconciliation_surplus,
    :data_source
)
ON CONFLICT(object_id) DO UPDATE SET
    ein=excluded.ein, fiscal_year_end=excluded.fiscal_year_end,
    org_name=excluded.org_name,
    total_revenue=excluded.total_revenue,
    contributions_grants=excluded.contributions_grants,
    program_service_revenue=excluded.program_service_revenue,
    investment_income=excluded.investment_income,
    net_gain_investments=excluded.net_gain_investments,
    other_revenue=excluded.other_revenue,
    total_expenses=excluded.total_expenses,
    total_program_expenses=excluded.total_program_expenses,
    salaries_comp=excluded.salaries_comp,
    other_salaries_wages=excluded.other_salaries_wages,
    pension_contributions=excluded.pension_contributions,
    other_employee_benefits=excluded.other_employee_benefits,
    payroll_taxes=excluded.payroll_taxes,
    depreciation=excluded.depreciation,
    interest_expense=excluded.interest_expense,
    occupancy=excluded.occupancy,
    total_functional_expenses=excluded.total_functional_expenses,
    total_assets_boy=excluded.total_assets_boy,
    total_assets_eoy=excluded.total_assets_eoy,
    total_liabilities_boy=excluded.total_liabilities_boy,
    total_liabilities_eoy=excluded.total_liabilities_eoy,
    net_assets_boy=excluded.net_assets_boy,
    net_assets_eoy=excluded.net_assets_eoy,
    cash_and_equivalents=excluded.cash_and_equivalents,
    investments_securities=excluded.investments_securities,
    land_bldg_equip_net=excluded.land_bldg_equip_net,
    net_unrealized_gains=excluded.net_unrealized_gains,
    other_changes_net_assets=excluded.other_changes_net_assets,
    reconciliation_surplus=excluded.reconciliation_surplus,
    data_source=excluded.data_source
"""


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------

def _fetch_org(ein: str, session: requests.Session) -> dict | None:
    """Fetch the ProPublica organization record for one EIN."""
    url = ORG_URL.format(ein=ein)
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error(f"ProPublica fetch failed for EIN {ein}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def _sum_fields(filing: dict, keys: list[str]) -> int | None:
    """
    Sum a list of ProPublica keys from one filing entry.
    Returns None only if ALL keys are absent from the dict.
    0-valued keys are included (0 is a valid reported value).
    """
    vals = [filing[k] for k in keys if k in filing and filing[k] is not None]
    return sum(vals) if vals else None


def map_filing(filing: dict, org_name: str, ein: str) -> dict:
    """
    Map one ProPublica filings_with_data entry to a form990_filings row dict.

    object_id is synthetic: f"PP_{EIN}_{TAX_PERIOD}" — guaranteed not to
    collide with TEOS object_ids (which are all-numeric).

    fiscal_year_end = tax_prd_yr (the calendar year the fiscal year ends).
    """
    tax_prd    = str(filing.get("tax_prd", ""))
    tax_prd_yr = filing.get("tax_prd_yr")

    row: dict = {
        "object_id":               f"PP_{ein}_{tax_prd}",
        "ein":                     ein,
        "fiscal_year_end":         tax_prd_yr,
        "org_name":                org_name,
        "data_source":             "propublica",
        # NULL columns — not available from ProPublica
        "total_expenses":          None,
        "total_program_expenses":  None,
        "pension_contributions":   None,
        "other_employee_benefits": None,
        "depreciation":            None,
        "interest_expense":        None,
        "occupancy":               None,
        "total_assets_boy":        None,
        "total_liabilities_boy":   None,
        "net_assets_boy":          None,
        "cash_and_equivalents":    None,
        "investments_securities":  None,
        "land_bldg_equip_net":     None,
        "net_unrealized_gains":    None,
        "other_changes_net_assets":None,
        "reconciliation_surplus":  None,
    }

    # Direct 1:1 mappings
    for pp_key, col in PROPUBLICA_DIRECT.items():
        row[col] = filing.get(pp_key)

    # Composite mappings
    for col, pp_keys in PROPUBLICA_COMPOSITE.items():
        row[col] = _sum_fields(filing, pp_keys)

    return row


def _revenue_reconciles(row: dict) -> bool:
    """
    Verify: contributions + program_service + investment + gains + other == total.
    Returns True if the sum matches within 1 dollar (rounding tolerance).
    """
    total = row.get("total_revenue")
    if total is None:
        return False
    parts = [
        row.get("contributions_grants")    or 0,
        row.get("program_service_revenue") or 0,
        row.get("investment_income")       or 0,
        row.get("net_gain_investments")    or 0,
        row.get("other_revenue")           or 0,
    ]
    return abs(sum(parts) - total) <= 1


def print_row(row: dict) -> None:
    """Print a mapped row in the same format as parser.print_filing."""
    print(f"\n{'='*65}")
    print(f"  {row.get('org_name','?')}  (EIN {row.get('ein','?')})  [ProPublica]")
    print(f"  Fiscal Year End: {row.get('fiscal_year_end','?')}  "
          f"  Object ID: {row.get('object_id','?')}")
    print(f"{'='*65}")

    sections = [
        ("PART VIII — Revenue", [
            ("Total revenue",            "total_revenue"),
            ("  Contributions & grants", "contributions_grants"),
            ("  Program service revenue","program_service_revenue"),
            ("  Investment income",       "investment_income"),
            ("  Net gain on investments","net_gain_investments"),
            ("  Other revenue",           "other_revenue"),
        ]),
        ("PART IX — Expenses", [
            ("Total functional exp",     "total_functional_expenses"),
            ("  Officer/director comp",  "salaries_comp"),
            ("  Other salaries & wages", "other_salaries_wages"),
            ("  Payroll taxes",          "payroll_taxes"),
        ]),
        ("PART X — Balance Sheet (EOY)", [
            ("Total assets (EOY)",       "total_assets_eoy"),
            ("Total liabilities (EOY)",  "total_liabilities_eoy"),
            ("Net assets (EOY)",         "net_assets_eoy"),
        ]),
    ]
    for section_name, fields in sections:
        print(f"\n  {section_name}")
        for label, key in fields:
            val = row.get(key)
            if val is not None:
                print(f"    {label:<36} ${val:>16,}")
            else:
                print(f"    {label:<36} {'NULL':>17}")

    reconciled = _revenue_reconciles(row)
    print(f"\n  Revenue reconciliation: {'✓ OK' if reconciled else '✗ FAIL'}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def load_ein(conn: sqlite3.Connection | None, ein: str, org_name: str,
             session: requests.Session, start_year: int, end_year: int,
             dry_run: bool) -> tuple[int, int]:
    """
    Load ProPublica filings for one EIN in [start_year, end_year].
    Returns (loaded, skipped) counts.
    """
    data = _fetch_org(ein, session)
    if data is None:
        return 0, 0

    org_name = org_name or (data.get("organization") or {}).get("name", "")
    filings  = data.get("filings_with_data", [])

    loaded, skipped = 0, 0
    for filing in filings:
        yr      = filing.get("tax_prd_yr")
        ftype   = filing.get("formtype")

        # Only full Form 990 (formtype 0) within target year range
        if ftype != 0 or yr is None or not (start_year <= yr <= end_year):
            continue

        row = map_filing(filing, org_name, ein)

        if not _revenue_reconciles(row):
            logger.warning(
                f"  EIN={ein} FY{yr}: revenue does not reconcile — "
                f"sum={sum([row.get(k) or 0 for k in ('contributions_grants','program_service_revenue','investment_income','net_gain_investments','other_revenue')])} "
                f"total={row.get('total_revenue')}"
            )
            skipped += 1
            continue

        print_row(row)

        if not dry_run and conn is not None:
            conn.execute(UPSERT_SQL, row)
            conn.commit()
        loaded += 1

    return loaded, skipped


def run(eins: set[str], start_year: int, end_year: int, db_path: str,
        dry_run: bool = False) -> None:
    conn = None
    if not dry_run:
        conn = sqlite3.connect(db_path)
        init_db(conn)

    session = requests.Session()
    session.headers["User-Agent"] = "project-jenni-990-pipeline/1.0"

    total_loaded = total_skipped = 0
    for i, ein in enumerate(sorted(eins)):
        logger.info(f"Fetching EIN {ein} ({i+1}/{len(eins)}) …")
        loaded, skipped = load_ein(conn, ein, "", session,
                                   start_year, end_year, dry_run)
        total_loaded  += loaded
        total_skipped += skipped
        if i < len(eins) - 1:
            time.sleep(RATE_LIMIT)

    if conn:
        conn.close()

    action = "would load" if dry_run else "loaded"
    logger.info(
        f"Done — {total_loaded} filings {action}, {total_skipped} skipped "
        f"(revenue reconciliation failures)"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Load IRS Form 990 data from ProPublica API (FY2012–FY2019)"
    )
    parser.add_argument("--db", required=True,
                        help="Path to 990_data.db")
    parser.add_argument("--ein", nargs="+",
                        help="EIN(s) to load (default: all 5 validation institutions)")
    parser.add_argument("--start-year", type=int, default=2012,
                        help="First fiscal year to load (default: 2012)")
    parser.add_argument("--end-year", type=int, default=2019,
                        help="Last fiscal year to load (default: 2019)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print mapped rows without writing to DB")
    args = parser.parse_args()

    eins = {e.replace("-", "").strip().zfill(9) for e in args.ein} \
           if args.ein else VALIDATION_EINS

    run(eins, args.start_year, args.end_year, args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
