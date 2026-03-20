#!/usr/bin/env python3
"""
downloader.py
-------------
Fetches IPEDS bulk CSV files from NCES and extracts them into data/raw/ipeds_csv/.

Handles all IPEDS file naming quirks documented in CLAUDE.md:
  - EF component has 4 parts (A, B, C, D); Part C is even years only
  - SFA files use two-year naming: SFA2223.zip for survey_year 2022
  - Finance files split by framework: F2223_F1A.zip (FASB) and F2223_F2.zip (GASB)
  - ADM is standalone from survey_year 2014 only
  - E12 files used prefix EF12 before 2012, then changed to EFIA

Tracks download state in data/raw/ipeds_csv/manifest.json.
Skips files already successfully downloaded. Safe to re-run.

Usage:
    python downloader.py                              # All components, all years
    python downloader.py --component IC EF ADM        # Specific components
    python downloader.py --year 2022 2023             # Specific years
    python downloader.py --component IC --year 2022   # Combined filter
    python downloader.py --dry-run                    # Show what would download
"""

import os
import io
import json
import time
import logging
import argparse
import zipfile
from pathlib import Path
from datetime import datetime

try:
    import requests
except ImportError:
    raise SystemExit("requests is required: pip install requests")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://nces.ed.gov/ipeds/datacenter/data"
RAW_DIR  = Path(__file__).parent.parent.parent / "data" / "raw" / "ipeds_csv"
MANIFEST = RAW_DIR / "manifest.json"

# Survey years to cover: fall start year (survey_year = fall of academic year)
DEFAULT_YEAR_RANGE = range(2000, 2025)

# Delay between requests to be polite to NCES servers
REQUEST_DELAY_SECONDS = 1.5

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File Name Generators
# Per-component logic for building the NCES zip filename for a given year.
# Returns list of candidate filenames in priority order.
# ---------------------------------------------------------------------------

def _yr(year):
    """'2022' -> '22'"""
    return str(year)[-2:]

def _yr2(year):
    """Two-year suffix: 2022 -> '2223'"""
    return f"{_yr(year)}{_yr(year + 1)}"


COMPONENT_FILES = {
    # Header/Directory — institutional metadata (name, control, Carnegie, EIN, OPEID)
    # This is the source for institution_master; distinct from IC (tuition/programs)
    "HD": lambda year: [f"HD{year}.zip", f"hd{year}.zip"],

    # Institutional Characteristics — program offerings, calendar
    "IC": lambda year: [f"IC{year}.zip", f"ic{year}.zip"],

    # IC Academic Year charges — tuition, fees, room & board
    # Separate file from IC; both needed for a complete ipeds_ic row
    "IC_AY": lambda year: [f"IC{year}_AY.zip", f"ic{year}_ay.zip"],

    # Fall Enrollment — 4 parts. Part C (residence) is even years only.
    "EF_A": lambda year: [f"EF{year}A.zip", f"ef{year}a.zip"],
    "EF_B": lambda year: [f"EF{year}B.zip", f"ef{year}b.zip"],
    "EF_C": lambda year: [f"EF{year}C.zip"] if year % 2 == 0 else [],  # Even years only
    "EF_D": lambda year: [f"EF{year}D.zip", f"ef{year}d.zip"],

    # Admissions — standalone from 2014; skip earlier years
    "ADM": lambda year: (
        [f"ADM{year}.zip", f"adm{year}.zip"] if year >= 2014 else []
    ),

    # Completions
    "C": lambda year: [
        f"C{year}_A.zip",
        f"c{year}_a.zip",
        f"C{year}A.zip",
    ],

    # Graduation Rates
    "GR": lambda year: [f"GR{year}.zip", f"gr{year}.zip"],

    # Student Financial Aid — two-year naming
    "SFA": lambda year: [
        f"SFA{_yr2(year)}.zip",
        f"sfa{_yr2(year)}.zip",
    ],

    # Finance — FASB (private) and GASB (public) are separate files
    "F_FASB": lambda year: [
        f"F{_yr2(year)}_F1A.zip",
        f"f{_yr2(year)}_f1a.zip",
        f"F{_yr2(year)}_F1A23.zip",   # Some years have extra suffix
    ],
    "F_GASB": lambda year: [
        f"F{_yr2(year)}_F2.zip",
        f"f{_yr2(year)}_f2.zip",
    ],

    # Human Resources — NCES splits into two files (no single HR{year}.zip):
    #   S{year}_SIS.zip  → fall staff survey (instructional staff counts by rank)
    #   SAL{year}_IS.zip → instructional staff salaries
    "HR_SIS": lambda year: [f"S{year}_SIS.zip", f"s{year}_sis.zip"],
    "HR_SAL": lambda year: [f"SAL{year}_IS.zip", f"sal{year}_is.zip"],

    # 12-Month Enrollment — naming changed in 2012
    "E12": lambda year: (
        [f"EF12{year}.zip"] if year < 2012
        else [f"EFIA{year}.zip", f"efia{year}.zip"]
    ),

    # Graduation Rates 200%
    "GR200": lambda year: [f"GR200_{year}.zip", f"GR{year}_200.zip"],

    # Outcome Measures
    "OM": lambda year: [f"OM{year}.zip"],

    # Academic Libraries
    "AL": lambda year: [f"AL{year}.zip"],
}

# Logical component groups (what the user specifies on the CLI)
COMPONENT_GROUPS = {
    "HD":    ["HD"],
    "IC":    ["IC", "IC_AY"],
    "EF":    ["EF_A", "EF_B", "EF_C", "EF_D"],
    "ADM":   ["ADM"],
    "C":     ["C"],
    "GR":    ["GR"],
    "SFA":   ["SFA"],
    "F":     ["F_FASB", "F_GASB"],
    "HR":    ["HR_SIS", "HR_SAL"],
    "E12":   ["E12"],
    "GR200": ["GR200"],
    "OM":    ["OM"],
    "AL":    ["AL"],
}

DEFAULT_COMPONENTS = ["HD", "IC", "EF", "ADM", "C", "GR", "SFA", "F", "HR"]


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_manifest():
    """Load the download state tracker."""
    if MANIFEST.exists():
        with open(MANIFEST) as f:
            return json.load(f)
    return {}


def save_manifest(manifest):
    """Persist the download state tracker."""
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)


def manifest_key(file_key, year):
    return f"{file_key}:{year}"


# ---------------------------------------------------------------------------
# Download & Extraction
# ---------------------------------------------------------------------------

def download_file(url, timeout=120):
    """
    Download a file from url. Returns (content_bytes, True) on success,
    (None, False) on 404, raises on other errors.
    """
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        if resp.status_code == 404:
            return None, False
        resp.raise_for_status()
        return resp.content, True
    except requests.exceptions.RequestException as e:
        logger.error(f"Download error for {url}: {e}")
        raise


def extract_zip(content_bytes, dest_dir):
    """Extract a zip from bytes into dest_dir. Returns list of extracted filenames."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(io.BytesIO(content_bytes)) as zf:
        for name in zf.namelist():
            # Extract only CSV files
            if name.lower().endswith(".csv"):
                zf.extract(name, dest_dir)
                extracted.append(name)
                logger.debug(f"  Extracted: {name}")
    return extracted


def fetch_component_year(file_key, year, dest_dir, dry_run=False):
    """
    Try each candidate filename for a given file_key/year.
    Returns (filename_used, status) where status is:
      'downloaded', 'not_found', 'skipped_empty', 'dry_run'
    """
    candidates = COMPONENT_FILES[file_key](year)
    if not candidates:
        logger.debug(f"{file_key} {year}: no candidates (expected — check CLAUDE.md)")
        return None, "no_candidates"

    for filename in candidates:
        url = f"{BASE_URL}/{filename}"

        if dry_run:
            logger.info(f"  [DRY RUN] Would fetch: {url}")
            return filename, "dry_run"

        logger.debug(f"  Trying: {url}")
        content, found = download_file(url)

        if not found:
            continue

        if len(content) < 500:
            # Some NCES 404-equivalent responses return 200 with tiny error HTML
            logger.warning(f"{file_key} {year}: {filename} appears empty ({len(content)} bytes)")
            return filename, "skipped_empty"

        extracted = extract_zip(content, dest_dir)
        if not extracted:
            logger.warning(f"{file_key} {year}: zip contained no CSVs")
            return filename, "no_csv_in_zip"

        logger.info(f"{file_key} {year}: downloaded {filename} → {extracted}")
        return filename, "downloaded"

    logger.debug(f"{file_key} {year}: not found at NCES (may not exist for this year)")
    return None, "not_found"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def download_all(components=None, years=None, dry_run=False, force=False):
    """
    Main download loop. Respects manifest to skip already-downloaded files.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    if components is None:
        components = DEFAULT_COMPONENTS
    if years is None:
        years = list(DEFAULT_YEAR_RANGE)

    # Expand component groups to individual file keys
    file_keys = []
    for comp in components:
        if comp in COMPONENT_GROUPS:
            file_keys.extend(COMPONENT_GROUPS[comp])
        elif comp in COMPONENT_FILES:
            file_keys.append(comp)
        else:
            logger.warning(f"Unknown component: {comp} — skipping")

    manifest = load_manifest()

    stats = {"downloaded": 0, "skipped": 0, "not_found": 0, "errors": 0}

    for file_key in file_keys:
        for year in sorted(years):
            key = manifest_key(file_key, year)

            if not force and manifest.get(key, {}).get("status") == "downloaded":
                logger.debug(f"{file_key} {year}: already downloaded, skipping")
                stats["skipped"] += 1
                continue

            dest_dir = RAW_DIR / _component_dir(file_key) / str(year)

            try:
                filename, status = fetch_component_year(file_key, year, dest_dir, dry_run)

                if not dry_run:
                    manifest[key] = {
                        "status": status,
                        "filename": filename,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    save_manifest(manifest)

                if status == "downloaded":
                    stats["downloaded"] += 1
                elif status == "not_found":
                    stats["not_found"] += 1
                    logger.debug(f"{file_key} {year}: not on NCES server")
                elif status == "dry_run":
                    stats["downloaded"] += 1  # count as "would download"
                else:
                    stats["skipped"] += 1

            except Exception as e:
                logger.error(f"{file_key} {year}: ERROR — {e}")
                stats["errors"] += 1
                if not dry_run:
                    manifest[key] = {
                        "status": "error",
                        "error": str(e),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    save_manifest(manifest)

            if not dry_run:
                time.sleep(REQUEST_DELAY_SECONDS)

    label = "Would download" if dry_run else "Downloaded"
    logger.info(
        f"\n{'='*60}\n"
        f"{label}: {stats['downloaded']}  |  "
        f"Skipped (cached): {stats['skipped']}  |  "
        f"Not on NCES: {stats['not_found']}  |  "
        f"Errors: {stats['errors']}"
    )
    return stats


def _component_dir(file_key):
    """Map file key to subdirectory name (matches what loader.py expects)."""
    mapping = {
        "HD":     "HD",
        "IC":     "IC",
        "IC_AY":  "IC",    # IC_AY extracts into the same IC directory as IC
        "EF_A":   "EF",
        "EF_B":   "EF",
        "EF_C":   "EF",
        "EF_D":   "EF",
        "ADM":    "ADM",
        "C":      "C",
        "GR":     "GR",
        "SFA":    "SFA",
        "F_FASB": "F",
        "F_GASB": "F",
        "HR_SIS": "HR",
        "HR_SAL": "HR",
        "E12":    "E12",
        "GR200":  "GR200",
        "OM":     "OM",
        "AL":     "AL",
    }
    return mapping.get(file_key, file_key)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download IPEDS bulk CSV files from NCES"
    )
    parser.add_argument(
        "--component", nargs="+",
        choices=list(COMPONENT_GROUPS.keys()),
        help=f"Components to download. Default: {DEFAULT_COMPONENTS}"
    )
    parser.add_argument(
        "--year", nargs="+", type=int,
        help="Specific survey years to download (fall start year, e.g., 2022)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be downloaded without actually downloading"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-download even if already in manifest"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    stats = download_all(
        components=args.component,
        years=args.year,
        dry_run=args.dry_run,
        force=args.force,
    )

    exit(1 if stats["errors"] > 0 else 0)
