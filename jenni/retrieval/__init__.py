"""jenni.retrieval — modular search layer with vector-compatible architecture."""

from jenni.retrieval.base import (
    InstitutionRetriever,
    JENNIDocument,
    RetrievalResult,
)
from jenni.retrieval.search_layer import JENNISearchLayer, needs_web_search
from jenni.retrieval.sql_retriever import SQLRetriever
from jenni.retrieval.web_retriever import WebRetriever

__all__ = [
    "InstitutionRetriever",
    "JENNIDocument",
    "RetrievalResult",
    "JENNISearchLayer",
    "needs_web_search",
    "SQLRetriever",
    "WebRetriever",
]
