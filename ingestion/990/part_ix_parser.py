#!/usr/bin/env python3
"""
ingestion/990/part_ix_parser.py
---------------------------------
Phase A + B: Parse Form 990 Part IX (Statement of Functional Expenses) —
functional column breakdowns from TEOS/IRSx XML into form990_part_ix.

Phase A (original):
  Line 25 — Total functional expenses: cols B/C/D
  Line 12 — Advertising and promotion: cols B/C/D
  Line 14 — Information technology: cols B/C/D
  Line 11e — Professional fundraising fees: TotalAmt + B/C/D (Phase B)
  Line 11f — Investment management fees: TotalAmt + B/C/D (Phase B)

Phase B (all remaining lines):
  Lines 1–11d, 11g, 13, 15–24 — each with cols B/C/D
  Column names prefixed ln01_ through ln24_ (see schema for full list)

Calculated ratios (Phase A, require form990_filings join):
  prog_services_pct      = total_prog_services / total_functional_expenses
  overhead_ratio         = (total_mgmt_general + total_fundraising_exp) / total_functional_expenses
  fundraising_efficiency = total_fundraising_exp / contributions_grants

ProPublica rows: NULL by design — ProPublica API does not expose column breakdowns.

Usage:
    # Validation institutions only (dry run)
    python3 ingestion/990/part_ix_parser.py --db data/databases/990_data.db \\
        --ein 042103544 041081650 042103545 042103580 042103594 --dry-run

    # Full TEOS universe
    python3 ingestion/990/part_ix_parser.py --db data/databases/990_data.db
"""

import argparse
import logging
import sqlite3
from pathlib import Path

from irsx.filing import Filing

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "990_part_ix_schema.sql"
XML_DIR     = Path(__file__).resolve().parents[2] / "data" / "raw" / "990_xml"


# ---------------------------------------------------------------------------
# Phase B line map: (irsx_schedule_key, column_prefix)
# Each prefix generates _prog, _mgmt, _fundraising columns.
# Lines 12 (Advertising), 14 (IT), 25 (Total) use Phase A legacy names — omitted here.
# ---------------------------------------------------------------------------
_PHASE_B_LINES: list[tuple[str, str]] = [
    ("GrantsToDomesticOrgsGrp",        "ln01_grants_govts"),
    ("GrantsToDomesticIndividualsGrp", "ln02_grants_indiv"),
    ("ForeignGrantsGrp",               "ln03_grants_foreign"),
    ("BenefitsToMembersGrp",           "ln04_member_benefits"),
    ("CompCurrentOfcrDirectorsGrp",    "ln05_officer_comp"),
    ("CompDisqualPersonsGrp",          "ln06_disqualified_comp"),
    ("OtherSalariesAndWagesGrp",       "ln07_other_salaries"),
    ("PensionPlanContributionsGrp",    "ln08_pension"),
    ("OtherEmployeeBenefitsGrp",       "ln09_emp_benefits"),
    ("PayrollTaxesGrp",                "ln10_payroll_taxes"),
    ("FeesForServicesManagementGrp",   "ln11a_fees_mgmt_svc"),
    ("FeesForServicesLegalGrp",        "ln11b_fees_legal"),
    ("FeesForServicesAccountingGrp",   "ln11c_fees_accounting"),
    ("FeesForServicesLobbyingGrp",     "ln11d_fees_lobbying"),
    ("FeesForServicesProfFundraising", "ln11e_fees_prof_fund"),
    ("FeesForSrvcInvstMgmntFeesGrp",  "ln11f_fees_invest_mgmt"),
    ("FeesForServicesOtherGrp",        "ln11g_fees_other"),
    ("OfficeExpensesGrp",              "ln13_office_exp"),
    ("RoyaltiesGrp",                   "ln15_royalties"),
    ("OccupancyGrp",                   "ln16_occupancy"),
    ("TravelGrp",                      "ln17_travel"),
    ("PymtTravelEntrtnmntPubOfclGrp",  "ln18_travel_officials"),
    ("ConferencesMeetingsGrp",         "ln19_conferences"),
    ("InterestGrp",                    "ln20_interest"),
    ("PaymentsToAffiliatesGrp",        "ln21_pmts_affiliates"),
    ("DepreciationDepletionGrp",       "ln22_depreciation"),
    ("InsuranceGrp",                   "ln23_insurance"),
    ("AllOtherExpensesGrp",            "ln24_other_exp"),
]

_PHASE_B_COLS: list[str] = [
    f"{prefix}{suffix}"
    for _, prefix in _PHASE_B_LINES
    for suffix in ("_prog", "_mgmt", "_fundraising")
]

# Phase A column list (fixed legacy names)
_PHASE_A_COLS: list[str] = [
    "object_id", "ein", "fiscal_year_end",
    "total_prog_services", "total_mgmt_general", "total_fundraising_exp",
    "advertising_prog", "advertising_mgmt", "advertising_fundraising",
    "it_prog", "it_mgmt", "it_fundraising",
    "prof_fundraising_fees", "invest_mgmt_fees",
    "prog_services_pct", "overhead_ratio", "fundraising_efficiency",
]

_ALL_COLS: list[str] = _PHASE_A_COLS + _PHASE_B_COLS

# Build UPSERT SQL dynamically from column list
_col_csv        = ", ".join(_ALL_COLS)
_placeholder_csv = ", ".join(f":{c}" for c in _ALL_COLS)
_update_csv     = ",\n    ".join(
    f"{c}=excluded.{c}"
    for c in _ALL_COLS
    if c != "object_id"
)
UPSERT_SQL = f"""
INSERT INTO form990_part_ix ({_col_csv})
VALUES ({_placeholder_csv})
ON CONFLICT(object_id) DO UPDATE SET
    {_update_csv},
    loaded_at=datetime('now')
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _grp(d: dict | None, key: str) -> int | None:
    if not isinstance(d, dict):
        return None
    return _int(d.get(key))


def _ratio(numerator, denominator) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 6)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def migrate_phase_b(conn: sqlite3.Connection) -> None:
    """Add Phase B columns to form990_part_ix if not already present."""
    existing = {row[1] for row in conn.execute(
        "PRAGMA table_info(form990_part_ix)"
    ).fetchall()}
    added = 0
    for col in _PHASE_B_COLS:
        if col not in existing:
            conn.execute(f"ALTER TABLE form990_part_ix ADD COLUMN {col} INTEGER")
            added += 1
    if added:
        conn.commit()
        logger.info(f"Phase B migration: added {added} columns to form990_part_ix")


def init_db(conn: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    else:
        logger.warning("990_part_ix_schema.sql not found")
    migrate_phase_b(conn)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_part_ix(xml_path: Path, conn: sqlite3.Connection | None) -> dict | None:
    """
    Parse one Form 990 XML and return a form990_part_ix row dict.
    conn is used to look up total_functional_expenses and contributions_grants
    from form990_filings for ratio calculation.
    Returns None if the filing cannot be parsed.
    """
    stem      = xml_path.stem
    object_id = stem.replace("_public", "")

    try:
        f = Filing(object_id, filepath=str(xml_path))
        f.process()
    except Exception as exc:
        logger.error(f"IRSx failed on {xml_path.name}: {exc}")
        return None

    if "IRS990" not in f.list_schedules():
        return None

    s   = f.get_schedule("IRS990")
    hdr = f.get_schedule("ReturnHeader990x") or {}

    ein = str(f.get_ein()).zfill(9)

    tax_period_end = hdr.get("TaxPeriodEndDt", "")
    fiscal_year_end = int(tax_period_end[:4]) if tax_period_end else None

    # ------------------------------------------------------------------
    # Phase A — Lines 25, 12, 14, 11e, 11f  (legacy column names)
    # ------------------------------------------------------------------

    # Line 25 — Total functional expenses by column
    tfe = s.get("TotalFunctionalExpensesGrp") or {}
    total_prog_services   = _grp(tfe, "ProgramServicesAmt")
    total_mgmt_general    = _grp(tfe, "ManagementAndGeneralAmt")
    total_fundraising_exp = _grp(tfe, "FundraisingAmt")
    total_functional_exp  = _grp(tfe, "TotalAmt")

    # Line 12 — Advertising and promotion
    adv = s.get("AdvertisingGrp") or {}
    advertising_prog        = _grp(adv, "ProgramServicesAmt")
    advertising_mgmt        = _grp(adv, "ManagementAndGeneralAmt")
    advertising_fundraising = _grp(adv, "FundraisingAmt")

    # Line 14 — Information technology
    it = s.get("InformationTechnologyGrp") or {}
    it_prog        = _grp(it, "ProgramServicesAmt")
    it_mgmt        = _grp(it, "ManagementAndGeneralAmt")
    it_fundraising = _grp(it, "FundraisingAmt")

    # Line 11e — Professional fundraising service fees (TotalAmt)
    pff = s.get("FeesForServicesProfFundraising") or {}
    prof_fundraising_fees = _grp(pff, "TotalAmt")

    # Line 11f — Investment management fees (TotalAmt)
    imf = s.get("FeesForSrvcInvstMgmntFeesGrp") or {}
    invest_mgmt_fees = _grp(imf, "TotalAmt")

    # ------------------------------------------------------------------
    # Look up contributions_grants and total_functional_expenses from
    # form990_filings for ratio calculation
    # ------------------------------------------------------------------
    contributions_grants = None
    if conn is not None:
        r = conn.execute(
            "SELECT contributions_grants FROM form990_filings WHERE object_id=?",
            (object_id,)
        ).fetchone()
        if r:
            contributions_grants = r[0]

    if total_functional_exp is None and conn is not None:
        r2 = conn.execute(
            "SELECT total_functional_expenses FROM form990_filings WHERE object_id=?",
            (object_id,)
        ).fetchone()
        if r2:
            total_functional_exp = r2[0]

    # ------------------------------------------------------------------
    # Calculated ratios
    # ------------------------------------------------------------------
    prog_services_pct = _ratio(total_prog_services, total_functional_exp)

    overhead_num = None
    if total_mgmt_general is not None and total_fundraising_exp is not None:
        overhead_num = total_mgmt_general + total_fundraising_exp
    elif total_mgmt_general is not None:
        overhead_num = total_mgmt_general
    elif total_fundraising_exp is not None:
        overhead_num = total_fundraising_exp
    overhead_ratio = _ratio(overhead_num, total_functional_exp)

    fundraising_efficiency = _ratio(total_fundraising_exp, contributions_grants)

    row: dict = {
        "object_id":              object_id,
        "ein":                    ein,
        "fiscal_year_end":        fiscal_year_end,
        "total_prog_services":    total_prog_services,
        "total_mgmt_general":     total_mgmt_general,
        "total_fundraising_exp":  total_fundraising_exp,
        "advertising_prog":       advertising_prog,
        "advertising_mgmt":       advertising_mgmt,
        "advertising_fundraising":advertising_fundraising,
        "it_prog":                it_prog,
        "it_mgmt":                it_mgmt,
        "it_fundraising":         it_fundraising,
        "prof_fundraising_fees":  prof_fundraising_fees,
        "invest_mgmt_fees":       invest_mgmt_fees,
        "prog_services_pct":      prog_services_pct,
        "overhead_ratio":         overhead_ratio,
        "fundraising_efficiency": fundraising_efficiency,
    }

    # ------------------------------------------------------------------
    # Phase B — all remaining Part IX lines (cols B, C, D each)
    # ------------------------------------------------------------------
    for xml_key, prefix in _PHASE_B_LINES:
        grp = s.get(xml_key) or {}
        row[f"{prefix}_prog"]        = _grp(grp, "ProgramServicesAmt")
        row[f"{prefix}_mgmt"]        = _grp(grp, "ManagementAndGeneralAmt")
        row[f"{prefix}_fundraising"] = _grp(grp, "FundraisingAmt")

    return row


# ---------------------------------------------------------------------------
# Print helper
# ---------------------------------------------------------------------------

def print_row(row: dict) -> None:
    print(f"\n{'='*72}")
    print(f"  EIN {row.get('ein')}  FY{row.get('fiscal_year_end')}  "
          f"[{row.get('object_id')}]")
    print(f"{'='*72}")
    print(f"  {'Line':<35} {'Prog Svc (B)':>14} {'Mgmt/Gen (C)':>14} {'Fundraising (D)':>16}")
    print(f"  {'-'*82}")

    def fmt(v):
        return f"${v:>13,}" if v is not None else f"{'NULL':>14}"

    # Phase A lines
    print(f"  {'Ln 25 — Total func exp':<35} "
          f"{fmt(row.get('total_prog_services'))} "
          f"{fmt(row.get('total_mgmt_general'))} "
          f"{fmt(row.get('total_fundraising_exp'))}")
    print(f"  {'Ln 12 — Advertising':<35} "
          f"{fmt(row.get('advertising_prog'))} "
          f"{fmt(row.get('advertising_mgmt'))} "
          f"{fmt(row.get('advertising_fundraising'))}")
    print(f"  {'Ln 14 — IT expenses':<35} "
          f"{fmt(row.get('it_prog'))} "
          f"{fmt(row.get('it_mgmt'))} "
          f"{fmt(row.get('it_fundraising'))}")
    print(f"  {'Ln 11e — Prof fund fees (Total A)':<35} "
          f"{'':14} {'':14} {fmt(row.get('prof_fundraising_fees'))}")
    print(f"  {'Ln 11f — Invest mgmt fees (Total A)':<35} "
          f"{'':14} {fmt(row.get('invest_mgmt_fees'))} {'':16}")

    # Phase B lines
    _B_LABELS = [
        ("ln01_grants_govts",      "Ln 1  — Grants to govts/orgs"),
        ("ln02_grants_indiv",      "Ln 2  — Grants to individuals"),
        ("ln03_grants_foreign",    "Ln 3  — Foreign grants"),
        ("ln04_member_benefits",   "Ln 4  — Member benefits"),
        ("ln05_officer_comp",      "Ln 5  — Officer compensation"),
        ("ln06_disqualified_comp", "Ln 6  — Disqualified comp"),
        ("ln07_other_salaries",    "Ln 7  — Other salaries"),
        ("ln08_pension",           "Ln 8  — Pension"),
        ("ln09_emp_benefits",      "Ln 9  — Employee benefits"),
        ("ln10_payroll_taxes",     "Ln 10 — Payroll taxes"),
        ("ln11a_fees_mgmt_svc",    "Ln 11a — Mgmt svc fees"),
        ("ln11b_fees_legal",       "Ln 11b — Legal fees"),
        ("ln11c_fees_accounting",  "Ln 11c — Accounting fees"),
        ("ln11d_fees_lobbying",    "Ln 11d — Lobbying fees"),
        ("ln11e_fees_prof_fund",   "Ln 11e — Prof fund fees (B/C/D)"),
        ("ln11f_fees_invest_mgmt", "Ln 11f — Invest mgmt fees (B/C/D)"),
        ("ln11g_fees_other",       "Ln 11g — Other fees"),
        ("ln13_office_exp",        "Ln 13 — Office expenses"),
        ("ln15_royalties",         "Ln 15 — Royalties"),
        ("ln16_occupancy",         "Ln 16 — Occupancy"),
        ("ln17_travel",            "Ln 17 — Travel"),
        ("ln18_travel_officials",  "Ln 18 — Official travel"),
        ("ln19_conferences",       "Ln 19 — Conferences"),
        ("ln20_interest",          "Ln 20 — Interest"),
        ("ln21_pmts_affiliates",   "Ln 21 — Pmts to affiliates"),
        ("ln22_depreciation",      "Ln 22 — Depreciation"),
        ("ln23_insurance",         "Ln 23 — Insurance"),
        ("ln24_other_exp",         "Ln 24 — Other expenses"),
    ]
    print()
    print("  Phase B lines:")
    for prefix, label in _B_LABELS:
        p = row.get(f"{prefix}_prog")
        m = row.get(f"{prefix}_mgmt")
        d = row.get(f"{prefix}_fundraising")
        if any(v is not None for v in (p, m, d)):
            print(f"  {label:<35} {fmt(p)} {fmt(m)} {fmt(d)}")

    print()

    def pct(v):
        return f"{v*100:.1f}%" if v is not None else "NULL"

    print(f"  prog_services_pct      = {pct(row.get('prog_services_pct'))}")
    print(f"  overhead_ratio         = {pct(row.get('overhead_ratio'))}")
    print(f"  fundraising_efficiency = {pct(row.get('fundraising_efficiency'))}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(xml_files: list[Path], db_path: str, ein_filter: set[str] | None,
        dry_run: bool) -> None:
    conn = sqlite3.connect(db_path)
    init_db(conn)

    parsed = written = skipped = errors = 0
    for xml_path in xml_files:
        row = extract_part_ix(xml_path, conn)
        if row is None:
            errors += 1
            continue

        if ein_filter and row["ein"] not in ein_filter:
            skipped += 1
            continue

        parsed += 1
        if dry_run or logger.isEnabledFor(logging.DEBUG):
            print_row(row)

        if not dry_run:
            conn.execute(UPSERT_SQL, row)
            if parsed % 500 == 0:
                conn.commit()
                logger.info(f"  ... {parsed} rows written")
            written += 1

    conn.commit()
    conn.close()

    action = "would write" if dry_run else "written"
    logger.info(f"Done — {parsed} parsed, {written} {action}, "
                f"{skipped} skipped (EIN filter), {errors} errors")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Parse Form 990 Part IX functional columns from TEOS XML (Phase A + B)"
    )
    parser.add_argument("--db", required=True, help="Path to 990_data.db")
    parser.add_argument("--xml", nargs="+",
                        help="Specific XML file(s); default: all in data/raw/990_xml/")
    parser.add_argument("--ein", nargs="+",
                        help="Filter to these EINs only (zero-padded, no hyphens)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print without writing to DB")
    args = parser.parse_args()

    if args.xml:
        xml_files = [Path(p) for p in args.xml]
    else:
        xml_files = sorted(XML_DIR.glob("*_public.xml"))

    if not xml_files:
        logger.error("No XML files found")
        return

    ein_filter = None
    if args.ein:
        ein_filter = {e.replace("-", "").strip().zfill(9) for e in args.ein}

    logger.info(f"Part IX parse (Phase A+B) — {len(xml_files)} XML files"
                + (f", EIN filter: {ein_filter}" if ein_filter else ""))

    run(xml_files, args.db, ein_filter, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
