"""
jenni/retrieval/search_layer.py
──────────────────────────────────────────────────────────────────────────────
JENNISearchLayer — top-level orchestrator for the modular retrieval layer.

Architecture
────────────
Four domain retrievers, each independently swappable:

  institution  SQLRetriever  fuzzy name matching, Carnegie peer groups
  web          WebRetriever  current news via Anthropic web_search tool
  news         WebRetriever  aliased to web; extensible to dedicated news API
  narrative    SQLRetriever  pre-encoded institution_narratives

The search layer activates selectively based on query content:
  - SQL retrieval always active (institution + narrative domains)
  - Web retrieval activates when the query has a current-events dimension

Synthesizer protocol
────────────────────
search() returns list[RetrievalResult].  The synthesizer merges these and
does NOT need to know which backend produced each document.  Source is always
visible via JENNIDocument.source and .domain fields.
"""
from __future__ import annotations

import re
from typing import Optional

from jenni.retrieval.base import InstitutionRetriever, RetrievalResult
from jenni.retrieval.document_store import DocumentStore
from jenni.retrieval.sql_retriever import SQLRetriever
from jenni.retrieval.web_retriever import WebRetriever

# ── Current-events trigger ─────────────────────────────────────────────────
_CURRENT_EVENTS_WORDS = {
    "recent", "recently", "news", "latest", "current", "today",
    "announced", "announcement", "appointment", "appointed", "launched",
    "new", "closed", "closing", "merger", "acquired", "acquisition",
    "accreditation", "leadership", "president", "chancellor", "provost",
    "ranking", "tuition", "enrollment", "budget", "deficit", "layoffs",
    "program", "campus", "strike", "protest",
}
_CURRENT_EVENTS_PHRASES = (
    "what happened",
    "what's new",
    "tell me about",
    "recent news",
    "latest news",
    "in the news",
    "this year",
    "last year",
    "financial health",    # often implies wanting current picture
)
# Year patterns forward of the database window: 2024, 2025, 2026, …
_YEAR_PATTERN = re.compile(r"\b20(2[4-9]|[3-9]\d)\b")


def needs_web_search(query: str) -> bool:
    """
    Return True when the query has a current-events or recent-news dimension
    that warrants activating the web retriever alongside SQL retrieval.
    """
    q = query.lower()
    tokens = set(q.split())
    if _CURRENT_EVENTS_WORDS & tokens:
        return True
    if any(p in q for p in _CURRENT_EVENTS_PHRASES):
        return True
    if _YEAR_PATTERN.search(query):
        return True
    return False


class JENNISearchLayer:
    """
    Modular search layer for JENNI queries.

    Domain retrievers are independently swappable via constructor injection.
    DocumentStore persists retrieved JENNIDocuments for caching and future
    vector indexing.
    """

    def __init__(
        self,
        institution_retriever: Optional[InstitutionRetriever] = None,
        web_retriever: Optional[InstitutionRetriever] = None,
        narrative_retriever: Optional[InstitutionRetriever] = None,
        store: Optional[DocumentStore] = None,
    ) -> None:
        self.institution_retriever: InstitutionRetriever = (
            institution_retriever or SQLRetriever()
        )
        self.web_retriever: InstitutionRetriever = (
            web_retriever or WebRetriever()
        )
        # news is an alias for web; swap to a dedicated news retriever here
        self.news_retriever: InstitutionRetriever = self.web_retriever
        self.narrative_retriever: InstitutionRetriever = (
            narrative_retriever or SQLRetriever()
        )
        self._store = store or DocumentStore()

    def search(
        self,
        query: str,
        entities: Optional[list[dict]] = None,
        *,
        run_web: Optional[bool] = None,
    ) -> list[RetrievalResult]:
        """
        Run retrieval across active domains and return merged results.

        Parameters
        ----------
        query    : natural language query
        entities : pre-resolved institution entities from query_resolver
                   (each dict has 'unitid', 'institution_name', …)
        run_web  : override web search activation (None = auto-detect)

        Returns
        -------
        list[RetrievalResult] — one entry per domain searched, in order:
            institution → narrative (per entity) → web (if activated)
        """
        results: list[RetrievalResult] = []

        # ── Institution domain — always run ────────────────────────────────
        inst_result = self.institution_retriever.find_institutions(query)
        if inst_result.documents:
            results.append(inst_result)
            self._store.save_result(inst_result)

        # ── Narrative domain — run for each resolved entity ────────────────
        if entities:
            for entity in entities:
                uid = entity.get("unitid")
                if uid:
                    narr_result = self.narrative_retriever.find_documents(
                        query, unitid=uid
                    )
                    if narr_result.documents:
                        results.append(narr_result)
                        self._store.save_result(narr_result)

        # ── Web / news domain — conditional on query content ───────────────
        do_web = run_web if run_web is not None else needs_web_search(query)
        if do_web:
            primary_uid = (entities[0].get("unitid") if entities else None)
            web_result = self.web_retriever.find_documents(
                query, unitid=primary_uid
            )
            if web_result.documents:
                results.append(web_result)
                self._store.save_result(web_result)

        return results
