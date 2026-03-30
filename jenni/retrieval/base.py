"""
jenni/retrieval/base.py
──────────────────────────────────────────────────────────────────────────────
Abstract retrieval interfaces and shared data structures for the JENNI search
layer.  All retrieval backends return RetrievalResult envelopes containing
JENNIDocument objects so the synthesizer never needs to know how data was
fetched.

Vector-readiness: JENNIDocument.embedding is present but set to None until
the vector backend is enabled.  The field is part of the core dataclass so
every document is vector-ready without a future schema migration.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JENNIDocument:
    """
    A single retrieved document from any source (SQL, web, narrative).

    embedding is None until vector indexing is enabled.  When the vector
    layer is activated, populate this field with the document's embedding
    before inserting into jenni_documents; the store will persist it as a
    BLOB column ready for similarity search.
    """
    doc_id: str                              # unique within source+domain
    source: str                              # 'sql' | 'web' | 'news' | 'narrative'
    domain: str                              # 'institution' | 'web' | 'news' | 'narrative'
    content: str                             # primary text payload
    title: str = ""
    url: Optional[str] = None               # for web/news; None for SQL-sourced
    retrieved_at: str = ""                  # ISO 8601 UTC timestamp
    institution_unitid: Optional[int] = None
    query: str = ""                         # originating query
    embedding: Optional[list[float]] = None  # None = vector not yet computed


@dataclass
class RetrievalResult:
    """
    Standard envelope for all retrieval results regardless of source.

    The synthesizer receives a merged list of RetrievalResult objects and
    does not need to know which backend produced each document.  Source is
    always visible via JENNIDocument.source and .domain fields.
    """
    query: str
    domain: str                              # 'institution' | 'web' | 'news' | 'narrative'
    documents: list[JENNIDocument] = field(default_factory=list)
    retrieval_time_ms: float = 0.0
    metadata: dict = field(default_factory=dict)


class InstitutionRetriever(ABC):
    """
    Abstract base class for institution retrieval backends.

    Subclasses implement SQL-backed, vector-backed, or hybrid retrieval.
    The public interface is stable; swapping backends requires only updating
    JENNISearchLayer without touching the synthesizer or query resolver.
    """

    @abstractmethod
    def find_institutions(self, query: str, max_results: int = 3) -> RetrievalResult:
        """
        Match institution names mentioned in the query.

        Returns institutions from institution_master (SQL) or a vector index
        (future), wrapped in RetrievalResult.
        """

    @abstractmethod
    def find_similar(self, unitid: int, max_results: int = 5) -> RetrievalResult:
        """
        Find institutions in the same Carnegie peer group as unitid.
        """

    @abstractmethod
    def find_documents(
        self,
        query: str,
        unitid: Optional[int] = None,
        max_results: int = 10,
    ) -> RetrievalResult:
        """
        Retrieve relevant documents for the query, optionally scoped to a
        specific institution.  Returns narrative text, financial summaries,
        or other structured text depending on the backend.
        """
