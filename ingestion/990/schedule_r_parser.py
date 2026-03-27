#!/usr/bin/env python3
"""
ingestion/990/schedule_r_parser.py
-------------------------------------
Parse IRS Form 990 Schedule R (Related Organizations and Unrelated Partnerships)
into form990_related_orgs and form990_related_transactions.

Source: TEOS/IRSx XML only.

Usage:
    .venv/bin/python3 ingestion/990/schedule_r_parser.py \\
        --db data/databases/990_data.db

    # Specific EINs only
    .venv/bin/python3 ingestion/990/schedule_r_parser.py \\
        --db data/databases/990_data.db \\
        --ein 042103580 042103594 --dry-run
"""

import argparse
import logging
import sqlite3
from pathlib import Path

from irsx.filing import Filing

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "990_schedule_r_schema.sql"
XML_DIR     = Path(__file__).resolve().parents[2] / "data" / "raw" / "990_xml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, dict):
        return val.get('#text') or val.get('BusinessNameLine1Txt') or str(val)
    return str(val).strip() or None


def _int(val) -> int | None:
    try:
        return int(float(str(val).replace(',', ''))) if val is not None else None
    except (ValueError, TypeError):
        return None


def _bool_ind(val) -> int | None:
    """Convert IRS boolean indicator ('true'/'false'/0/1) to 0/1."""
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


def _org_name(d: dict) -> str | None:
    """Extract org name from a name dict or BusinessName dict."""
    if d is None:
        return None
    for key in ('BusinessNameLine1Txt', '#text'):
        if key in d:
            return str(d[key]).strip() or None
    return None


def _name_field(entry: dict, *keys) -> str | None:
    """Pull org name from a nested name field."""
    for k in keys:
        v = entry.get(k)
        if v:
            if isinstance(v, dict):
                name = _org_name(v)
                if name:
                    return name
            return str(v).strip() or None
    return None


# ---------------------------------------------------------------------------
# Schedule R extraction
# ---------------------------------------------------------------------------

def extract_schedule_r(object_id: str, xml_path: Path, ein: str,
                       fiscal_year_end: int) -> tuple[list[dict], list[dict]]:
    """
    Parse Schedule R from a single XML filing.
    Returns (orgs_rows, tx_rows).
    """
    try:
        f = Filing(object_id, str(xml_path))
        f.process()
    except Exception as e:
        logger.warning(f"  IRSx error on {object_id}: {e}")
        return [], []

    if 'IRS990ScheduleR' not in f.list_schedules():
        return [], []

    try:
        sked = f.get_schedule('IRS990ScheduleR')
    except Exception as e:
        logger.warning(f"  Schedule R parse error {object_id}: {e}")
        return [], []

    if not sked:
        return [], []

    orgs = []
    txs  = []

    # ---- Related org groups ----
    type_map = {
        'IdDisregardedEntitiesGrp':        'disregarded',
        'IdRelatedTaxExemptOrgGrp':        'tax_exempt',
        'IdRelatedOrgTxblPartnershipGrp':  'partnership',
        'IdRelatedOrgTxblCorpTrGrp':       'corp_trust',
    }

    for group_key, rel_type in type_map.items():
        raw = sked.get(group_key, [])
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            continue

        for entry in raw:
            if not isinstance(entry, dict):
                continue

            # Name — different keys per group type
            name = (
                _name_field(entry, 'DisregardedEntityName') or
                _name_field(entry, 'RelatedOrganizationName')
            )

            # Controlling entity
            ctrl = (
                _name_field(entry, 'DirectControllingEntityName') or
                _name_field(entry, 'DirectControllingNaOrg')
            )

            # Domicile
            domicile = (
                entry.get('LegalDomicileStateCd') or
                entry.get('LegalDomicileForeignCountryCd')
            )
            if isinstance(domicile, dict):
                domicile = domicile.get('#text') or str(domicile)

            orgs.append({
                'object_id':                object_id,
                'ein':                      ein,
                'fiscal_year_end':          fiscal_year_end,
                'org_name':                 name,
                'org_ein':                  _text(entry.get('EIN')),
                'relationship_type':        rel_type,
                'primary_activities':       _text(entry.get('PrimaryActivitiesTxt')),
                'legal_domicile':           str(domicile).strip() if domicile else None,
                'direct_controlling_entity': ctrl,
                'controlled_org_ind':       _bool_ind(entry.get('ControlledOrganizationInd')),
                'total_income':             _int(entry.get('TotalIncomeAmt')),
                'eoy_assets':               _int(entry.get('EndOfYearAssetsAmt')),
                'share_of_total_income':    _int(entry.get('ShareOfTotalIncomeAmt')),
                'share_of_eoy_assets':      _int(entry.get('ShareOfEOYAssetsAmt')),
            })

    # ---- Transactions (Part V) ----
    raw_tx = sked.get('TransactionsRelatedOrgGrp', [])
    if isinstance(raw_tx, dict):
        raw_tx = [raw_tx]
    if isinstance(raw_tx, list):
        for entry in raw_tx:
            if not isinstance(entry, dict):
                continue
            org_name = _name_field(entry, 'OtherOrganizationName')
            txs.append({
                'object_id':      object_id,
                'ein':            ein,
                'fiscal_year_end': fiscal_year_end,
                'other_org_name': org_name,
                'transaction_type': _text(entry.get('TransactionTypeTxt')),
                'amount':         _int(entry.get('InvolvedAmt')),
                'amount_method':  _text(entry.get('MethodOfAmountDeterminationTxt')),
            })

    return orgs, txs


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def upsert_orgs(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Delete existing rows for this object_id, then insert fresh."""
    if not rows:
        return 0
    obj = rows[0]['object_id']
    conn.execute("DELETE FROM form990_related_orgs WHERE object_id=?", (obj,))
    conn.executemany("""
        INSERT INTO form990_related_orgs
            (object_id, ein, fiscal_year_end, org_name, org_ein,
             relationship_type, primary_activities, legal_domicile,
             direct_controlling_entity, controlled_org_ind,
             total_income, eoy_assets, share_of_total_income, share_of_eoy_assets)
        VALUES
            (:object_id, :ein, :fiscal_year_end, :org_name, :org_ein,
             :relationship_type, :primary_activities, :legal_domicile,
             :direct_controlling_entity, :controlled_org_ind,
             :total_income, :eoy_assets, :share_of_total_income, :share_of_eoy_assets)
    """, rows)
    return len(rows)


def upsert_txs(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    obj = rows[0]['object_id']
    conn.execute("DELETE FROM form990_related_transactions WHERE object_id=?", (obj,))
    conn.executemany("""
        INSERT INTO form990_related_transactions
            (object_id, ein, fiscal_year_end, other_org_name,
             transaction_type, amount, amount_method)
        VALUES
            (:object_id, :ein, :fiscal_year_end, :other_org_name,
             :transaction_type, :amount, :amount_method)
    """, rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(db_path: str, xml_dir: Path = XML_DIR,
        target_eins: set | None = None, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    if not dry_run:
        init_db(conn)

    # Load object_id → (ein, fiscal_year_end) from existing filings
    filings = {
        row[0]: (row[1], row[2])
        for row in conn.execute(
            "SELECT object_id, ein, fiscal_year_end FROM form990_filings WHERE data_source='irsx'"
        )
    }

    xml_files = sorted(xml_dir.glob("*_public.xml"))
    logger.info(f"Schedule R: {len(xml_files):,} XML files, {len(filings):,} irsx filings")

    total_orgs = total_txs = processed = skipped = 0
    for xml_path in xml_files:
        object_id = xml_path.stem.replace("_public", "")
        if object_id not in filings:
            skipped += 1
            continue
        ein, fy = filings[object_id]
        if target_eins and ein not in target_eins:
            skipped += 1
            continue

        orgs, txs = extract_schedule_r(object_id, xml_path, ein, fy)
        processed += 1

        if dry_run:
            if orgs or txs:
                logger.info(f"  DRY {object_id} ({ein} FY{fy}): "
                            f"{len(orgs)} orgs, {len(txs)} txs")
            continue

        if orgs or txs:
            total_orgs += upsert_orgs(conn, orgs)
            total_txs  += upsert_txs(conn, txs)

        if processed % 200 == 0:
            conn.commit()
            logger.info(f"  {processed:,}/{len(xml_files):,} processed — "
                        f"{total_orgs:,} org rows, {total_txs:,} tx rows so far")

    conn.commit()
    conn.close()

    result = {'orgs': total_orgs, 'transactions': total_txs,
              'processed': processed, 'skipped': skipped}
    logger.info(f"Schedule R complete: {total_orgs:,} org rows, "
                f"{total_txs:,} tx rows from {processed:,} XMLs")
    return result


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
