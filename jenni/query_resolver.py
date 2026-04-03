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
import statistics
import time
from pathlib import Path
from typing import Optional

from jenni.config import (
    DB_IPEDS, DB_990, DB_QUANT, DB_EADA,
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
# Stress requires unambiguous distress language — "financial health" and "risk"
# are too broad and misclassify general analysis queries.
_STRESS_WORDS     = {"stress", "distress", "closure", "closing", "bankrupt",
                     "warning", "struggling", "troubled", "vulnerable", "insolvent",
                     "at risk", "in danger", "warning signs", "going under"}
_SECTOR_WORDS     = {"sector", "all", "which schools", "which institutions", "across",
                     "industry", "landscape", "list", "most", "least", "highest", "lowest",
                     "nationally", "nationwide", "how many"}
_DATA_WORDS       = {"what is", "how much", "show me", "give me", "what was",
                     "what are", "show", "display", "table", "numbers", "data"}
# institution_profile: "tell me about", "financial health", "overview" queries
# without explicit stress language — general institutional portrait requests.
_PROFILE_PHRASES  = (
    "tell me about", "what do you know about", "overview of", "profile of",
    "financial health", "give me an overview", "who is", "what is",
)
_PROFILE_WORDS    = {"overview", "profile", "health", "about", "portrait",
                     "summary", "introduction", "background"}


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
    if any(p in q for p in _PROFILE_PHRASES) or _PROFILE_WORDS & tokens:
        return "institution_profile"
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

    All three phases run and merge results — early return from alias phase
    was dropped because it silently dropped the second institution in
    comparison queries where one matched by alias and the other by substring.
    """
    index = _load_name_index()
    query_lower = query.lower()
    candidates: dict[int, dict] = {}

    # Phase 1: exact alias lookup
    for alias, uid in KNOWN_ALIASES.items():
        if alias in query_lower:
            for rec in index:
                if rec["unitid"] == uid:
                    candidates[uid] = {**rec, "match_score": 1.0, "match_method": "alias"}
                    break

    # Phase 2: substring match against institution_name — merges with alias results
    # so both institutions resolve in queries like "Compare BC and Georgetown …"
    #
    # Token-overlap guard: require each distinctive token of the candidate name
    # (non-stopword, len >= 4) to appear as a whole word in the query.
    # This prevents "Eastern University" from matching inside "Northeastern University"
    # because "eastern" is not a whole word in the query tokens.
    _SUBSTR_STOPWORDS = {"university", "college", "institute", "school", "of", "the",
                         "and", "at", "for", "state", "city", "new"}
    query_tokens = set(query_lower.split())
    name_map = {rec["institution_name"].lower(): rec for rec in index}

    for name_lower, rec in name_map.items():
        if name_lower not in query_lower:
            continue
        # Whole-word token check: all distinctive tokens of the candidate name
        # must appear as complete tokens in the query.
        name_tokens = [t for t in name_lower.split()
                       if t not in _SUBSTR_STOPWORDS and len(t) >= 4]
        if name_tokens and not all(t in query_tokens for t in name_tokens):
            continue
        uid = rec["unitid"]
        if uid not in candidates:
            candidates[uid] = {**rec, "match_score": 1.0, "match_method": "exact_substring"}

    # Return immediately if any clean match was found — Phase 3 is a fallback
    # only for queries where neither alias nor substring matched anything.
    # Running fuzzy after clean matches produces noise (e.g. "Oakton College"
    # from the token "College" in "Boston College").
    if candidates:
        return sorted(candidates.values(), key=lambda x: -x["match_score"])[:max_results]

    # Phase 3: token-window fuzzy match (fallback — no clean matches above)
    tokens = query.split()
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

def _compute_part_ix_peer_context(
    ein: str,
    carnegie_basic,
    part_ix_history: list[dict],
    ipeds_conn: sqlite3.Connection,
    db990_conn: sqlite3.Connection,
) -> dict[int, dict]:
    """
    Compute Carnegie peer medians and institution percentiles for three Part IX
    metrics: advertising_total, it_total, and prof_fundraising_fees.

    Returns a dict keyed by fiscal_year_end.  Only years with MIN_PEER_COUNT or
    more peers reporting Part IX data are included.
    """
    if not part_ix_history or not carnegie_basic or not ein:
        return {}

    fiscal_years = [r["fiscal_year_end"] for r in part_ix_history]
    if not fiscal_years:
        return {}

    # All active peers with the same Carnegie basic (institution itself included)
    peer_eins = [
        r["ein"]
        for r in _dict_rows(ipeds_conn, """
            SELECT ein FROM institution_master
            WHERE carnegie_basic = ? AND ein IS NOT NULL AND is_active = 1
        """, (carnegie_basic,))
    ]
    if len(peer_eins) < MIN_PEER_COUNT:
        return {}

    ein_ph = ",".join("?" * len(peer_eins))
    fy_ph  = ",".join("?" * len(fiscal_years))
    peer_rows = _dict_rows(db990_conn, f"""
        SELECT ein, fiscal_year_end,
               (COALESCE(advertising_prog, 0) + COALESCE(advertising_mgmt, 0)
                + COALESCE(advertising_fundraising, 0))  AS adv_total,
               (COALESCE(it_prog, 0) + COALESCE(it_mgmt, 0)
                + COALESCE(it_fundraising, 0))           AS it_total,
               COALESCE(prof_fundraising_fees, 0)         AS pf_total
        FROM form990_part_ix
        WHERE ein IN ({ein_ph})
          AND fiscal_year_end IN ({fy_ph})
    """, peer_eins + fiscal_years)

    # Group by fiscal year
    by_fy: dict[int, list[dict]] = {}
    for row in peer_rows:
        by_fy.setdefault(row["fiscal_year_end"], []).append(row)

    def _pctile(values: list[float], inst_val: float) -> float:
        """Fraction of peers below the institution's value (0–1)."""
        return sum(1 for v in values if v < inst_val) / len(values) if values else 0.0

    result: dict[int, dict] = {}
    for inst_row in part_ix_history:
        fy    = inst_row["fiscal_year_end"]
        peers = by_fy.get(fy, [])
        n     = len(peers)
        if n < MIN_PEER_COUNT:
            continue

        inst_adv = (
            (inst_row.get("advertising_prog") or 0)
            + (inst_row.get("advertising_mgmt") or 0)
            + (inst_row.get("advertising_fundraising") or 0)
        )
        inst_it = (
            (inst_row.get("it_prog") or 0)
            + (inst_row.get("it_mgmt") or 0)
            + (inst_row.get("it_fundraising") or 0)
        )
        inst_pf = inst_row.get("prof_fundraising_fees") or 0

        adv_vals = [r["adv_total"] for r in peers]
        it_vals  = [r["it_total"]  for r in peers]
        pf_vals  = [r["pf_total"]  for r in peers]

        result[fy] = {
            "peer_n":                  n,
            "advertising_peer_median": statistics.median(adv_vals),
            "advertising_peer_pct":    _pctile(adv_vals, inst_adv),
            "it_peer_median":          statistics.median(it_vals),
            "it_peer_pct":             _pctile(it_vals, inst_it),
            "fundraising_peer_median": statistics.median(pf_vals),
            "fundraising_peer_pct":    _pctile(pf_vals, inst_pf),
        }

    return result


def _load_institution_data(
    unitid: int,
    quant_conn: sqlite3.Connection,
    db990_conn: sqlite3.Connection,
    ipeds_conn: sqlite3.Connection,
    primary_year: int | None = None,
    eada_conn: sqlite3.Connection | None = None,
) -> dict:
    """Pull all data for one institution from the available databases."""

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

    # form990_part_ix — TEOS/irsx years only (FY2020+)
    # Loaded for all institutions with an EIN; synthesizer decides when to include.
    part_ix_history: list[dict] = []
    if ein:
        part_ix_history = _dict_rows(db990_conn, """
            SELECT ix.fiscal_year_end,
                   ix.advertising_prog, ix.advertising_mgmt, ix.advertising_fundraising,
                   ix.it_prog, ix.it_mgmt, ix.it_fundraising,
                   ix.prof_fundraising_fees, ix.invest_mgmt_fees,
                   ix.total_prog_services, ix.total_mgmt_general, ix.total_fundraising_exp,
                   ix.prog_services_pct, ix.overhead_ratio, ix.fundraising_efficiency
            FROM form990_part_ix ix
            WHERE ix.ein = ?
            ORDER BY ix.fiscal_year_end
        """, (ein,))

    # Part IX peer context — Carnegie peer medians/percentiles for advertising, IT, fundraising
    part_ix_peer_context: dict[int, dict] = {}
    if part_ix_history:
        part_ix_peer_context = _compute_part_ix_peer_context(
            ein or "",
            master.get("carnegie_basic"),
            part_ix_history,
            ipeds_conn,
            db990_conn,
        )

    # form990_schedule_d — endowment detail, all TEOS years
    schedule_d_history: list[dict] = []
    if ein:
        schedule_d_history = _dict_rows(db990_conn, """
            SELECT fiscal_year_end, endowment_boy, endowment_eoy,
                   contributions_endowment, investment_return_endowment,
                   grants_from_endowment, other_endowment_changes,
                   endowment_restricted_perm, endowment_restricted_temp,
                   endowment_unrestricted, endowment_board_designated,
                   endowment_spending_rate, endowment_runway
            FROM form990_schedule_d
            WHERE ein = ?
            ORDER BY fiscal_year_end
        """, (ein,))

    # form990_compensation — top 10 earners, most recent TEOS year
    compensation_rows: list[dict] = []
    if ein:
        compensation_rows = _dict_rows(db990_conn, """
            SELECT officer_name, officer_title, comp_total, comp_base,
                   comp_bonus, comp_deferred, comp_nontaxable, related_org_comp,
                   hours_per_week, former_officer, fiscal_year_end
            FROM form990_compensation
            WHERE ein = ?
              AND fiscal_year_end = (
                  SELECT MAX(fiscal_year_end) FROM form990_compensation WHERE ein = ?
              )
            ORDER BY comp_total DESC
            LIMIT 10
        """, (ein, ein))

    # form990_part_viii — most recent TEOS year (revenue sub-lines)
    part_viii_row: dict | None = None
    if ein:
        rows = _dict_rows(db990_conn, """
            SELECT fiscal_year_end, govt_grants_amt, all_other_contributions_amt,
                   prog_svc_revenue_2a, prog_svc_desc_2a,
                   prog_svc_revenue_2b, prog_svc_desc_2b,
                   prog_svc_revenue_2c, prog_svc_desc_2c,
                   prog_svc_revenue_2d, prog_svc_desc_2d,
                   prog_svc_revenue_2e, prog_svc_desc_2e
            FROM form990_part_viii
            WHERE ein = ?
            ORDER BY fiscal_year_end DESC
            LIMIT 1
        """, (ein,))
        part_viii_row = rows[0] if rows else None

    # form990_governance — most recent TEOS year
    governance_row: dict | None = None
    if ein:
        rows = _dict_rows(db990_conn, """
            SELECT fiscal_year_end, voting_members_governing_body,
                   voting_members_independent, total_employees,
                   conflict_of_interest_policy, whistleblower_policy,
                   document_retention_policy, financials_audited, audit_committee,
                   family_or_business_relationship, government_grants_amt
            FROM form990_governance
            WHERE ein = ?
            ORDER BY fiscal_year_end DESC
            LIMIT 1
        """, (ein,))
        governance_row = rows[0] if rows else None

    # eada_instlevel — most recent 3 years (unitid-keyed, eada_data.db)
    eada_instlevel_history: list[dict] = []
    if eada_conn is not None:
        eada_instlevel_history = list(reversed(_dict_rows(eada_conn, """
            SELECT survey_year, grnd_total_revenue, grnd_total_expense,
                   studentaid_total, recruitexp_total,
                   hdcoach_salary_men, hdcoach_salary_women,
                   partic_men, partic_women, ef_total_count
            FROM eada_instlevel
            WHERE unitid = ?
            ORDER BY survey_year DESC
            LIMIT 3
        """, (unitid,))))

    # eada_sports — most recent year, all sports ordered by expenses (unitid-keyed)
    eada_sports_rows: list[dict] = []
    if eada_conn is not None:
        eada_sports_rows = _dict_rows(eada_conn, """
            SELECT sport_name, total_revenue, total_expenses, survey_year
            FROM eada_sports
            WHERE unitid = ?
              AND survey_year = (
                  SELECT MAX(survey_year) FROM eada_sports WHERE unitid = ?
              )
            ORDER BY total_expenses DESC
        """, (unitid, unitid))

    return {
        "master":                master,
        "quant_latest":          quant_latest,
        "quant_history":         quant_history,
        "stress":                stress,
        "narratives":            narratives,
        "part_ix_history":       part_ix_history,
        "part_ix_peer_context":  part_ix_peer_context,
        "schedule_d_history":    schedule_d_history,
        "compensation_rows":     compensation_rows,
        "part_viii_row":         part_viii_row,
        "governance_row":        governance_row,
        "eada_instlevel_history": eada_instlevel_history,
        "eada_sports_rows":      eada_sports_rows,
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
    _t0 = time.monotonic()

    query_type = classify_query(query)
    entities   = extract_entities(query)

    # Comparison and profile queries default to PRIMARY_YEAR when no year is
    # specified.  max(years_in_db) would return 2023 (26.9% completeness —
    # financial data pending FY2024 990 filings), producing a half-populated
    # comparison.  Trend and sector queries intentionally use the latest year.
    if year is None and query_type in ("comparison", "institution_profile"):
        year = PRIMARY_YEAR

    _t_db_start = time.monotonic()

    quant_conn = sqlite3.connect(str(DB_QUANT))
    db990_conn = sqlite3.connect(str(DB_990))
    ipeds_conn = sqlite3.connect(str(DB_IPEDS))
    eada_conn  = sqlite3.connect(str(DB_EADA))

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
        data = _load_institution_data(uid, quant_conn, db990_conn, ipeds_conn, primary_year, eada_conn)
        institution_data[uid] = data

    quant_conn.close()
    db990_conn.close()
    ipeds_conn.close()
    eada_conn.close()

    _t_db_end = time.monotonic()

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

    # Scorecard single-year caveat — surfaces in synthesizer when net price /
    # earnings metrics are present.  Update vintage year when new Scorecard
    # data is loaded (see Annual Refresh Policy in CLAUDE.md).
    scorecard_note = (
        "Scorecard metrics (net_price, earnings_to_debt_ratio, "
        "net_price_to_earnings, grad_rate_150) reflect a single data vintage "
        "(2022). Trend data unavailable pending historical bulk download from "
        "data.ed.gov. Do not extrapolate direction from these values."
    )

    # ── Search layer ──────────────────────────────────────────────────────
    # Activates when the query has a current-events or recent-news dimension.
    # Lazy import avoids circular dependency (retrieval.sql_retriever imports
    # extract_entities from this module).
    search_results: list = []
    try:
        from jenni.retrieval.search_layer import JENNISearchLayer, needs_web_search  # noqa: PLC0415
        if needs_web_search(query):
            search_layer = JENNISearchLayer()
            search_results = search_layer.search(
                query, entities=entities, run_web=True
            )
    except Exception:
        # Search layer failures are non-fatal — SQL context is always complete
        pass

    _t_end = time.monotonic()

    return {
        "query":                   query,
        "query_type":              query_type,
        "entities":                entities,
        "accordion":               accordion,
        "institution_data":        institution_data,
        "peer_data":               peer_data,
        "data_quality":            dq,
        "scorecard_single_year_note": scorecard_note,
        "search_results":          search_results,
        "_timing": {
            "resolver_ms": int((_t_end  - _t0)        * 1000),
            "db_query_ms": int((_t_db_end - _t_db_start) * 1000),
        },
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
