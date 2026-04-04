-- schema/learning_schema.sql
-- Learning layer tables for 990_data.db
-- Applied to: data/databases/990_data.db
--
-- jenni_institutional_insights: validated per-institution insights
-- jenni_patterns: cross-institutional patterns (5+ distinct unitids)
--
-- Rebuild: apply this SQL against 990_data.db, then run
--   python3 ingestion/learning/seed_loader.py --db data/databases/990_data.db

CREATE TABLE IF NOT EXISTS jenni_institutional_insights (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    unitid              INTEGER NOT NULL,
    institution_name    TEXT NOT NULL,
    insight_text        TEXT NOT NULL,
    evidence_tier       INTEGER NOT NULL,
    confidence          TEXT NOT NULL,       -- 'high' | 'medium' | 'low'
    source_tables       TEXT,                -- comma-separated table names
    fiscal_year_end     INTEGER,
    insight_type        TEXT,                -- 'trajectory' | 'structural' | 'financial_position' | ...
    status              TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'superseded' | 'rejected'
    superseded_by       INTEGER,             -- FK to id of replacement insight
    extraction_method   TEXT NOT NULL DEFAULT 'seeded',  -- 'seeded' | 'model_extracted' | 'curator_promoted'
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (unitid, insight_text),
    FOREIGN KEY (superseded_by) REFERENCES jenni_institutional_insights(id)
);

CREATE INDEX IF NOT EXISTS idx_jii_unitid
    ON jenni_institutional_insights(unitid);

CREATE INDEX IF NOT EXISTS idx_jii_status
    ON jenni_institutional_insights(status);

-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS jenni_patterns (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_text        TEXT NOT NULL UNIQUE,
    supporting_unitids  TEXT,                -- JSON array of unitids
    institution_count   INTEGER,
    evidence_tier       INTEGER,
    confidence          TEXT,                -- 'high' | 'medium' | 'low'
    status              TEXT DEFAULT 'candidate',  -- 'candidate' | 'active' | 'rejected'
    pattern_type        TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
