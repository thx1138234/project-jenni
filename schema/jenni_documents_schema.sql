-- jenni_documents: persistent store for all retrieved documents
-- Used by JENNISearchLayer across all domain retrievers (SQL, web, narrative).
--
-- embedding column is NULL until the vector layer is enabled.
-- When vector search is activated, populate embedding with a JSON-encoded
-- float list before inserting; similarity search queries this column directly.
--
-- One row per unique document (doc_id = MD5 of source:unitid:suffix or url).
-- INSERT OR REPLACE semantics — safe to re-insert on duplicate retrieval.

-- jenni_query_log: every synthesize() call, success or failure
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
CREATE INDEX IF NOT EXISTS idx_qlog_timestamp  ON jenni_query_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_qlog_query_type ON jenni_query_log(query_type);

-- jenni_documents: retrieved documents from all retrieval backends
CREATE TABLE IF NOT EXISTS jenni_documents (
    doc_id              TEXT PRIMARY KEY,
    source              TEXT NOT NULL,       -- 'sql' | 'web' | 'news' | 'narrative'
    domain              TEXT NOT NULL,       -- 'institution' | 'web' | 'news' | 'narrative'
    content             TEXT NOT NULL,
    title               TEXT,
    url                 TEXT,
    retrieved_at        TEXT NOT NULL,       -- ISO 8601 UTC (e.g. 2026-03-30T14:22:00+00:00)
    institution_unitid  INTEGER,             -- NULL for sector-level web results
    query               TEXT,               -- originating query for audit trail
    embedding           BLOB                 -- NULL until vector layer enabled
                                             -- format: JSON-encoded float array
);

CREATE INDEX IF NOT EXISTS idx_jd_unitid ON jenni_documents(institution_unitid);
CREATE INDEX IF NOT EXISTS idx_jd_source ON jenni_documents(source);
CREATE INDEX IF NOT EXISTS idx_jd_domain ON jenni_documents(domain);
