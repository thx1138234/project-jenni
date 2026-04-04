"""
jenni/learning/sanitizer.py
----------------------------
Strips role-revealing or personally-identifying patterns from query text
before the query is written to jenni_query_log.

The raw query is never stored — only the sanitized version.
"""

from __future__ import annotations

import re

ROLE_PATTERNS = [
    r'\bas (cfo|coo|cto|vp|president|provost|dean|director)\b',
    r'\bi work (at|for)\b',
    r'\bmy (institution|university|college|school)\b',
    r'\bwe (are|have|do|did|went)\b',
]


def sanitize_query(query_text: str) -> str:
    sanitized = query_text
    for pattern in ROLE_PATTERNS:
        sanitized = re.sub(
            pattern, '[role removed]',
            sanitized, flags=re.IGNORECASE,
        )
    return sanitized.strip()
