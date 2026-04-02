#!/usr/bin/env python3
"""
ingestion/990/supplemental_runner.py
--------------------------------------
Run all five supplemental 990 parsers against all TEOS XML files in one pass.
Parsers run in sequence (each makes one pass over all XML files):

  1. schedule_d_parser   → form990_schedule_d     (endowment, Schedule D Part V)
  2. part_ix_parser      → form990_part_ix         (functional expenses, Part IX)
  3. compensation_parser → form990_compensation    (officer comp, Schedule J)
  4. schedule_r_parser   → form990_related_orgs    (related orgs, Schedule R)
                        → form990_related_transactions
  5. governance_parser   → form990_governance      (Part VI board/policy flags)
  6. part_viii_parser    → form990_part_viii       (revenue sub-lines, Part VIII Tier 1)

Designed to be idempotent: re-running replaces existing rows for each object_id.
Run this after any new XML files are downloaded (Zone 2, annual refresh, etc.).

Usage:
    .venv/bin/python3 ingestion/990/supplemental_runner.py \\
        --db  data/databases/990_data.db \\
        --xml data/raw/990_xml

    # Specific parsers only
    .venv/bin/python3 ingestion/990/supplemental_runner.py \\
        --db data/databases/990_data.db \\
        --parsers schedule_d part_ix compensation schedule_r governance
"""

import argparse
import importlib.util
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

HERE = Path(__file__).parent


def _load(name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PARSER_NAMES = ['schedule_d', 'part_ix', 'compensation', 'schedule_r', 'governance', 'part_viii']


def run_all(db: str, xml_dir: Path, parsers: list[str]) -> None:
    results = {}
    total_start = time.time()

    for name in parsers:
        logger.info(f"{'='*60}")
        logger.info(f"Running {name}_parser ...")
        t0 = time.time()
        try:
            mod = _load(f"{name}_parser")
            result = mod.run(db, xml_dir)
            elapsed = time.time() - t0
            results[name] = result
            logger.info(f"  {name}: done in {elapsed:.1f}s — {result}")
        except Exception as e:
            logger.error(f"  {name} FAILED: {e}", exc_info=True)
            results[name] = {'error': str(e)}

    elapsed = time.time() - total_start
    logger.info(f"{'='*60}")
    logger.info(f"Supplemental runner complete in {elapsed:.1f}s")
    logger.info("Summary:")
    for name, r in results.items():
        logger.info(f"  {name}: {r}")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("data/raw/990_xml/supplemental.log",
                                mode="a", encoding="utf-8"),
        ]
    )
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',      required=True)
    parser.add_argument('--xml',     default='data/raw/990_xml')
    parser.add_argument('--parsers', nargs='+', default=PARSER_NAMES,
                        choices=PARSER_NAMES,
                        help='Which parsers to run (default: all)')
    args = parser.parse_args()

    run_all(args.db, Path(args.xml), args.parsers)


if __name__ == '__main__':
    main()
