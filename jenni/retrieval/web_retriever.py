"""
jenni/retrieval/web_retriever.py
──────────────────────────────────────────────────────────────────────────────
Web search retrieval via the Anthropic web_search_20250305 server-side tool.

When an institution query has a current-events or recent-news dimension,
WebRetriever performs a targeted search and returns results as JENNIDocument
objects.  The synthesizer receives these alongside SQL-sourced documents,
clearly labelled [external:web], and incorporates them without needing to
know the retrieval source.

Vector-readiness: returned documents have embedding=None.  Embeddings are
computed and stored by DocumentStore when the vector layer is enabled.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Optional

import anthropic

from jenni.config import get_api_key, MODEL_HAIKU
from jenni.retrieval.base import InstitutionRetriever, JENNIDocument, RetrievalResult

_WEB_SEARCH_TOOL: dict = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}

_URL_PATTERN = re.compile(r"https?://[^\s\]\"'>]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc_id(seed: str, idx: int) -> str:
    raw = f"web:{seed}:{idx}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _extract_documents(
    response: anthropic.types.Message,
    query: str,
    unitid: Optional[int],
) -> list[JENNIDocument]:
    """
    Pull JENNIDocument objects from an Anthropic message that used web_search.

    Strategy (most-specific first):
    1. Parse tool_result / web_search_result content blocks — gives the richest
       structured output with individual titles, URLs, and page snippets.
    2. Fall back to URL-bearing sentences extracted from text blocks.
    3. If nothing else, store the full text block as a single document.
    """
    now = _now_iso()
    docs: list[JENNIDocument] = []

    # Strategy 1: server-side tool result blocks
    for block in response.content:
        btype = getattr(block, "type", "")
        if btype == "tool_result":
            items = getattr(block, "content", []) or []
            for item in items:
                itype = getattr(item, "type", "")
                if itype in ("web_search_result", "web_search_result_20250305"):
                    title = getattr(item, "title", "") or ""
                    url   = getattr(item, "url", "") or None
                    # encrypted_content is the page text when available
                    text = (
                        getattr(item, "encrypted_content", None)
                        or getattr(item, "content", None)
                        or title
                    )
                    if text:
                        docs.append(JENNIDocument(
                            doc_id=_doc_id(url or title, len(docs)),
                            source="web",
                            domain="web",
                            content=str(text)[:2000],
                            title=title,
                            url=url,
                            retrieved_at=now,
                            institution_unitid=unitid,
                            query=query,
                        ))

    if docs:
        return _deduplicate(docs)

    # Strategy 2: extract URL-bearing sentences from text blocks
    for block in response.content:
        if getattr(block, "type", "") == "text":
            text: str = block.text
            sentences = re.split(r"(?<=[.!?\n])\s+", text)
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                urls = _URL_PATTERN.findall(sentence)
                url = urls[0].rstrip(".,);") if urls else None
                docs.append(JENNIDocument(
                    doc_id=_doc_id(url or sentence[:32], len(docs)),
                    source="web",
                    domain="web",
                    content=sentence,
                    url=url,
                    retrieved_at=now,
                    institution_unitid=unitid,
                    query=query,
                ))

    if docs:
        return _deduplicate(docs)

    # Strategy 3: full text block as a single document
    for block in response.content:
        if getattr(block, "type", "") == "text" and block.text.strip():
            docs.append(JENNIDocument(
                doc_id=_doc_id(query[:32], 0),
                source="web",
                domain="web",
                content=block.text.strip()[:2000],
                retrieved_at=now,
                institution_unitid=unitid,
                query=query,
            ))
            break

    return docs


def _deduplicate(docs: list[JENNIDocument]) -> list[JENNIDocument]:
    seen: set[str] = set()
    unique: list[JENNIDocument] = []
    for d in docs:
        key = d.content[:80].strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


class WebRetriever(InstitutionRetriever):
    """
    Web search backed by the Anthropic web_search_20250305 server-side tool.

    find_documents is the only meaningful method here — the other two raise
    NotImplementedError because web search does not resolve institution names
    or peer groups; those remain SQL retriever responsibilities.
    """

    def find_institutions(self, query: str, max_results: int = 3) -> RetrievalResult:
        raise NotImplementedError("WebRetriever does not resolve institution names")

    def find_similar(self, unitid: int, max_results: int = 5) -> RetrievalResult:
        raise NotImplementedError("WebRetriever does not provide peer matching")

    def find_documents(
        self,
        query: str,
        unitid: Optional[int] = None,
        max_results: int = 10,
    ) -> RetrievalResult:
        t0 = time.monotonic()

        prompt = (
            f"Search for recent news and current information relevant to this query:\n"
            f'"{query}"\n\n'
            "Summarize what you find, covering:\n"
            "- News from the past 12 months\n"
            "- Enrollment or program announcements\n"
            "- Financial news or credit rating changes\n"
            "- Leadership appointments or departures\n"
            "- Accreditation actions or regulatory news\n\n"
            "Be factual and concise. Cite source URLs where available."
        )

        docs: list[JENNIDocument] = []
        try:
            client = anthropic.Anthropic(api_key=get_api_key())
            response = client.messages.create(
                model=MODEL_HAIKU,
                max_tokens=1024,
                tools=[_WEB_SEARCH_TOOL],
                messages=[{"role": "user", "content": prompt}],
            )
            docs = _extract_documents(response, query, unitid)
        except Exception:
            # Web search failures are non-fatal — SQL retrieval continues
            pass

        elapsed = (time.monotonic() - t0) * 1000
        return RetrievalResult(
            query=query,
            domain="web",
            documents=docs[:max_results],
            retrieval_time_ms=elapsed,
            metadata={"source": "anthropic_web_search_20250305"},
        )
