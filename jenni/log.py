"""
jenni/log.py
──────────────────────────────────────────────────────────────────────────────
Query-level observability for the JENNI intelligence layer.

Every API call through synthesize() is logged to jenni_query_log in the
jenni_documents database — on successful completion and on failure.  The log
is the primary instrument for monitoring quality, latency, and cost in
production.

Schema (jenni_query_log):
    query_id          TEXT PRIMARY KEY  — ISO timestamp + 6-char hex suffix
    query_text        TEXT              — raw user query
    query_type        TEXT              — analysis|comparison|trend|stress|sector|data
    institutions      TEXT              — JSON list of matched institution names
    model_used        TEXT              — model ID (e.g. claude-sonnet-4-6)
    tokens_in         INTEGER
    tokens_out        INTEGER
    latency_ms        INTEGER           — wall-clock ms from API call start to response
    completeness      REAL              — data_quality.completeness_pct (NULL on error)
    accordion_position TEXT             — accordion zone (e.g. 'center')
    error             TEXT              — NULL on success; exception message on failure
    timestamp         TEXT              — DEFAULT datetime('now') UTC
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone

from jenni.config import DB_DOCUMENTS

_DDL = """
CREATE TABLE IF NOT EXISTS jenni_query_log (
    query_id           TEXT PRIMARY KEY,
    query_text         TEXT,
    query_type         TEXT,
    institutions       TEXT,
    model_used         TEXT,
    tokens_in          INTEGER,
    tokens_out         INTEGER,
    latency_ms         INTEGER,
    resolver_ms        INTEGER,
    db_query_ms        INTEGER,
    synthesizer_ms     INTEGER,
    delivery_ms        INTEGER,
    completeness       REAL,
    accordion_position TEXT,
    error              TEXT,
    timestamp          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_qlog_timestamp ON jenni_query_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_qlog_query_type ON jenni_query_log(query_type);
"""

# Columns added after initial schema — applied idempotently via ALTER TABLE
_MIGRATIONS = [
    "ALTER TABLE jenni_query_log ADD COLUMN resolver_ms    INTEGER",
    "ALTER TABLE jenni_query_log ADD COLUMN db_query_ms    INTEGER",
    "ALTER TABLE jenni_query_log ADD COLUMN synthesizer_ms INTEGER",
    "ALTER TABLE jenni_query_log ADD COLUMN delivery_ms    INTEGER",
]


def _ensure_table() -> None:
    conn = sqlite3.connect(str(DB_DOCUMENTS))
    conn.executescript(_DDL)
    # Apply any migrations that haven't landed yet (idempotent)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except Exception:
            pass  # column already exists
    conn.commit()
    conn.close()


# Initialise table once at import time
_ensure_table()


def _query_id() -> str:
    """Return a unique query ID: ISO timestamp + 6-char hex nonce."""
    now = datetime.now(timezone.utc)
    nonce = format(int(now.timestamp() * 1000) % 0xFFFFFF, "06x")
    return now.strftime("%Y%m%dT%H%M%S") + "_" + nonce


def log_query(
    *,
    context: dict,
    model_used: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    resolver_ms: int = 0,
    db_query_ms: int = 0,
    synthesizer_ms: int = 0,
    delivery_ms: int = 0,
    error: str | None = None,
) -> str:
    """
    Write one row to jenni_query_log.

    Parameters
    ----------
    context        : full context package from query_resolver
    model_used     : model ID string
    tokens_in      : input tokens billed
    tokens_out     : output tokens billed
    latency_ms     : total wall-clock latency (resolver + synthesizer + delivery)
    resolver_ms    : time in assemble_context() (entity match + DB queries)
    db_query_ms    : time for SQLite queries specifically within assemble_context()
    synthesizer_ms : time for the Claude API call
    delivery_ms    : time for render_response() or to_json()
    error          : None on success; exception message on failure

    Returns
    -------
    query_id string (for correlation with application logs)
    """
    query_id = _query_id()

    institutions = json.dumps([
        e.get("institution_name", "")
        for e in context.get("entities", [])
    ])

    dq = context.get("data_quality") or {}
    completeness = dq.get("completeness_pct")

    accordion = context.get("accordion") or {}
    accordion_position = accordion.get("zone")

    try:
        conn = sqlite3.connect(str(DB_DOCUMENTS))
        conn.execute("""
            INSERT INTO jenni_query_log
                (query_id, query_text, query_type, institutions, model_used,
                 tokens_in, tokens_out, latency_ms,
                 resolver_ms, db_query_ms, synthesizer_ms, delivery_ms,
                 completeness, accordion_position, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            query_id,
            context.get("query", ""),
            context.get("query_type", ""),
            institutions,
            model_used,
            tokens_in,
            tokens_out,
            latency_ms,
            resolver_ms,
            db_query_ms,
            synthesizer_ms,
            delivery_ms,
            completeness,
            accordion_position,
            error,
        ))
        conn.commit()
        conn.close()
    except Exception:
        # Logging failures must never surface to the user
        pass

    return query_id
