#!/usr/bin/env python3
"""
ingestion/eada/downloader.py
-----------------------------
Downloads EADA InstLevel ZIP files from the OPE portal.

Source:
    File list: https://ope.ed.gov/athletics/api/dataFiles/fileList
    Download:  https://ope.ed.gov/athletics/api/dataFiles/file?fileName={name}

Each year ships as EADA_YYYY-YYYY.zip (or "EADA YYYY-YYYY.zip" pre-2017).
We download only the primary per-year ZIP (not the combined SAS/SPSS/EXCEL bundles).

Downloaded ZIPs land in out_dir. Already-downloaded files are skipped unless
--force is specified.

Usage:
    python3 ingestion/eada/downloader.py --out-dir data/raw/eada_csv
    python3 ingestion/eada/downloader.py --out-dir data/raw/eada_csv --year 2023
    python3 ingestion/eada/downloader.py --out-dir data/raw/eada_csv --force
"""

import argparse
import logging
import time
from pathlib import Path
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

FILE_LIST_URL = "https://ope.ed.gov/athletics/api/dataFiles/fileList"
DOWNLOAD_URL  = "https://ope.ed.gov/athletics/api/dataFiles/file?fileName={name}"
RATE_LIMIT    = 1.0  # seconds between requests


def _is_primary_zip(filename: str) -> bool:
    """Return True for the primary per-year ZIP (not combined SAS/SPSS bundles)."""
    fn = filename.lower()
    return fn.startswith("eada") and fn.endswith(".zip") and "combined" not in fn and "all_data" not in fn and "all data" not in fn


def fetch_file_list(session: requests.Session) -> list[dict]:
    """Return the full file-list JSON from the OPE API."""
    resp = session.get(FILE_LIST_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def download_year(session: requests.Session, filename: str, out_dir: Path,
                  force: bool = False) -> bool:
    """
    Download one EADA ZIP into out_dir.
    Returns True if downloaded, False if skipped (already exists).
    """
    dest = out_dir / filename
    if dest.exists() and not force:
        logger.info(f"  Already downloaded: {filename}")
        return False

    url = DOWNLOAD_URL.format(name=quote(filename))
    logger.info(f"  Downloading {filename} …")
    resp = session.get(url, timeout=120)
    resp.raise_for_status()

    dest.write_bytes(resp.content)
    logger.info(f"  Saved {filename} ({len(resp.content) / 1_048_576:.1f} MB)")
    return True


def run(out_dir: Path, target_year: int | None = None,
        force: bool = False) -> list[Path]:
    """
    Download EADA primary ZIPs for all available years (or one specific year).
    Returns list of paths to downloaded ZIPs.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = "project-jenni-eada-downloader/1.0"

    file_list = fetch_file_list(session)

    # Filter to primary ZIPs only, optionally to one year
    targets = [
        entry for entry in file_list
        if _is_primary_zip(entry["FileName"])
        and (target_year is None or entry["Year"] == target_year)
    ]
    targets.sort(key=lambda e: e["Year"])

    logger.info(f"EADA DOWNLOAD — {len(targets)} file(s) to process")

    downloaded = []
    for i, entry in enumerate(targets):
        fn   = entry["FileName"]
        yr   = entry["Year"]
        logger.info(f"[{i+1}/{len(targets)}] Year {yr}: {fn}")
        wrote = download_year(session, fn, out_dir, force=force)
        if wrote:
            downloaded.append(out_dir / fn)
            if i < len(targets) - 1:
                time.sleep(RATE_LIMIT)

    logger.info(f"Download complete — {len(downloaded)} new file(s)")
    return downloaded


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Download EADA InstLevel ZIPs")
    parser.add_argument("--out-dir", default="data/raw/eada_csv",
                        help="Directory for downloaded ZIPs")
    parser.add_argument("--year", type=int, default=None,
                        help="Download only this end-year (e.g. 2023 for AY 2022-23)")
    parser.add_argument("--force", action="store_true",
                        help="Re-download files that already exist")
    args = parser.parse_args()

    run(Path(args.out_dir), target_year=args.year, force=args.force)


if __name__ == "__main__":
    main()
