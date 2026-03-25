#!/usr/bin/env python3
"""
ingestion/990/downloader.py
----------------------------
Downloads IRS Form 990 XML filings for institutions whose EINs are in
institution_master (or a hardcoded validation set).

Mode 1 — IRS TEOS portal (2019–present):
  Downloads the annual index CSV, matches EINs, then downloads only the
  ZIP files that contain those institutions' XML filings and extracts them.
  ZIP files are large (120MB–2.6GB); this script avoids full-ZIP downloads
  by probing each ZIP's central directory via HTTP Range requests before
  committing to a full download.

Mode 2 — ProPublica API (2012–2018): Not yet implemented.

Usage:
    # Mode 1 — five validation institutions, 2022–2023
    python3 ingestion/990/downloader.py \\
        --db data/databases/ipeds_data.db \\
        --years 2022 2023 \\
        --out data/raw/990_xml

    # Limit to specific EINs only
    python3 ingestion/990/downloader.py \\
        --db data/databases/ipeds_data.db \\
        --years 2023 \\
        --ein 042103544 042103580 \\
        --out data/raw/990_xml

    # Dry run — show which filings would be downloaded, no writes
    python3 ingestion/990/downloader.py \\
        --db data/databases/ipeds_data.db \\
        --years 2023 --dry-run

Environment:
    Reads EINs from institution_master in --db unless --ein is specified.
    No API key required for TEOS portal — plain HTTPS.
"""

import argparse
import csv
import io
import logging
import os
import sqlite3
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

INDEX_URL  = "https://apps.irs.gov/pub/epostcard/990/xml/{year}/index_{year}.csv"
ZIP_URL    = "https://apps.irs.gov/pub/epostcard/990/xml/{year}/{fname}"

# Validation institution EINs (fallback if no DB available)
VALIDATION_EINS = {
    "042103544",  # Babson College
    "041081650",  # Bentley University
    "042103545",  # Boston College / Trustees of Boston College
    "042103580",  # Harvard University
    "042103594",  # MIT
}


# ---------------------------------------------------------------------------
# EIN helpers
# ---------------------------------------------------------------------------

def load_eins_from_db(db_path: str) -> set[str]:
    """Return all EINs from institution_master that are non-null."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT ein FROM institution_master WHERE ein IS NOT NULL AND ein != ''"
    ).fetchall()
    conn.close()
    # Normalise: strip hyphens, zero-pad to 9 digits
    return {_norm_ein(r[0]) for r in rows}


def _norm_ein(ein: str) -> str:
    """Normalise EIN to 9-digit string without hyphens."""
    return ein.replace("-", "").strip().zfill(9)


# ---------------------------------------------------------------------------
# Index parsing
# ---------------------------------------------------------------------------

def fetch_index(year: int, session: requests.Session) -> list[dict]:
    """
    Download and parse the TEOS index CSV for a given year.
    Returns a list of row dicts with keys:
      RETURN_ID, FILING_TYPE, EIN, TAX_PERIOD, SUB_DATE,
      TAXPAYER_NAME, RETURN_TYPE, DLN, OBJECT_ID
    Only RETURN_TYPE == '990' rows are returned.
    """
    url = INDEX_URL.format(year=year)
    logger.info(f"Fetching index {year}: {url}")
    resp = session.get(url, timeout=120)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    full_990 = [r for r in rows if r.get("RETURN_TYPE") == "990"]
    logger.info(f"  {len(rows):,} total rows; {len(full_990):,} Form 990 filings")
    return full_990


def match_eins(rows: list[dict], target_eins: set[str]) -> list[dict]:
    """
    Filter index rows to those whose EIN is in target_eins.
    Takes the most recent filing per EIN (by TAX_PERIOD, descending).
    """
    by_ein: dict[str, dict] = {}
    for row in rows:
        ein = _norm_ein(row["EIN"])
        if ein not in target_eins:
            continue
        existing = by_ein.get(ein)
        if existing is None or row["TAX_PERIOD"] > existing["TAX_PERIOD"]:
            by_ein[ein] = row
    return list(by_ein.values())


# ---------------------------------------------------------------------------
# ZIP discovery — HTTP Range-based central directory probe
# ---------------------------------------------------------------------------

def _zip_contains_file(session: requests.Session, zip_url: str,
                       filename: str) -> bool:
    """
    Return True if `filename` is listed in the ZIP's central directory.
    Uses HTTP Range requests — avoids downloading the full ZIP.
    Falls back to False on any error (caller will try full download).
    """
    try:
        # 1. Get file size
        head = session.head(zip_url, timeout=15)
        if head.status_code != 200:
            return False
        file_size = int(head.headers.get("Content-Length", 0))
        if not file_size:
            return False

        # 2. Read up to 65 KB from end to find the End-of-Central-Directory record
        read_size = min(65_558, file_size)
        resp = session.get(
            zip_url,
            headers={"Range": f"bytes={file_size - read_size}-{file_size - 1}"},
            timeout=30,
        )
        if resp.status_code not in (200, 206):
            return False
        tail = resp.content

        # 3. Locate EOCD signature (PK\x05\x06) from the end
        sig = b"PK\x05\x06"
        pos = tail.rfind(sig)
        if pos == -1:
            return False
        eocd = tail[pos:]
        if len(eocd) < 22:
            return False

        cd_size   = struct.unpack_from("<I", eocd, 12)[0]
        cd_offset = struct.unpack_from("<I", eocd, 16)[0]

        # ZIP64 guard — central directory offset == 0xFFFFFFFF means ZIP64
        if cd_offset == 0xFFFF_FFFF or cd_size == 0xFFFF_FFFF:
            # ZIP64 EOCD locator is immediately before the EOCD record
            # Offset of EOCD in the full file:
            eocd_abs = file_size - read_size + pos
            z64_loc_abs = eocd_abs - 20
            if z64_loc_abs < 0:
                return False
            z64_resp = session.get(
                zip_url,
                headers={"Range": f"bytes={z64_loc_abs}-{z64_loc_abs + 19}"},
                timeout=30,
            )
            z64_data = z64_resp.content
            if z64_data[:4] != b"PK\x06\x07":
                return False
            z64_eocd_abs = struct.unpack_from("<Q", z64_data, 8)[0]
            z64_eocd_resp = session.get(
                zip_url,
                headers={"Range": f"bytes={z64_eocd_abs}-{z64_eocd_abs + 55}"},
                timeout=30,
            )
            z64_eocd = z64_eocd_resp.content
            if z64_eocd[:4] != b"PK\x06\x06":
                return False
            cd_size   = struct.unpack_from("<Q", z64_eocd, 40)[0]
            cd_offset = struct.unpack_from("<Q", z64_eocd, 48)[0]

        # 4. Download central directory
        cd_resp = session.get(
            zip_url,
            headers={"Range": f"bytes={cd_offset}-{cd_offset + cd_size - 1}"},
            timeout=60,
        )
        if cd_resp.status_code not in (200, 206):
            return False

        # 5. Simple byte-search for the filename
        return filename.encode("utf-8") in cd_resp.content

    except Exception as exc:
        logger.debug(f"ZIP probe error ({zip_url}): {exc}")
        return False


def find_zip_for_object(session: requests.Session, year: int,
                        object_id: str) -> str | None:
    """
    Determine which TEOS ZIP file contains `{object_id}_public.xml`.

    Strategy:
    1. If positions 5-6 of object_id parse to a valid month (01-12), try that
       ZIP first (single HTTP range probe).
    2. Scan all available ZIPs for the year in order if step 1 fails.

    Returns the ZIP filename (e.g. '2023_TEOS_XML_01A.zip') or None.
    """
    filename = f"{object_id}_public.xml"
    month_code = object_id[4:6]

    candidates = []
    if month_code.isdigit() and 1 <= int(month_code) <= 12:
        candidates.append(f"{year}_TEOS_XML_{int(month_code):02d}A.zip")

    # Append all other possible ZIPs (A suffix, months 01–12) for fallback
    for m in range(1, 13):
        fallback = f"{year}_TEOS_XML_{m:02d}A.zip"
        if fallback not in candidates:
            candidates.append(fallback)

    for zip_fname in candidates:
        url = ZIP_URL.format(year=year, fname=zip_fname)
        logger.debug(f"  Probing {zip_fname} for {filename} …")
        if _zip_contains_file(session, url, filename):
            logger.info(f"  Found {filename} in {zip_fname}")
            return zip_fname

    logger.warning(f"  {filename} not found in any {year} ZIP")
    return None


# ---------------------------------------------------------------------------
# Download and extract
# ---------------------------------------------------------------------------

def download_and_extract(session: requests.Session, year: int,
                         zip_fname: str, object_ids: set[str],
                         out_dir: Path) -> set[str]:
    """
    Download a TEOS ZIP and extract the XML files for the given object_ids.
    Streams the ZIP to a temp file to handle large archives without loading
    fully into memory.

    Returns the set of object_ids successfully extracted.
    """
    url = ZIP_URL.format(year=year, fname=zip_fname)
    resp = session.head(url, timeout=15)
    size_mb = int(resp.headers.get("Content-Length", 0)) // 1_000_000
    logger.info(f"Downloading {zip_fname} ({size_mb} MB) …")

    extracted: set[str] = set()
    targets = {f"{oid}_public.xml" for oid in object_ids}

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = tmp.name
        try:
            with session.get(url, stream=True, timeout=600) as dl:
                dl.raise_for_status()
                done = 0
                for chunk in dl.iter_content(chunk_size=1 << 20):  # 1 MB chunks
                    tmp.write(chunk)
                    done += len(chunk)
                    if done % (100 << 20) == 0:
                        logger.info(f"  {done >> 20} MB / {size_mb} MB")

            tmp.flush()
            with zipfile.ZipFile(tmp_path, "r") as zf:
                for member in zf.namelist():
                    # Files are stored as "{ZIP_BASENAME}/{OID}_public.xml"
                    basename = member.rsplit("/", 1)[-1]
                    if basename in targets:
                        # Extract flat to out_dir (no subdirectory structure)
                        data = zf.read(member)
                        dest = out_dir / basename
                        dest.write_bytes(data)
                        oid = basename.replace("_public.xml", "")
                        extracted.add(oid)
                        logger.info(f"  Extracted {basename}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return extracted


# ---------------------------------------------------------------------------
# Mode 1 orchestration
# ---------------------------------------------------------------------------

def run_teos(years: list[int], target_eins: set[str],
             out_dir: Path, dry_run: bool = False) -> int:
    """
    Main Mode 1 pipeline: index → match EINs → probe ZIPs → extract XMLs.
    Returns number of XML files written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "project-jenni-990-pipeline/1.0"

    total_written = 0

    for year in sorted(years):
        logger.info(f"=== Year {year} ===")

        # 1. Fetch and filter index
        rows = fetch_index(year, session)
        hits = match_eins(rows, target_eins)
        if not hits:
            logger.info(f"  No matching EINs found in {year} index")
            continue
        logger.info(f"  Matched {len(hits)} institutions:")
        for h in hits:
            logger.info(f"    {h['TAXPAYER_NAME']}  EIN={h['EIN']}  "
                        f"TAX_PERIOD={h['TAX_PERIOD']}  OBJECT_ID={h['OBJECT_ID']}")

        if dry_run:
            continue

        # 2. Group by ZIP file
        zip_to_oids: dict[str, set[str]] = {}
        oid_to_row:  dict[str, dict]     = {}
        for h in hits:
            oid = h["OBJECT_ID"]
            xml_path = out_dir / f"{oid}_public.xml"
            if xml_path.exists():
                logger.info(f"  Already downloaded: {xml_path.name}")
                total_written += 1
                continue
            oid_to_row[oid] = h
            zip_fname = find_zip_for_object(session, year, oid)
            if zip_fname:
                zip_to_oids.setdefault(zip_fname, set()).add(oid)
            else:
                logger.error(f"  Could not locate ZIP for OBJECT_ID={oid} — skipping")

        # 3. Download each needed ZIP once and extract all matching files
        for zip_fname, oids in zip_to_oids.items():
            extracted = download_and_extract(session, year, zip_fname, oids, out_dir)
            total_written += len(extracted)
            missing = oids - extracted
            if missing:
                logger.warning(f"  Not found after extraction: {missing}")

    return total_written


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
        description="Download IRS Form 990 XML filings via TEOS portal"
    )
    parser.add_argument("--db",    help="Path to ipeds_data.db (loads EINs from institution_master)")
    parser.add_argument("--years", type=int, nargs="+", required=True,
                        help="Tax years to download (e.g. 2022 2023)")
    parser.add_argument("--ein",   nargs="+",
                        help="Specific EINs only (overrides --db; use 9-digit format)")
    parser.add_argument("--out",   default="data/raw/990_xml",
                        help="Output directory for XML files (default: data/raw/990_xml)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show matched filings without downloading")
    args = parser.parse_args()

    # Resolve target EINs
    if args.ein:
        target_eins = {_norm_ein(e) for e in args.ein}
        logger.info(f"Using {len(target_eins)} EINs from --ein flag")
    elif args.db:
        target_eins = load_eins_from_db(args.db)
        logger.info(f"Loaded {len(target_eins)} EINs from institution_master")
    else:
        target_eins = VALIDATION_EINS
        logger.info(f"Using {len(target_eins)} hardcoded validation EINs")

    out_dir = Path(args.out)
    n = run_teos(args.years, target_eins, out_dir, dry_run=args.dry_run)

    if args.dry_run:
        logger.info("Dry run complete — no files written")
    else:
        logger.info(f"Done — {n} XML file(s) in {out_dir}")


if __name__ == "__main__":
    main()
