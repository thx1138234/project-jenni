"""
ingestion/learning/seed_loader.py
-----------------------------------
One-time loader: writes validated seed insights from seed_insights.py
into jenni_institutional_insights in 990_data.db.

All seeds are Tier 1 evidence (institution_trajectories + federal data).
They pass validation by construction — run through JENNIInsightValidator
to confirm and to set confidence/tier correctly.

Usage:
    .venv/bin/python3 ingestion/learning/seed_loader.py \\
        --db data/databases/990_data.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingestion.learning.seed_insights import SEED_INSIGHTS
from jenni.learning.validator import JENNIInsightValidator


def load_seeds(db_path: str) -> int:
    validator = JENNIInsightValidator()
    conn = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    stored = 0
    rejected = 0

    for seed in SEED_INSIGHTS:
        result = validator.validate(seed, context={})
        if not result.approved:
            print(f"  REJECTED unitid={seed['unitid']}: {result.rejection_reason}")
            rejected += 1
            continue

        conn.execute("""
            INSERT OR IGNORE INTO jenni_institutional_insights
                (unitid, institution_name, insight_text,
                 evidence_tier, confidence, source_tables,
                 fiscal_year_end, insight_type,
                 extraction_method, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            seed['unitid'],
            seed['institution_name'],
            seed['insight_text'],
            result.evidence_tier,
            seed.get('confidence', result.confidence),
            seed.get('source_tables', ''),
            seed.get('fiscal_year_end'),
            'trajectory',
            'seeded',
            now,
            now,
        ))
        stored += 1
        print(f"  STORED  unitid={seed['unitid']} "
              f"({seed['institution_name']}) "
              f"tier={result.evidence_tier} confidence={result.confidence}")

    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) FROM jenni_institutional_insights"
    ).fetchone()[0]
    conn.close()

    print(f"\nSeed load complete: {stored} stored, {rejected} rejected")
    print(f"Total rows in jenni_institutional_insights: {total}")
    return stored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='data/databases/990_data.db')
    args = parser.parse_args()
    load_seeds(args.db)


if __name__ == '__main__':
    main()
