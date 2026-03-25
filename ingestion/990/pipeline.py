#!/usr/bin/env python3
"""
ingestion/990/pipeline.py
--------------------------
Full-scale 990 pipeline for all private nonprofit 4-year degree-granting
institutions in institution_master.

Two-phase load:
  Phase 1 — TEOS (FY2020–FY2023, index years 2021–2024):
    Downloads and parses IRS Form 990 XML files via the TEOS portal.
    Files land in data/raw/990_xml/. Already-downloaded files are skipped.
    Note: TEOS index year 2020 returns HTTP 302 redirects — inaccessible.
    FY2019 is covered by ProPublica.

  Phase 2 — ProPublica (FY2012–FY2019):
    Fetches structured 990 data from the ProPublica Nonprofit Explorer API.
    Processed in batches of 50 EINs (rate-limited to 5 req/sec).

Institution scope: institution_master WHERE control=2 (private nonprofit)
  AND iclevel=1 (4-year) AND degree_granting=1 AND ein valid.

Progress is logged to LOG_PATH. Run as a background process.

Usage:
    python3 ingestion/990/pipeline.py \\
        --ipeds-db  data/databases/ipeds_data.db \\
        --db        data/databases/990_data.db \\
        --xml-dir   data/raw/990_xml

    # ProPublica only (skip TEOS — useful for reruns)
    python3 ingestion/990/pipeline.py ... --skip-teos

    # TEOS only
    python3 ingestion/990/pipeline.py ... --skip-propublica
"""

import argparse
import importlib.util
import logging
import sqlite3
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Module loader (ingestion/990/ can't be imported as a dotted path)
# ---------------------------------------------------------------------------

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_HERE        = Path(__file__).parent
_downloader  = _load_module("downloader",         _HERE / "downloader.py")
_parser      = _load_module("parser",             _HERE / "parser.py")
_pp_loader   = _load_module("propublica_loader",  _HERE / "propublica_loader.py")

LOG_PATH     = Path("data/raw/990_xml/pipeline.log")
SCHEMA_PATH  = Path(__file__).resolve().parents[2] / "schema" / "990_schema.sql"

# TEOS index years → fiscal years covered
# index year 2021 → FY2020 (TAX_PERIOD 202006 / 202005 etc.)
# index year 2022 → FY2021
# index year 2023 → FY2022
# index year 2024 → FY2023
# NOTE: index year 2020 returns HTTP 302 — skip it; FY2019 covered by ProPublica
TEOS_YEARS   = [2021, 2022, 2023, 2024]
PP_START     = 2012
PP_END       = 2019
BATCH_SIZE   = 50


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8"),
        ],
    )
    return logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Institution master query
# ---------------------------------------------------------------------------

def load_target_eins(ipeds_db: str) -> list[str]:
    """
    Return distinct valid EINs for private nonprofit 4-year degree-granting
    institutions from institution_master.
    """
    conn = sqlite3.connect(ipeds_db)
    rows = conn.execute("""
        SELECT DISTINCT ein
        FROM institution_master
        WHERE control = 2
          AND iclevel = 1
          AND degree_granting = 1
          AND ein IS NOT NULL
          AND ein != ''
          AND ein != '-1'
          AND CAST(ein AS INTEGER) > 0
        ORDER BY ein
    """).fetchall()
    conn.close()

    eins = []
    for (ein,) in rows:
        normalised = ein.replace("-", "").strip().zfill(9)
        if normalised != "000000000" and len(normalised) == 9:
            eins.append(normalised)
    return eins


# ---------------------------------------------------------------------------
# Phase 1 — TEOS download + parse
# ---------------------------------------------------------------------------

def run_teos_phase(eins: list[str], xml_dir: Path, db_path: str,
                   log: logging.Logger) -> dict:
    """Download XMLs via TEOS and parse into 990_data.db."""
    target_set = set(eins)
    xml_dir.mkdir(parents=True, exist_ok=True)

    # ---- Download ----
    log.info(f"TEOS DOWNLOAD — {len(eins):,} EINs, years {TEOS_YEARS}")
    for year in TEOS_YEARS:
        log.info(f"  Fetching TEOS index year {year} …")
        try:
            written = _downloader.run_teos(
                years=[year],
                target_eins=target_set,
                out_dir=xml_dir,
                dry_run=False,
            )
            log.info(f"  Year {year}: {written} XML file(s) written/skipped")
        except Exception as exc:
            log.error(f"  Year {year} FAILED: {exc}")

    # ---- Parse all XMLs ----
    xml_files = sorted(xml_dir.glob("*_public.xml"))
    log.info(f"TEOS PARSE — {len(xml_files):,} XML files in {xml_dir}")

    conn = sqlite3.connect(db_path)
    _parser.init_db(conn)

    parsed = written = errors = 0
    for xml_path in xml_files:
        row = _parser.extract_filing(xml_path)
        if row is None:
            errors += 1
            continue
        parsed += 1
        _parser.upsert_filing(conn, row)
        if parsed % 100 == 0:
            conn.commit()
            log.info(f"  Parsed {parsed:,} / {len(xml_files):,} XMLs …")
    conn.commit()
    conn.close()

    log.info(f"  Parse complete: {parsed:,} parsed, {errors} errors")
    return {"teos_parsed": parsed, "teos_errors": errors}


# ---------------------------------------------------------------------------
# Phase 2 — ProPublica
# ---------------------------------------------------------------------------

def run_propublica_phase(eins: list[str], db_path: str,
                         log: logging.Logger) -> dict:
    """Load FY2012–FY2019 via ProPublica API in batches of BATCH_SIZE."""
    log.info(f"PROPUBLICA LOAD — {len(eins):,} EINs, FY{PP_START}–FY{PP_END}")

    import requests as _req
    session = _req.Session()
    session.headers["User-Agent"] = "project-jenni-990-pipeline/1.0"

    conn = sqlite3.connect(db_path)
    _parser.init_db(conn)   # ensure schema exists

    total_loaded = total_skipped = 0
    batches = [eins[i:i+BATCH_SIZE] for i in range(0, len(eins), BATCH_SIZE)]

    for b_idx, batch in enumerate(batches):
        b_loaded = b_skipped = 0
        for ein in batch:
            loaded, skipped = _pp_loader.load_ein(
                conn, ein, "",
                session, PP_START, PP_END, dry_run=False,
            )
            b_loaded  += loaded
            b_skipped += skipped
            time.sleep(_pp_loader.RATE_LIMIT)

        conn.commit()
        total_loaded  += b_loaded
        total_skipped += b_skipped

        pct = (b_idx + 1) / len(batches) * 100
        log.info(
            f"  Batch {b_idx+1:>4}/{len(batches)} ({pct:5.1f}%)  "
            f"+{b_loaded} loaded, +{b_skipped} skipped  "
            f"[cumulative: {total_loaded:,} loaded]"
        )

    conn.close()
    log.info(f"  ProPublica complete: {total_loaded:,} loaded, "
             f"{total_skipped} skipped")
    return {"pp_loaded": total_loaded, "pp_skipped": total_skipped}


# ---------------------------------------------------------------------------
# Final statistics report
# ---------------------------------------------------------------------------

def report_stats(db_path: str, eins: list[str], log: logging.Logger) -> None:
    conn = sqlite3.connect(db_path)

    total_rows = conn.execute("SELECT COUNT(*) FROM form990_filings").fetchone()[0]
    log.info(f"\n{'='*65}")
    log.info(f"PIPELINE COMPLETE — FINAL STATISTICS")
    log.info(f"{'='*65}")
    log.info(f"Total rows in form990_filings: {total_rows:,}")

    # Source breakdown
    src_rows = conn.execute("""
        SELECT data_source, COUNT(*) FROM form990_filings
        GROUP BY data_source
    """).fetchall()
    for src, cnt in src_rows:
        log.info(f"  {src}: {cnt:,} rows")

    # Coverage by institution
    ein_set = set(eins)
    filed_eins = {r[0] for r in conn.execute(
        "SELECT DISTINCT ein FROM form990_filings"
    )}
    target_filed = filed_eins & ein_set
    target_no_filing = ein_set - filed_eins

    # Coverage tiers: >=10 yrs = complete, 1-9 = partial, 0 = none
    yr_counts = dict(conn.execute("""
        SELECT ein, COUNT(DISTINCT fiscal_year_end)
        FROM form990_filings WHERE ein IN ({})
        GROUP BY ein
    """.format(",".join(f"'{e}'" for e in ein_set))).fetchall())

    complete  = sum(1 for e in ein_set if yr_counts.get(e, 0) >= 10)
    partial   = sum(1 for e in ein_set if 1 <= yr_counts.get(e, 0) < 10)
    none_     = len(target_no_filing)

    log.info(f"\nInstitution coverage (of {len(ein_set):,} target EINs):")
    log.info(f"  Complete (≥10 fiscal years): {complete:,}")
    log.info(f"  Partial  (1–9 fiscal years): {partial:,}")
    log.info(f"  No filings found:            {none_:,}")

    # Year distribution
    log.info(f"\nRows by fiscal year:")
    yr_dist = conn.execute("""
        SELECT fiscal_year_end, COUNT(*), data_source
        FROM form990_filings
        GROUP BY fiscal_year_end, data_source
        ORDER BY fiscal_year_end, data_source
    """).fetchall()
    for fy, cnt, src in yr_dist:
        log.info(f"  FY{fy}  {src:>12}  {cnt:>6,} rows")

    # Systematic errors — EINs in institution_master but zero filings
    if target_no_filing:
        sample = sorted(target_no_filing)[:20]
        log.info(f"\nSample of {len(target_no_filing):,} EINs with no filings "
                 f"(first 20): {sample}")

    conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Full-scale 990 pipeline — TEOS + ProPublica"
    )
    parser.add_argument("--ipeds-db", default="data/databases/ipeds_data.db")
    parser.add_argument("--db",       default="data/databases/990_data.db")
    parser.add_argument("--xml-dir",  default="data/raw/990_xml")
    parser.add_argument("--skip-teos",        action="store_true")
    parser.add_argument("--skip-propublica",  action="store_true")
    args = parser.parse_args()

    log = setup_logging()
    log.info("="*65)
    log.info("990 FULL-SCALE PIPELINE STARTING")
    log.info("="*65)

    eins = load_target_eins(args.ipeds_db)
    log.info(f"Target institutions: {len(eins):,} EINs from institution_master")
    log.info(f"TEOS years: {TEOS_YEARS}  (covers FY2020–FY2023)")
    log.info(f"ProPublica: FY{PP_START}–FY{PP_END}")

    xml_dir = Path(args.xml_dir)
    stats = {}

    if not args.skip_teos:
        stats.update(run_teos_phase(eins, xml_dir, args.db, log))
    else:
        log.info("TEOS phase skipped (--skip-teos)")

    if not args.skip_propublica:
        stats.update(run_propublica_phase(eins, args.db, log))
    else:
        log.info("ProPublica phase skipped (--skip-propublica)")

    report_stats(args.db, eins, log)
    log.info("Pipeline complete.")


if __name__ == "__main__":
    main()
