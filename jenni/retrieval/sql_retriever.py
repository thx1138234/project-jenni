"""
jenni/retrieval/sql_retriever.py
──────────────────────────────────────────────────────────────────────────────
SQL-backed institution retrieval.  Uses existing fuzzy-match entity extraction
from query_resolver and Carnegie peer group data from institution_master /
institution_quant.

This is the current-production retriever.  When the vector layer is enabled,
SQLRetriever continues to handle institution resolution and peer lookup; the
VectorRetriever takes over semantic document search.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from jenni.config import DB_IPEDS, DB_QUANT
from jenni.retrieval.base import InstitutionRetriever, JENNIDocument, RetrievalResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc_id(prefix: str, uid: int, suffix: str = "") -> str:
    raw = f"{prefix}:{uid}:{suffix}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _dict_rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


class SQLRetriever(InstitutionRetriever):
    """
    Institution retrieval backed by ipeds_data.db and institution_quant.db.

    find_institutions  — fuzzy entity matching via extract_entities()
    find_similar       — Carnegie peer group members from institution_master
    find_documents     — pre-encoded narratives from institution_narratives
    """

    def find_institutions(self, query: str, max_results: int = 3) -> RetrievalResult:
        # Local import avoids circular dependency with query_resolver
        from jenni.query_resolver import extract_entities  # noqa: PLC0415

        t0 = time.monotonic()
        matches = extract_entities(query, max_results=max_results)
        docs: list[JENNIDocument] = []
        for m in matches:
            uid = m["unitid"]
            content = (
                f"{m['institution_name']} — {m.get('control_label', '')} | "
                f"{m.get('state_abbr', '')} | Carnegie {m.get('carnegie_basic', '')}"
            )
            docs.append(JENNIDocument(
                doc_id=_doc_id("sql_inst", uid),
                source="sql",
                domain="institution",
                content=content,
                title=m["institution_name"],
                retrieved_at=_now_iso(),
                institution_unitid=uid,
                query=query,
            ))
        elapsed = (time.monotonic() - t0) * 1000
        return RetrievalResult(
            query=query,
            domain="institution",
            documents=docs,
            retrieval_time_ms=elapsed,
            metadata={"match_count": len(matches)},
        )

    def find_similar(self, unitid: int, max_results: int = 5) -> RetrievalResult:
        t0 = time.monotonic()
        docs: list[JENNIDocument] = []

        ipeds_conn = sqlite3.connect(str(DB_IPEDS))
        rows = _dict_rows(ipeds_conn,
            "SELECT carnegie_basic FROM institution_master WHERE unitid = ?",
            (unitid,))

        if not rows or rows[0].get("carnegie_basic") is None:
            ipeds_conn.close()
            return RetrievalResult(
                query=str(unitid), domain="institution",
                documents=[], retrieval_time_ms=0.0,
            )

        carnegie = rows[0]["carnegie_basic"]
        peers = _dict_rows(ipeds_conn, """
            SELECT unitid, institution_name, state_abbr, control_label
            FROM institution_master
            WHERE carnegie_basic = ? AND unitid != ? AND is_active = 1
            ORDER BY institution_name
            LIMIT ?
        """, (carnegie, unitid, max_results))
        ipeds_conn.close()

        for p in peers:
            uid = p["unitid"]
            docs.append(JENNIDocument(
                doc_id=_doc_id("sql_peer", uid),
                source="sql",
                domain="institution",
                content=(
                    f"{p['institution_name']} — {p.get('control_label', '')} | "
                    f"{p.get('state_abbr', '')}"
                ),
                title=p["institution_name"],
                retrieved_at=_now_iso(),
                institution_unitid=uid,
                query=f"peers of unitid={unitid}",
            ))

        elapsed = (time.monotonic() - t0) * 1000
        return RetrievalResult(
            query=str(unitid),
            domain="institution",
            documents=docs,
            retrieval_time_ms=elapsed,
            metadata={"carnegie_basic": carnegie, "peer_count": len(docs)},
        )

    def find_documents(
        self,
        query: str,
        unitid: Optional[int] = None,
        max_results: int = 10,
    ) -> RetrievalResult:
        t0 = time.monotonic()
        docs: list[JENNIDocument] = []

        quant_conn = sqlite3.connect(str(DB_QUANT))
        where = "WHERE unitid = ?" if unitid else ""
        params: tuple = (unitid,) if unitid else ()

        narr_rows = _dict_rows(quant_conn, f"""
            SELECT unitid, narrative_type, content
            FROM institution_narratives
            {where}
            ORDER BY
                CASE source WHEN 'hand_crafted' THEN 0
                            WHEN 'auto_seeded'  THEN 1
                            ELSE 2 END,
                valid_from DESC NULLS LAST
            LIMIT ?
        """, (*params, max_results))
        quant_conn.close()

        for nr in narr_rows:
            uid = nr["unitid"]
            ntype = nr["narrative_type"]
            docs.append(JENNIDocument(
                doc_id=_doc_id("sql_narr", uid, ntype),
                source="narrative",
                domain="narrative",
                content=nr["content"],
                title=f"{ntype} (unitid={uid})",
                retrieved_at=_now_iso(),
                institution_unitid=uid,
                query=query,
            ))

        elapsed = (time.monotonic() - t0) * 1000
        return RetrievalResult(
            query=query,
            domain="narrative",
            documents=docs,
            retrieval_time_ms=elapsed,
        )
