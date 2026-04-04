"""
jenni/learning/pattern_agent.py
---------------------------------
Weekly pattern detection across jenni_institutional_insights.

Phase 1: keyword co-occurrence across 5+ distinct institutions.
Generates candidate patterns with confidence='low' for human curation.

Phase 2 (PostgreSQL migration): replace keyword grouping with
embedding similarity — architecture is identical, only the grouping
logic changes. No schema migration required.

Usage:
    .venv/bin/python3 -m jenni.learning.pattern_agent \\
        --db data/databases/990_data.db
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone


def detect_patterns(db_conn: sqlite3.Connection) -> list[dict]:
    """
    Find insight_text patterns appearing across 5+ distinct institutions.
    Generates candidate patterns with confidence='low' for human curation.

    Phase 1: groups by insight_type — keyword co-occurrence across institutions.
    Phase 2 upgrade point: replace type grouping with embedding similarity.
    """
    rows = db_conn.execute("""
        SELECT unitid, insight_text, insight_type
        FROM jenni_institutional_insights
        WHERE status = 'active'
        ORDER BY insight_type, unitid
    """).fetchall()

    # Group by insight_type, look for common occurrence across 5+ distinct unitids
    type_groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for unitid, text, itype in rows:
        type_groups[itype or 'unknown'].append((unitid, text))

    candidates = []
    for itype, items in type_groups.items():
        unitids = list({unitid for unitid, _ in items})
        if len(unitids) >= 5:
            # Summarise the shared signal as the first insight_text in the group
            # Phase 2: replace with centroid of embeddings
            sample_text = items[0][1] if items else ''
            candidates.append({
                'pattern_type':       itype,
                'supporting_unitids': unitids[:20],
                'institution_count':  len(unitids),
                'confidence':         'low',
                'status':             'candidate',
                'pattern_text':       (
                    f"Cross-institutional {itype} pattern observed across "
                    f"{len(unitids)} institutions. "
                    f"Sample: {sample_text[:120]}"
                ),
            })
    return candidates


def store_patterns(
    db_conn: sqlite3.Connection,
    candidates: list[dict],
) -> int:
    """
    Write candidate patterns to jenni_patterns.
    Uses INSERT OR IGNORE — safe to re-run weekly.
    """
    now = datetime.now(timezone.utc).isoformat()
    stored = 0
    for c in candidates:
        db_conn.execute("""
            INSERT OR IGNORE INTO jenni_patterns
                (pattern_text, supporting_unitids, institution_count,
                 evidence_tier, confidence, status, pattern_type,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c['pattern_text'],
            json.dumps(c['supporting_unitids']),
            c['institution_count'],
            2,   # cross-validated inference
            c['confidence'],
            c['status'],
            c['pattern_type'],
            now,
            now,
        ))
        stored += 1
    db_conn.commit()
    return stored


def run(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    candidates = detect_patterns(conn)
    stored = store_patterns(conn, candidates)
    conn.close()
    return {'candidates_detected': len(candidates), 'patterns_stored': stored}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='data/databases/990_data.db')
    args = parser.parse_args()
    result = run(args.db)
    print(result)
