"""
jenni/query_resolver.py
--------------------------------------
Classifies queries, extracts institution entities (fuzzy name matching against
institution_master), and assembles the context package for the synthesizer.

The model NEVER touches the database. All retrieval happens here.
The context package is a plain dict; the synthesizer formats it into a prompt.

Public API:
    resolve(query, year=None) -> dict   # full context package
"""

from __future__ import annotations

import difflib
import sqlite3
from pathlib import Path
from typing import Optional

from jenni.config import (
    DB_IPEDS, DB_990, DB_QUANT,
    PRIMARY_YEAR, BACKWARD_TERMINUS_990, BACKWARD_TERMINUS_IPEDS,
    FORWARD_TERMINUS_DEFENSIBLE, MIN_PEER_COUNT,
)

# ---------------------------------------------------------------------------
# Common institution abbreviations / aliases  (lower-case)
# ---------------------------------------------------------------------------
KNOWN_ALIASES: dict[str, int] = {
    "mit":      166683,
    "bc":       164924,
    "bu":       168148,   # Boston University
    "northeastern": 167358,
    "babson":   164580,
    "bentley":  164739,
    "harvard":  166027,
    "stanford": 243744,
    "yale":     130794,
    "princeton":186131,
    "columbia": 190150,
    "penn":     215062,
    "upenn":    215062,
    "duke":     198419,
    "nyu":      193900,
    "cornell":  190415,
    "dartmouth":182670,
    "brown":    217156,
    "tufts":    168148,   # note: same as BU — will be caught by name match
    "uc berkeley":110635,
    "ucla":     110662,
    "michigan": 170976,
    "uchicago": 144050,
    "northwestern":147767,
    "johns hopkins":162928,
    "jhu":      162928,
    "emory":    139755,
    "vanderbilt":220978,
    "notre dame":152080,
    "georgetown":131496,
    "wake forest":199193,
    "rice":     227757,
    "tulane":   230764,
    "lehigh":   212577,
}

# ---------------------------------------------------------------------------
# Query type classifiers
# ---------------------------------------------------------------------------
_COMPARISON_WORDS = {"compare", "vs", "versus", "against", "relative to", "benchmark",
                     "compared", "comparison", "peer", "peers", "rank", "ranking"}
_TREND_WORDS      = {"trend", "over time", "history", "trajectory", "changed",
                     "growth", "decline", "years", "trajectory", "longitudinal", "cagr"}
_STRESS_WORDS     = {"stress", "risk", "distress", "closure", "closing", "bankrupt",
                     "financial health", "warning", "struggling", "troubled", "at risk",
                     "in danger", "vulnerable"}
_SECTOR_WORDS     = {"sector", "all", "which schools", "which institutions", "across",
                     "industry", "landscape", "list", "most", "least", "highest", "lowest",
                     "nationally", "nationwide", "how many"}
_DATA_WORDS       = {"what is", "how much", "show me", "give me", "what was",
                     "what are", "show", "display", "table", "numbers", "data"}


def classify_query(query: str) -> str:
    q = query.lower()
    tokens = set(q.split())

    if _COMPARISON_WORDS & tokens or any(p in q for p in ("vs ", " vs.", "compared to")):
        return "comparison"
    if _TREND_WORDS & tokens or any(p in q for p in ("over time", "over the", "since 20")):
        return "trend"
    if _STRESS_WORDS & tokens or any(p in q for p in _STRESS_WORDS):
        return "stress"
    if _SECTOR_WORDS & tokens or any(p in q for p in ("which schools", "which institutions")):
        return "sector"
    if any(p in q for p in _DATA_WORDS):
        return "data"
    return "analysis"


# ---------------------------------------------------------------------------
# Institution name index (lazy-loaded, module-level cache)
# ---------------------------------------------------------------------------
_name_index: list[dict] | None = None


def _load_name_index() -> list[dict]:
    global _name_index
    if _name_index is not None:
        return _name_index
    conn = sqlite3.connect(str(DB_IPEDS))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT unitid, institution_name, state_abbr, city, control, "
        "control_label, carnegie_basic, iclevel, ein "
        "FROM institution_master WHERE is_active = 1"
    ).fetchall()
    conn.close()
    _name_index = [dict(r) for r in rows]
    return _name_index


def extract_entities(query: str, max_results: int = 3) -> list[dict]:
    """
    Fuzzy-match institution names mentioned in the query.
    Returns list of institution_master records (with added match_score).
    """
    index = _load_name_index()
    query_lower = query.lower()

    # Phase 1: exact alias lookup
    matched_by_alias: dict[int, dict] = {}
    for alias, uid in KNOWN_ALIASES.items():
        if alias in query_lower:
            for rec in index:
                if rec["unitid"] == uid:
                    matched_by_alias[uid] = {**rec, "match_score": 1.0, "match_method": "alias"}
                    break

    if matched_by_alias:
        return sorted(matched_by_alias.values(), key=lambda x: -x["match_score"])[:max_results]

    # Phase 2: substring match against institution_name
    name_map = {rec["institution_name"].lower(): rec for rec in index}
    names_lower = list(name_map.keys())

    direct: dict[int, dict] = {}
    for name_lower, rec in name_map.items():
        if name_lower in query_lower:
            uid = rec["unitid"]
            direct[uid] = {**rec, "match_score": 1.0, "match_method": "exact_substring"}

    if direct:
        return sorted(direct.values(), key=lambda x: -x["match_score"])[:max_results]

    # Phase 3: token-window fuzzy match
    tokens = query.split()
    candidates: dict[int, dict] = {}

    for window_size in range(1, 5):
        for i in range(len(tokens) - window_size + 1):
            window = " ".join(tokens[i : i + window_size]).lower()
            close = difflib.get_close_matches(window, names_lower, n=3, cutoff=0.72)
            for match in close:
                rec = name_map[match]
                uid = rec["unitid"]
                score = difflib.SequenceMatcher(None, window, match).ratio()
                if uid not in candidates or score > candidates[uid]["match_score"]:
                    candidates[uid] = {**rec, "match_score": score, "match_method": "fuzzy"}

    return sorted(candidates.values(), key=lambda x: -x["match_score"])[:max_results]


# ---------------------------------------------------------------------------
# Accordion position
# ---------------------------------------------------------------------------

def determine_accordion_position(years_in_db: list[int], query_year: int | None) -> dict:
    """
    Given the years available in the database for a query, determine where on
    the accordion we are and what epistemic posture is appropriate.
    """
    if not years_in_db:
        return {
            "years_in_db": [],
            "primary_year": PRIMARY_YEAR,
            "backward_terminus": BACKWARD_TERMINUS_990,
            "forward_terminus": FORWARD_TERMINUS_DEFENSIBLE,
            "zone": "no_data",
            "epistemic_posture": "acknowledge",
            "posture_note": "No structured data found for this query.",
        }

    primary_year = query_year or max(years_in_db)
    oldest_year  = min(years_in_db)

    if primary_year >= FORWARD_TERMINUS_DEFENSIBLE:
        zone    = "beyond_forward"
        posture = "conditional"
        note    = (
            f"Projecting beyond {FORWARD_TERMINUS_DEFENSIBLE} — use conditionals, "
            "not predictions."
        )
    elif primary_year > PRIMARY_YEAR + 1:
        zone    = "approaching_forward"
        posture = "conditional"
        note    = (
            f"Year {primary_year} is at the forward edge of confirmed data. "
            "Financial metrics may be partial (pending 990 filings)."
        )
    elif oldest_year <= BACKWARD_TERMINUS_990 and primary_year <= BACKWARD_TERMINUS_990 + 2:
        zone    = "approaching_backward"
        posture = "humility"
        note    = (
            f"Data coverage thins before {BACKWARD_TERMINUS_990} (990 XML) "
            f"and before {BACKWARD_TERMINUS_IPEDS} (IPEDS). "
            "Qualify trends that extend into this window."
        )
    else:
        zone    = "center"
        posture = "authority"
        note    = (
            f"Primary year {primary_year} is well-covered by multiple data sources. "
            "State findings with authority."
        )

    return {
        "years_in_db": sorted(years_in_db),
        "primary_year": primary_year,
        "backward_terminus": BACKWARD_TERMINUS_990,
        "forward_terminus": FORWARD_TERMINUS_DEFENSIBLE,
        "zone": zone,
        "epistemic_posture": posture,
        "posture_note": note,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _dict_rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def _load_institution_data(
    unitid: int,
    quant_conn: sqlite3.Connection,
    db990_conn: sqlite3.Connection,
    ipeds_conn: sqlite3.Connection,
    primary_year: int | None = None,
) -> dict:
    """Pull all data for one institution from the three databases."""

    # institution_master
    masters = _dict_rows(ipeds_conn,
        "SELECT * FROM institution_master WHERE unitid = ?", (unitid,))
    master = masters[0] if masters else {}

    # institution_quant — full history, sorted by year
    quant_history = _dict_rows(quant_conn,
        "SELECT * FROM institution_quant WHERE unitid = ? ORDER BY survey_year",
        (unitid,))

    # quant_latest: prefer the row matching primary_year; fall back to latest
    if primary_year and quant_history:
        year_map = {r["survey_year"]: r for r in quant_history}
        # Use requested year if present; else nearest year <= primary_year
        if primary_year in year_map:
            quant_latest = year_map[primary_year]
        else:
            candidates = [r for r in quant_history if r["survey_year"] <= primary_year]
            quant_latest = candidates[-1] if candidates else quant_history[-1]
    else:
        quant_latest = quant_history[-1] if quant_history else {}

    # financial_stress_signals (EIN-level — join through master)
    stress = None
    ein = master.get("ein")
    if ein:
        rows = _dict_rows(db990_conn,
            "SELECT * FROM financial_stress_signals WHERE ein = ? LIMIT 1", (ein,))
        if rows:
            stress = rows[0]
    if stress is None:
        # fallback: unitid match
        rows = _dict_rows(db990_conn,
            "SELECT * FROM financial_stress_signals WHERE unitid = ? LIMIT 1", (unitid,))
        if rows:
            stress = rows[0]

    # institution_narratives — group by type, prefer hand_crafted > auto_seeded
    narr_rows = _dict_rows(quant_conn, """
        SELECT narrative_type, content, confidence, source, valid_from, valid_until
        FROM institution_narratives
        WHERE unitid = ?
        ORDER BY
            CASE source WHEN 'hand_crafted' THEN 0
                        WHEN 'auto_seeded'  THEN 1
                        ELSE 2 END,
            valid_from DESC NULLS LAST
    """, (unitid,))

    narratives: dict[str, str] = {}
    for nr in narr_rows:
        t = nr["narrative_type"]
        if t not in narratives:
            narratives[t] = nr["content"]

    return {
        "master":        master,
        "quant_latest":  quant_latest,
        "quant_history": quant_history,
        "stress":        stress,
        "narratives":    narratives,
    }


def _data_quality(institution_data: dict[int, dict], primary_year: int) -> dict:
    """Summarize data quality across matched institutions."""
    all_completeness: list[float] = []
    all_sources: set[str] = {"ipeds"}
    missing: list[str] = []

    for uid, data in institution_data.items():
        q = data.get("quant_latest", {})
        if not q:
            continue

        c = q.get("data_completeness_pct")
        if c is not None:
            all_completeness.append(c)

        # Detect sources from non-NULL metric columns
        if q.get("operating_margin_value") is not None:
            all_sources.add("990")
        if q.get("enrollment_3yr_cagr_value") is not None:
            all_sources.add("ipeds")
        if q.get("athletics_net_value") is not None:
            all_sources.add("eada")
        if q.get("grad_rate_150_value") is not None:
            all_sources.add("scorecard")

        # Flag always-NULL metrics
        for col, label in [
            ("retention_rate_value",    "retention_rate (EF Part D not loaded)"),
            ("operating_margin_value",  "financial metrics (public institution or pre-TEOS)"),
        ]:
            if q.get(col) is None and "retention_rate" in col:
                if "retention_rate" not in " ".join(missing):
                    missing.append(label)

    avg_completeness = (
        sum(all_completeness) / len(all_completeness) if all_completeness else None
    )

    return {
        "primary_year":    primary_year,
        "completeness_pct": round(avg_completeness, 1) if avg_completeness is not None else None,
        "sources":         sorted(all_sources),
        "missing_metrics": missing,
    }


def assemble_context(
    query: str,
    year: int | None = None,
) -> dict:
    """
    Main entry point. Returns a full context package ready for the synthesizer.

    Parameters
    ----------
    query : str
        The user's natural language query.
    year : int | None
        Override the primary year for data retrieval (default: latest available).

    Returns
    -------
    dict with keys: query, query_type, entities, accordion, institution_data,
                    data_quality, peer_data
    """
    query_type = classify_query(query)
    entities   = extract_entities(query)

    quant_conn = sqlite3.connect(str(DB_QUANT))
    db990_conn = sqlite3.connect(str(DB_990))
    ipeds_conn = sqlite3.connect(str(DB_IPEDS))

    # Pre-pass: collect available years to determine accordion + primary_year
    all_years: list[int] = []
    uid_histories: dict[int, list[dict]] = {}
    for entity in entities:
        uid = entity["unitid"]
        hist = _dict_rows(quant_conn,
            "SELECT survey_year FROM institution_quant WHERE unitid = ? ORDER BY survey_year",
            (uid,))
        uid_histories[uid] = hist
        for row in hist:
            yr = row.get("survey_year")
            if yr:
                all_years.append(yr)

    years_in_db  = sorted(set(all_years))
    accordion    = determine_accordion_position(years_in_db, year)
    primary_year = accordion["primary_year"]

    # Main pass: load full data using resolved primary_year
    institution_data: dict[int, dict] = {}
    for entity in entities:
        uid  = entity["unitid"]
        data = _load_institution_data(uid, quant_conn, db990_conn, ipeds_conn, primary_year)
        institution_data[uid] = data

    quant_conn.close()
    db990_conn.close()
    ipeds_conn.close()

    # Peer data: extract from quant_latest peer_* columns of the primary entity
    peer_data: dict = {}
    if entities:
        primary_uid  = entities[0]["unitid"]
        primary_data = institution_data.get(primary_uid, {})
        q = primary_data.get("quant_latest", {})
        if q:
            peer_data = {
                "carnegie_peer_group_size": q.get("carnegie_peer_group_size"),
                "peer_medians": {
                    metric: q.get(f"{metric}_peer_median")
                    for metric in _METRIC_NAMES
                    if q.get(f"{metric}_peer_median") is not None
                },
                "peer_percentiles": {
                    metric: q.get(f"{metric}_peer_pct")
                    for metric in _METRIC_NAMES
                    if q.get(f"{metric}_peer_pct") is not None
                },
            }

    dq = _data_quality(institution_data, primary_year)

    return {
        "query":            query,
        "query_type":       query_type,
        "entities":         entities,
        "accordion":        accordion,
        "institution_data": institution_data,
        "peer_data":        peer_data,
        "data_quality":     dq,
    }


# Ordered metric names for peer data extraction
_METRIC_NAMES = [
    "tuition_dependency", "operating_margin", "debt_to_assets", "debt_to_revenue",
    "endowment_per_student", "endowment_spending_rate", "endowment_runway",
    "fundraising_efficiency", "overhead_ratio", "program_services_pct",
    "revenue_per_fte", "expense_per_fte",
    "enrollment_3yr_cagr", "yield_rate", "admit_rate", "app_3yr_cagr",
    "grad_rate_150", "retention_rate", "grad_enrollment_pct", "pell_pct",
    "net_price", "earnings_to_debt_ratio", "net_price_to_earnings",
    "athletics_to_expense_pct", "athletics_net", "athletics_per_student",
]
