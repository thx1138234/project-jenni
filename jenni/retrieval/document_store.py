"""
jenni/retrieval/document_store.py
──────────────────────────────────────────────────────────────────────────────
Persistent store for JENNIDocument objects in the jenni_documents table.

Documents retrieved by any domain retriever are saved here so that:
  1. They can be retrieved in future sessions without re-querying.
  2. When the vector layer is enabled, the embedding column is populated
     and similarity search can query this table directly.

The database is initialised lazily on first write — no setup step needed.
"""
from __future__ import annotations

import json
import sqlite3

from jenni.config import DB_DOCUMENTS
from jenni.retrieval.base import JENNIDocument, RetrievalResult

_DDL = """
CREATE TABLE IF NOT EXISTS jenni_documents (
    doc_id              TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    domain              TEXT NOT NULL,
    content             TEXT NOT NULL,
    title               TEXT,
    url                 TEXT,
    retrieved_at        TEXT NOT NULL,
    institution_unitid  INTEGER,
    query               TEXT,
    embedding           BLOB
);
CREATE INDEX IF NOT EXISTS idx_jd_unitid ON jenni_documents(institution_unitid);
CREATE INDEX IF NOT EXISTS idx_jd_source ON jenni_documents(source);
CREATE INDEX IF NOT EXISTS idx_jd_domain ON jenni_documents(domain);
"""


class DocumentStore:
    """Thin SQLite wrapper for jenni_documents persistence."""

    def __init__(self) -> None:
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(DB_DOCUMENTS))
        conn.executescript(_DDL)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_DOCUMENTS))
        conn.row_factory = sqlite3.Row
        return conn

    def save_document(self, doc: JENNIDocument) -> None:
        """Insert or replace a JENNIDocument."""
        embedding_blob = None
        if doc.embedding is not None:
            embedding_blob = json.dumps(doc.embedding).encode()
        conn = self._conn()
        conn.execute("""
            INSERT OR REPLACE INTO jenni_documents
                (doc_id, source, domain, content, title, url,
                 retrieved_at, institution_unitid, query, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc.doc_id, doc.source, doc.domain, doc.content,
            doc.title, doc.url, doc.retrieved_at,
            doc.institution_unitid, doc.query, embedding_blob,
        ))
        conn.commit()
        conn.close()

    def save_result(self, result: RetrievalResult) -> None:
        """Persist all documents in a RetrievalResult."""
        for doc in result.documents:
            self.save_document(doc)

    def get_by_unitid(self, unitid: int) -> list[JENNIDocument]:
        """Retrieve all persisted documents for an institution."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM jenni_documents WHERE institution_unitid = ? "
            "ORDER BY retrieved_at DESC",
            (unitid,),
        ).fetchall()
        conn.close()
        return [_row_to_doc(r) for r in rows]


def _row_to_doc(row: sqlite3.Row) -> JENNIDocument:
    embedding = None
    if row["embedding"]:
        try:
            embedding = json.loads(row["embedding"].decode())
        except Exception:
            pass
    return JENNIDocument(
        doc_id=row["doc_id"],
        source=row["source"],
        domain=row["domain"],
        content=row["content"],
        title=row["title"] or "",
        url=row["url"],
        retrieved_at=row["retrieved_at"],
        institution_unitid=row["institution_unitid"],
        query=row["query"] or "",
        embedding=embedding,
    )
