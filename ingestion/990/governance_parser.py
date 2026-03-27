#!/usr/bin/env python3
"""
ingestion/990/governance_parser.py
-------------------------------------
Parse IRS Form 990 Part VI (Governance, Management, and Disclosure)
into form990_governance.

Source: TEOS/IRSx XML only. All fields come from the IRS990 schedule body.

Usage:
    .venv/bin/python3 ingestion/990/governance_parser.py \\
        --db data/databases/990_data.db

    .venv/bin/python3 ingestion/990/governance_parser.py \\
        --db data/databases/990_data.db \\
        --ein 042103580 042103594 --dry-run
"""

import argparse
import logging
import sqlite3
from pathlib import Path

from irsx.filing import Filing

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "990_governance_schema.sql"
XML_DIR     = Path(__file__).resolve().parents[2] / "data" / "raw" / "990_xml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int(val) -> int | None:
    try:
        return int(float(str(val).replace(',', ''))) if val is not None else None
    except (ValueError, TypeError):
        return None


def _bool_ind(val) -> int | None:
    if val is None:
        return None
    if isinstance(val, dict):
        val = val.get('#text', val)
    s = str(val).lower().strip()
    if s in ('true', '1', 'x'):
        return 1
    if s in ('false', '0'):
        return 0
    return None


# ---------------------------------------------------------------------------
# Part VI extraction
# ---------------------------------------------------------------------------

def extract_governance(object_id: str, xml_path: Path, ein: str,
                       fiscal_year_end: int) -> dict | None:
    try:
        f = Filing(object_id, str(xml_path))
        f.process()
    except Exception as e:
        logger.warning(f"  IRSx error on {object_id}: {e}")
        return None

    if 'IRS990' not in f.list_schedules():
        return None

    try:
        sked = f.get_schedule('IRS990')
    except Exception as e:
        logger.warning(f"  IRS990 parse error {object_id}: {e}")
        return None

    if not sked:
        return None

    # financials_audited: either FSAuditedInd=true or consolidated audit
    fs_audited = _bool_ind(sked.get('FSAuditedInd'))
    consol = sked.get('ConsolidatedAuditFinclStmtInd')
    if fs_audited is None and consol is not None:
        fs_audited = _bool_ind(consol)

    return {
        'object_id':                    object_id,
        'ein':                          ein,
        'fiscal_year_end':              fiscal_year_end,
        'voting_members_governing_body': (
            _int(sked.get('VotingMembersGoverningBodyCnt')) or
            _int(sked.get('GoverningBodyVotingMembersCnt'))
        ),
        'voting_members_independent': (
            _int(sked.get('VotingMembersIndependentCnt')) or
            _int(sked.get('IndependentVotingMemberCnt'))
        ),
        'total_employees': (
            _int(sked.get('TotalEmployeeCnt')) or
            _int(sked.get('EmployeeCnt'))
        ),
        'family_or_business_relationship':  _bool_ind(sked.get('FamilyOrBusinessRlnInd')),
        'change_to_org_documents':           _bool_ind(sked.get('ChangeToOrgDocumentsInd')),
        'election_of_board_members':         _bool_ind(sked.get('ElectionOfBoardMembersInd')),
        'minutes_of_governing_body':         _bool_ind(sked.get('MinutesOfGoverningBodyInd')),
        'form990_provided_to_board':         _bool_ind(sked.get('Form990ProvidedToGvrnBodyInd')),
        'conflict_of_interest_policy':       _bool_ind(sked.get('ConflictOfInterestPolicyInd')),
        'whistleblower_policy':              _bool_ind(sked.get('WhistleblowerPolicyInd')),
        'document_retention_policy':         _bool_ind(sked.get('DocumentRetentionPolicyInd')),
        'financials_audited':                fs_audited,
        'audit_committee':                   _bool_ind(sked.get('AuditCommitteeInd')),
        'federal_grant_audit_required':      _bool_ind(sked.get('FederalGrantAuditRequiredInd')),
        'government_grants_amt':             _int(sked.get('GovernmentGrantsAmt')),
    }


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def upsert_governance(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO form990_governance
            (object_id, ein, fiscal_year_end,
             voting_members_governing_body, voting_members_independent,
             total_employees, family_or_business_relationship,
             change_to_org_documents, election_of_board_members,
             minutes_of_governing_body, form990_provided_to_board,
             conflict_of_interest_policy, whistleblower_policy,
             document_retention_policy, financials_audited,
             audit_committee, federal_grant_audit_required,
             government_grants_amt)
        VALUES
            (:object_id, :ein, :fiscal_year_end,
             :voting_members_governing_body, :voting_members_independent,
             :total_employees, :family_or_business_relationship,
             :change_to_org_documents, :election_of_board_members,
             :minutes_of_governing_body, :form990_provided_to_board,
             :conflict_of_interest_policy, :whistleblower_policy,
             :document_retention_policy, :financials_audited,
             :audit_committee, :federal_grant_audit_required,
             :government_grants_amt)
    """, row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(db_path: str, xml_dir: Path = XML_DIR,
        target_eins: set | None = None, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    if not dry_run:
        init_db(conn)

    filings = {
        row[0]: (row[1], row[2])
        for row in conn.execute(
            "SELECT object_id, ein, fiscal_year_end FROM form990_filings WHERE data_source='irsx'"
        )
    }

    xml_files = sorted(xml_dir.glob("*_public.xml"))
    logger.info(f"Governance: {len(xml_files):,} XML files, {len(filings):,} irsx filings")

    total = processed = skipped = 0
    for xml_path in xml_files:
        object_id = xml_path.stem.replace("_public", "")
        if object_id not in filings:
            skipped += 1
            continue
        ein, fy = filings[object_id]
        if target_eins and ein not in target_eins:
            skipped += 1
            continue

        row = extract_governance(object_id, xml_path, ein, fy)
        processed += 1

        if row is None:
            continue

        if dry_run:
            logger.info(f"  DRY {object_id} ({ein} FY{fy}): "
                        f"board={row['voting_members_governing_body']}, "
                        f"indep={row['voting_members_independent']}, "
                        f"coi={row['conflict_of_interest_policy']}, "
                        f"emp={row['total_employees']}")
            continue

        upsert_governance(conn, row)
        total += 1

        if total % 200 == 0:
            conn.commit()
            logger.info(f"  {total:,}/{len(xml_files):,} written …")

    conn.commit()
    conn.close()
    logger.info(f"Governance complete: {total:,} rows from {processed:,} XMLs")
    return {'rows': total, 'processed': processed, 'skipped': skipped}


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',      required=True)
    parser.add_argument('--xml-dir', default=str(XML_DIR))
    parser.add_argument('--ein',     nargs='+')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    run(args.db, Path(args.xml_dir),
        target_eins=set(args.ein) if args.ein else None,
        dry_run=args.dry_run)


if __name__ == '__main__':
    main()
