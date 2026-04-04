"""
jenni/learning/extractor.py
----------------------------
Post-synthesis insight extraction using Haiku (cost-controlled).

After every synthesis call, passes the narrative output through Haiku to
extract candidate insights. Only Haiku — not Sonnet — for cost control.

Extracted candidates are validated via JENNIInsightValidator before storage.
Failures are silently dropped — extraction failures must never surface to users.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import anthropic

from jenni.config import DB_IPEDS, MODEL_HAIKU, get_api_key
from jenni.learning.validator import JENNIInsightValidator

EXTRACTION_PROMPT = """You are analyzing a JENNI financial intelligence \
output about a higher education institution.

Extract up to 3 specific, factual insights from this narrative that:
- Reference a specific institution by name
- Make a claim grounded in financial, enrollment, or operational data
- Could be verified against federal data sources (990, IPEDS, EADA)

Do NOT extract:
- Opinions or interpretations without data backing
- Speculation about the future
- Claims about individuals or personal information
- General sector observations not tied to a specific institution

Return ONLY a JSON array. Each object must have:
{
  "institution_name": "...",
  "insight_text": "one sentence, specific and data-grounded",
  "source_tables": "comma-separated table names if identifiable",
  "insight_type": "trajectory|financial_position|peer_context|structural|pattern"
}

If no qualifying insights exist, return an empty array [].
Return ONLY the JSON array, no other text."""


class JENNIInsightExtractor:

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=get_api_key())
        self.validator = JENNIInsightValidator()

    def extract_and_store(
        self,
        narrative: str,
        context: dict,
        db_conn: sqlite3.Connection,
    ) -> list[dict]:
        """
        Extract candidate insights from narrative, validate, and store passing
        candidates into jenni_institutional_insights.

        Parameters
        ----------
        narrative  : synthesized narrative text
        context    : full context package (used for validator evidence tier)
        db_conn    : open connection to 990_data.db

        Returns
        -------
        List of stored candidate dicts (empty if none passed validation).
        """
        try:
            response = self.client.messages.create(
                model=MODEL_HAIKU,
                max_tokens=1000,
                messages=[{
                    'role': 'user',
                    'content': f"{EXTRACTION_PROMPT}\n\nNARRATIVE:\n{narrative}",
                }],
            )
            raw = response.content[0].text.strip()
            # Strip markdown code fences if Haiku wraps the JSON
            if raw.startswith('```'):
                raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
            candidates = json.loads(raw)
            if not isinstance(candidates, list):
                return []
        except Exception:
            return []

        stored = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            unitid = self._resolve_unitid(candidate.get('institution_name', ''))
            if not unitid:
                continue
            candidate['unitid'] = unitid
            result = self.validator.validate(candidate, context)
            if result.approved:
                self._write_insight(candidate, result, db_conn)
                stored.append(candidate)
        return stored

    def _resolve_unitid(self, name: str) -> int | None:
        """Look up unitid from institution_master by fuzzy name match."""
        if not name:
            return None
        try:
            conn = sqlite3.connect(str(DB_IPEDS))
            row = conn.execute(
                'SELECT unitid FROM institution_master '
                'WHERE institution_name LIKE ? LIMIT 1',
                (f'%{name}%',),
            ).fetchone()
            conn.close()
            return row[0] if row else None
        except Exception:
            return None

    def _write_insight(
        self,
        candidate: dict,
        result: object,
        db_conn: sqlite3.Connection,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            db_conn.execute("""
                INSERT OR IGNORE INTO jenni_institutional_insights
                    (unitid, institution_name, insight_text,
                     evidence_tier, confidence, source_tables,
                     insight_type, extraction_method,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                candidate['unitid'],
                candidate.get('institution_name', ''),
                candidate['insight_text'],
                result.evidence_tier,
                result.confidence,
                candidate.get('source_tables', ''),
                candidate.get('insight_type', ''),
                'model_extracted',
                now,
                now,
            ))
            db_conn.commit()
        except Exception:
            pass
