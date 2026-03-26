#!/usr/bin/env python3
"""
ingestion/990/parser.py
------------------------
Parses IRS Form 990 XML files using IRSx and extracts:
  - Part VIII  — Statement of Revenue
  - Part IX    — Statement of Functional Expenses
  - Part X     — Balance Sheet
  - Part XI    — Reconciliation of Net Assets

Stores results in 990_data.db via the schema in schema/990_schema.sql.

Usage:
    # Parse all XML files in default directory
    python3 ingestion/990/parser.py --db data/databases/990_data.db

    # Parse specific XML files
    python3 ingestion/990/parser.py --db data/databases/990_data.db \\
        --xml data/raw/990_xml/202301329349306830_public.xml

    # Dry run — parse and print without writing to DB
    python3 ingestion/990/parser.py --db data/databases/990_data.db \\
        --xml data/raw/990_xml/202301329349306830_public.xml --dry-run

Ground truth (Babson, TAX_PERIOD=202206, FY ending June 2022):
    CYTotalRevenueAmt = $397,619,450  (Part I summary / Part VIII total)
"""

import argparse
import logging
import sqlite3
from pathlib import Path

from irsx.filing import Filing

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "990_schema.sql"
XML_DIR     = Path(__file__).resolve().parents[2] / "data" / "raw" / "990_xml"


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        logger.warning("990_schema.sql not found — tables may not exist")


# ---------------------------------------------------------------------------
# IRSx extraction helpers
# ---------------------------------------------------------------------------

def _int(val) -> int | None:
    """Cast IRSx numeric string to int, return None on failure."""
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _grp(d: dict | None, key: str) -> int | None:
    """Extract TotalFunctionalExpensesGrp-style nested ints."""
    if not isinstance(d, dict):
        return None
    return _int(d.get(key))


def extract_filing(xml_path: Path) -> dict | None:
    """
    Parse one Form 990 XML with IRSx and return a flat dict of field values.
    Returns None if the filing cannot be parsed or is not a full Form 990.
    """
    # Derive OBJECT_ID from filename (strip _public.xml)
    stem = xml_path.stem  # e.g. 202301329349306830_public
    object_id = stem.replace("_public", "")

    try:
        f = Filing(object_id, filepath=str(xml_path))
        f.process()
    except Exception as exc:
        logger.error(f"IRSx failed on {xml_path.name}: {exc}")
        return None

    if "IRS990" not in f.list_schedules():
        logger.warning(f"{xml_path.name}: no IRS990 schedule (form type: {f.get_type()})")
        return None

    s = f.get_schedule("IRS990")
    hdr = f.get_schedule("ReturnHeader990x") or {}

    ein = str(f.get_ein()).zfill(9)

    # Tax period → fiscal_year_end
    # TAX_PERIOD in index is YYYYMM (period ending month).
    # fiscal_year_end = calendar year in which the FY ends.
    tax_period_end = hdr.get("TaxPeriodEndDt", "")  # e.g. "2022-06-30"
    if tax_period_end:
        fiscal_year_end = int(tax_period_end[:4])
    else:
        fiscal_year_end = None

    org_name = hdr.get("Filer", {}).get("BusinessName", {}).get("BusinessNameLine1Txt") \
               or s.get("PrincipalOfficerNm", "")

    # ------------------------------------------------------------------
    # Part VIII — Statement of Revenue
    # ------------------------------------------------------------------
    rev_grp = s.get("TotalRevenueGrp") or {}
    total_revenue           = _int(s.get("CYTotalRevenueAmt"))
    contributions_grants    = _int(s.get("TotalContributionsAmt"))
    program_service_revenue = _int(s.get("TotalProgramServiceRevenueAmt"))
    investment_income       = _grp(s.get("InvestmentIncomeGrp"), "TotalRevenueColumnAmt")
    net_gain_investments    = _grp(s.get("NetGainOrLossInvestmentsGrp"), "TotalRevenueColumnAmt")
    other_revenue           = _int(s.get("CYOtherRevenueAmt"))

    # ------------------------------------------------------------------
    # Part IX — Statement of Functional Expenses
    # ------------------------------------------------------------------
    total_expenses          = _int(s.get("CYTotalExpensesAmt"))
    total_func_exp_grp      = s.get("TotalFunctionalExpensesGrp") or {}
    total_program_exp       = _int(s.get("TotalProgramServiceExpensesAmt"))
    salaries_comp           = _grp(s.get("CompCurrentOfcrDirectorsGrp"), "TotalAmt") \
                              or _int(s.get("CYSalariesCompEmpBnftPaidAmt"))
    other_salaries_wages    = _grp(s.get("OtherSalariesAndWagesGrp"), "TotalAmt")
    pension_contributions   = _grp(s.get("PensionPlanContributionsGrp"), "TotalAmt")
    other_employee_benefits = _grp(s.get("OtherEmployeeBenefitsGrp"), "TotalAmt")
    payroll_taxes           = _grp(s.get("PayrollTaxesGrp"), "TotalAmt")
    depreciation            = _grp(s.get("DepreciationDepletionGrp"), "TotalAmt")
    interest_exp            = _grp(s.get("InterestGrp"), "TotalAmt")
    occupancy               = _grp(s.get("OccupancyGrp"), "TotalAmt")
    total_func_exp          = _grp(total_func_exp_grp, "TotalAmt")

    # ------------------------------------------------------------------
    # Part X — Balance Sheet
    # ------------------------------------------------------------------
    total_assets_boy        = _int(s.get("TotalAssetsBOYAmt"))
    total_assets_eoy        = _int(s.get("TotalAssetsEOYAmt"))
    total_liab_boy          = _int(s.get("TotalLiabilitiesBOYAmt"))
    total_liab_eoy          = _int(s.get("TotalLiabilitiesEOYAmt"))
    net_assets_boy          = _int(s.get("NetAssetsOrFundBalancesBOYAmt"))
    net_assets_eoy          = _int(s.get("NetAssetsOrFundBalancesEOYAmt"))
    cash_and_equiv          = _grp(s.get("CashNonInterestBearingGrp"), "EOYAmt")
    investments_securities  = _grp(s.get("InvestmentsPubTradedSecGrp"), "EOYAmt")
    land_bldg_equip_net     = _grp(s.get("LandBldgEquipBasisNetGrp"), "EOYAmt")

    # ------------------------------------------------------------------
    # Part XI — Reconciliation of Net Assets
    # ------------------------------------------------------------------
    net_unrlzd_gains        = _int(s.get("NetUnrlzdGainsLossesInvstAmt"))
    other_changes           = _int(s.get("OtherChangesInNetAssetsAmt"))
    reconciliation_rev_exp  = _int(s.get("ReconcilationRevenueExpnssAmt"))

    # ------------------------------------------------------------------
    # Part I — Organizational Summary
    # ------------------------------------------------------------------
    # f.get_type() returns IRSx-prefixed values like 'IRS990', 'IRS990EZ', 'IRS990PF'.
    # Normalize to plain form type strings for cross-source consistency.
    _raw_type = f.get_type() or ""
    form_type = _raw_type.replace("IRS", "") if _raw_type.startswith("IRS") else _raw_type
    total_employee_count    = _int(s.get("TotalEmployeeCnt"))

    return {
        "object_id":              object_id,
        "ein":                    ein,
        "fiscal_year_end":        fiscal_year_end,
        "org_name":               org_name,
        # Part VIII
        "total_revenue":          total_revenue,
        "contributions_grants":   contributions_grants,
        "program_service_revenue":program_service_revenue,
        "investment_income":      investment_income,
        "net_gain_investments":   net_gain_investments,
        "other_revenue":          other_revenue,
        # Part IX
        "total_expenses":         total_expenses,
        "total_program_expenses": total_program_exp,
        "salaries_comp":          salaries_comp,
        "other_salaries_wages":   other_salaries_wages,
        "pension_contributions":  pension_contributions,
        "other_employee_benefits":other_employee_benefits,
        "payroll_taxes":          payroll_taxes,
        "depreciation":           depreciation,
        "interest_expense":       interest_exp,
        "occupancy":              occupancy,
        "total_functional_expenses": total_func_exp,
        # Part X
        "total_assets_boy":       total_assets_boy,
        "total_assets_eoy":       total_assets_eoy,
        "total_liabilities_boy":  total_liab_boy,
        "total_liabilities_eoy":  total_liab_eoy,
        "net_assets_boy":         net_assets_boy,
        "net_assets_eoy":         net_assets_eoy,
        "cash_and_equivalents":   cash_and_equiv,
        "investments_securities": investments_securities,
        "land_bldg_equip_net":    land_bldg_equip_net,
        # Part XI
        "net_unrealized_gains":   net_unrlzd_gains,
        "other_changes_net_assets":other_changes,
        "reconciliation_surplus": reconciliation_rev_exp,
        # Part I — Organizational Summary
        "form_type":              form_type,
        "total_employee_count":   total_employee_count,
    }


# ---------------------------------------------------------------------------
# Print helper
# ---------------------------------------------------------------------------

def print_filing(row: dict) -> None:
    print(f"\n{'='*65}")
    print(f"  {row.get('org_name','?')}  (EIN {row.get('ein','?')})")
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
            ("Total expenses",            "total_expenses"),
            ("  Program service expenses","total_program_expenses"),
            ("  Officer/director comp",   "salaries_comp"),
            ("  Other salaries & wages",  "other_salaries_wages"),
            ("  Pension contributions",   "pension_contributions"),
            ("  Other employee benefits", "other_employee_benefits"),
            ("  Payroll taxes",           "payroll_taxes"),
            ("  Depreciation",            "depreciation"),
            ("  Interest",                "interest_expense"),
            ("  Occupancy",               "occupancy"),
            ("  Total functional exp",    "total_functional_expenses"),
        ]),
        ("PART X — Balance Sheet (EOY)", [
            ("Total assets (EOY)",        "total_assets_eoy"),
            ("Total liabilities (EOY)",   "total_liabilities_eoy"),
            ("Net assets (EOY)",          "net_assets_eoy"),
            ("  Cash & equivalents",      "cash_and_equivalents"),
            ("  Investments (securities)","investments_securities"),
            ("  Land/bldg/equip (net)",   "land_bldg_equip_net"),
        ]),
        ("PART XI — Net Asset Reconciliation", [
            ("Revenue less expenses",     "reconciliation_surplus"),
            ("Net unrealized gains",      "net_unrealized_gains"),
            ("Other changes",             "other_changes_net_assets"),
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


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

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
    form_type, total_employee_count
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
    :form_type, :total_employee_count
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
    form_type=excluded.form_type,
    total_employee_count=excluded.total_employee_count
"""


def upsert_filing(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(UPSERT_SQL, row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Parse Form 990 XML with IRSx")
    parser.add_argument("--db",  required=True, help="Path to 990_data.db")
    parser.add_argument("--xml", nargs="+",
                        help="Specific XML file(s); default: all in data/raw/990_xml/")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print parsed values without writing to DB")
    args = parser.parse_args()

    xml_files: list[Path]
    if args.xml:
        xml_files = [Path(p) for p in args.xml]
    else:
        xml_files = sorted(XML_DIR.glob("*_public.xml"))

    if not xml_files:
        logger.error("No XML files found")
        return

    conn = sqlite3.connect(args.db)
    if not args.dry_run:
        init_db(conn)

    parsed, written, errors = 0, 0, 0
    for xml_path in xml_files:
        logger.info(f"Parsing {xml_path.name} …")
        row = extract_filing(xml_path)
        if row is None:
            errors += 1
            continue
        parsed += 1
        print_filing(row)
        if not args.dry_run:
            upsert_filing(conn, row)
            conn.commit()
            written += 1

    conn.close()
    logger.info(f"Done — {parsed} parsed, {written} written, {errors} errors")


if __name__ == "__main__":
    main()
