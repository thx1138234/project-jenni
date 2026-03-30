-- jenni_documents: persistent store for all retrieved documents
-- Used by JENNISearchLayer across all domain retrievers (SQL, web, narrative).
--
-- embedding column is NULL until the vector layer is enabled.
-- When vector search is activated, populate embedding with a JSON-encoded
-- float list before inserting; similarity search queries this column directly.
--
-- One row per unique document (doc_id = MD5 of source:unitid:suffix or url).
-- INSERT OR REPLACE semantics — safe to re-insert on duplicate retrieval.

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
