#!/usr/bin/env python3
"""
ingestion/narrative_seeder.py
--------------------------------------
Seed the institution_narratives table in institution_quant.db.

Phase 1 auto-seeding:
  1. 'identity'          — for all ~13,609 institutions in institution_master
  2. 'stress_signal'     — for 1,363 institutions in financial_stress_signals
  3. 'financial_profile' — for institutions in institution_quant (latest year per institution)

Phase 2 hand-crafted:
  High-confidence narratives for the 5 MA validation institutions.
  These override any auto-seeded rows for the same (unitid, narrative_type).

All inserts use INSERT OR REPLACE — idempotent, safe to re-run.

Usage:
    .venv/bin/python3 ingestion/narrative_seeder.py \
        --ipeds  data/databases/ipeds_data.db \
        --db990  data/databases/990_data.db \
        --quant  data/databases/institution_quant.db

    .venv/bin/python3 ingestion/narrative_seeder.py \
        --ipeds  data/databases/ipeds_data.db \
        --db990  data/databases/990_data.db \
        --quant  data/databases/institution_quant.db \
        --dry-run
"""

import argparse
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "institution_narratives_schema.sql"
TODAY = "2026-03-28"

# ---------------------------------------------------------------------------
# Reference maps
# ---------------------------------------------------------------------------

CARNEGIE_LABELS = {
    15: "Doctoral University (R1 — Very High Research Activity)",
    16: "Doctoral University (R2 — High Research Activity)",
    17: "Doctoral/Professional University",
    21: "Master's University (M1 — Larger Programs)",
    22: "Master's University (M2 — Medium Programs)",
    23: "Master's University (M3 — Small Programs)",
    31: "Baccalaureate College: Arts & Sciences Focus",
    32: "Baccalaureate College: Diverse Fields",
    33: "Baccalaureate/Associate's College",
    40: "Associate's College: High Transfer",
    41: "Associate's College: High Traditional",
    42: "Associate's College: High Nontraditional",
    43: "Associate's College: Mixed Transfer/Traditional",
    44: "Associate's College: Mixed Transfer/Nontraditional",
    45: "Associate's College: Mixed Traditional/Nontraditional",
    46: "Mixed Associate's and Bachelor's",
    47: "Associate's College",
    51: "Special Focus: Arts & Design",
    52: "Special Focus: Health Professions",
    53: "Special Focus: Technical/Vocational",
    54: "Special Focus: Other Fields",
    55: "Special Focus: Faith-Related Institutions",
    56: "Special Focus: Medical School or Center",
    57: "Special Focus: Other Health Professions",
    58: "Special Focus: Engineering",
    59: "Special Focus: Technology",
    60: "Special Focus: Business & Management",
    61: "Special Focus: Arts, Music & Design",
    62: "Special Focus: Law",
    63: "Special Focus: Other Special Focus",
    65: "Tribal College or University",
}

ICLEVEL_LABELS  = {1: "four-year", 2: "two-year", 3: "less-than-two-year"}
CONTROL_LABELS  = {1: "public", 2: "private nonprofit", 3: "private for-profit"}

STRESS_SIGNAL_LABELS = [
    ("sig_deficit_yrs",       "operating deficit"),
    ("sig_neg_assets_yrs",    "negative net assets"),
    ("sig_asset_decline_yrs", "declining total assets"),
    ("sig_high_debt_yrs",     "high debt ratio"),
    ("sig_low_cash_yrs",      "low cash reserves"),
    ("sig_end_stress_yrs",    "endowment stress"),
    ("sig_low_runway_yrs",    "low operating runway"),
    ("sig_low_prog_yrs",      "low program-services ratio"),
]

SCORE_BANDS = [
    (6.5, "CRITICAL"),
    (5.0, "HIGH"),
    (3.5, "Elevated"),
    (2.0, "Baseline"),
    (0.1, "Marginal"),
    (0.0, "Clean"),
]


# ---------------------------------------------------------------------------
# Hand-crafted narratives — 5 MA validation institutions
# ---------------------------------------------------------------------------

HAND_CRAFTED: list[dict] = [
    # ---- Babson College (164580) ----
    {
        "unitid": 164580,
        "narrative_type": "identity",
        "content": (
            "Babson College is a private nonprofit, four-year business-focused institution in "
            "Wellesley, Massachusetts, founded in 1919 by entrepreneur Roger W. Babson. Carnegie "
            "Classification M3 (Master's University: Small Programs). Widely regarded as the "
            "leading institution in entrepreneurship education, ranked #1 for entrepreneurship "
            "by U.S. News & World Report for over 30 consecutive years. Enrollment: approximately "
            "2,400 undergraduates and 1,700 graduate students. The F.W. Olin Graduate School of "
            "Business offers MBA and other master's programs. Fiscal year ends June 30. "
            "EIN: 042103544. UNITID: 164580."
        ),
        "confidence": "high",
        "source": "hand_crafted",
    },
    {
        "unitid": 164580,
        "narrative_type": "financial_profile",
        "content": (
            "Babson's financial model is tuition-dependent — approximately 55–60% of revenue "
            "derives from student tuition and fees. FY2023 total revenue: $344M (fiscal year ending "
            "June 2023), down from $398M in FY2022 (which included elevated investment returns). "
            "Endowment: approximately $662M at end of FY2022, providing roughly 2.2 years of "
            "operating runway — adequate but below the private master's university median. "
            "Debt-to-assets ratio: moderate. Financial stress signals across FY2020–2022: none "
            "confirmed. Babson is financially stable. Primary financial risk: tuition concentration "
            "combined with demographic exposure in the Northeast (declining 18-year-old population "
            "through the early 2030s)."
        ),
        "confidence": "high",
        "source": "hand_crafted",
        "valid_from": 2020,
    },
    {
        "unitid": 164580,
        "narrative_type": "enrollment_profile",
        "content": (
            "Babson enrollment grew modestly over 2019–2023. Undergraduate yield rate approximately "
            "39–42% — solid but not exceptional among business schools. Draws heavily from the "
            "Northeast and internationally. Graduate enrollment (primarily MBA) represents "
            "approximately 40% of headcount. Demographic exposure: as a private institution "
            "concentrated in New England, Babson faces structural enrollment headwinds shared by "
            "all Northeast private institutions through the early 2030s. The institution's "
            "entrepreneurship brand provides some insulation against pure price competition."
        ),
        "confidence": "high",
        "source": "hand_crafted",
        "valid_from": 2019,
    },
    # ---- Bentley University (164739) ----
    {
        "unitid": 164739,
        "narrative_type": "identity",
        "content": (
            "Bentley University is a private nonprofit, four-year business-focused institution in "
            "Waltham, Massachusetts, founded in 1917. Carnegie Classification M1 (Master's "
            "University: Larger Programs). Enrollment: approximately 4,200 undergraduates and "
            "1,200 graduate students. Known for integrating business education with liberal arts "
            "and technology — the 'Arts and Sciences in Business' model. Strong placement record "
            "in accounting, finance, and corporate analytics. Fiscal year ends June 30. "
            "EIN: 041081650. UNITID: 164739."
        ),
        "confidence": "high",
        "source": "hand_crafted",
    },
    {
        "unitid": 164739,
        "narrative_type": "financial_profile",
        "content": (
            "Bentley's financial model is highly tuition-dependent with revenue concentrated in "
            "undergraduate tuition. Endowment: approximately $333M at end of FY2022, providing "
            "approximately 1.5 years of operating runway — below the private master's university "
            "median. Financial stress signals across FY2020–2022: none confirmed. Bentley is "
            "financially stable. Primary risks: tuition concentration and competitive pressure "
            "in the business education market from both ranked peers and lower-cost alternatives."
        ),
        "confidence": "high",
        "source": "hand_crafted",
        "valid_from": 2020,
    },
    # ---- Boston College (164924) ----
    {
        "unitid": 164924,
        "narrative_type": "identity",
        "content": (
            "Boston College is a private nonprofit Jesuit research university in Chestnut Hill, "
            "Massachusetts, founded in 1863 by the Society of Jesus. Carnegie Classification R2 "
            "(Doctoral University: High Research Activity). Enrollment: approximately 9,500 "
            "undergraduates and 5,000 graduate and professional students. Member of the Atlantic "
            "Coast Conference (ACC), Division I athletics. Fiscal year ends June 30. "
            "EIN: 042103545. UNITID: 164924. IMPORTANT: As a Jesuit institution, BC's president "
            "(Father William P. Leahy, S.J.) does NOT appear on Schedule J — compensation flows "
            "through the Society of Jesus, not the institution directly. The highest Schedule J "
            "earner is typically a head coach or investment professional."
        ),
        "confidence": "high",
        "source": "hand_crafted",
    },
    {
        "unitid": 164924,
        "narrative_type": "financial_profile",
        "content": (
            "Boston College is financially strong with a well-diversified revenue base: tuition, "
            "endowment distributions, research, gifts, and athletics (ACC member). FY2023 total "
            "revenue approximately $1.2B. Endowment: approximately $3.7B at end of FY2022 "
            "(endowment runway approximately 2.75 years). NOTE: FY2022 IPEDS Finance shows "
            "expenses ($1.02B) exceeding revenue ($897M) — this reflects an investment year, "
            "not financial distress; net assets are $4.7B, confirming strong financial health. "
            "Program services allocation: approximately 86% of total expenses. Financial stress "
            "signals across FY2020–2022: none confirmed. BC's financial position is among the "
            "strongest in the private doctoral tier in New England."
        ),
        "confidence": "high",
        "source": "hand_crafted",
        "valid_from": 2020,
    },
    # ---- Harvard University (166027) ----
    {
        "unitid": 166027,
        "narrative_type": "identity",
        "content": (
            "Harvard University is a private nonprofit doctoral research university in Cambridge, "
            "Massachusetts, founded in 1636 — the oldest institution of higher learning in the "
            "United States. Carnegie Classification R1 (Doctoral University: Very High Research "
            "Activity). Enrollment: approximately 7,000 undergraduates, 13,000 graduate students, "
            "and 4,000 professional students across 12 schools and the Radcliffe Institute. "
            "Fiscal year ends June 30. EIN: 042103580. UNITID: 166027. "
            "Harvard files 400+ related organizations on Schedule R annually (subsidiaries, "
            "investment vehicles, affiliates)."
        ),
        "confidence": "high",
        "source": "hand_crafted",
    },
    {
        "unitid": 166027,
        "narrative_type": "financial_profile",
        "content": (
            "Harvard's financial position is sui generis among U.S. institutions. Endowment: "
            "$49.4B at end of FY2022 (down from $53.2B in FY2021 due to market conditions), "
            "providing approximately 7.9 years of operating runway — the highest among all U.S. "
            "universities by a wide margin. Revenue is highly diversified: endowment distributions "
            "(~35%), research grants (~25%), tuition and fees (~20%), and gifts. Tuition dependency "
            "is low by sector standards. Program services allocation: approximately 87.8% of "
            "expenses. Financial stress signals: none. Harvard is the benchmark for institutional "
            "financial strength. The analytical questions for Harvard are not solvency or health "
            "but capital allocation: endowment spending rate, investment return vs. policy rate, "
            "and payout policy evolution."
        ),
        "confidence": "high",
        "source": "hand_crafted",
        "valid_from": 2019,
    },
    {
        "unitid": 166027,
        "narrative_type": "peer_context",
        "content": (
            "Harvard's meaningful peer set is extremely small: MIT, Stanford, Yale, Princeton, "
            "Penn, Columbia, Duke. Its Carnegie classification peer group (R1 doctoral universities) "
            "includes ~335 institutions with dramatically different financial profiles. Using the "
            "Carnegie R1 peer group for Harvard financial benchmarking will place Harvard as an "
            "extreme outlier on virtually every metric — endowment per student, revenue per FTE, "
            "operating margin. When benchmarking Harvard, always scope to institutions with "
            "endowments above $10B, or explicitly state the peer group construction and its "
            "limitations."
        ),
        "confidence": "high",
        "source": "hand_crafted",
    },
    # ---- MIT (166683) ----
    {
        "unitid": 166683,
        "narrative_type": "identity",
        "content": (
            "Massachusetts Institute of Technology (MIT) is a private nonprofit doctoral research "
            "university in Cambridge, Massachusetts, founded in 1861. Carnegie Classification R1 "
            "(Doctoral University: Very High Research Activity). Enrollment: approximately 4,500 "
            "undergraduates and 7,000 graduate students, with emphasis on science, engineering, "
            "and technology. 97 Nobel laureates affiliated. Fiscal year ends June 30. "
            "EIN: 042103594. UNITID: 166683. DATA GAP: FY2013 (fiscal_year_end=2013, "
            "TAX_PERIOD=201306) is absent from the ProPublica structured dataset — not a loader "
            "error; that filing year was not structured by ProPublica. Total 990 coverage: "
            "FY2012–FY2023 minus FY2013 = 11 filing years."
        ),
        "confidence": "high",
        "source": "hand_crafted",
    },
    {
        "unitid": 166683,
        "narrative_type": "financial_profile",
        "content": (
            "MIT's financial model is research-dominated — federal research grants and contracts "
            "represent the largest single revenue category, exceeding tuition revenue. Endowment: "
            "$24.7B at end of FY2022, providing approximately 4.8 years of operating runway. "
            "Overhead ratio: approximately 21.8% of expenses — significantly above sector median "
            "(13–14%). This is expected for a high-research-intensity institution; indirect cost "
            "recovery on federal grants is a material revenue component, not institutional "
            "inefficiency. Program services: approximately 78.2% of total expenses. Financial "
            "stress signals: none. MIT's primary financial risk is federal research funding "
            "volatility — a policy risk, not an institutional financial weakness."
        ),
        "confidence": "high",
        "source": "hand_crafted",
        "valid_from": 2019,
    },
]


# ---------------------------------------------------------------------------
# Auto-seed builders
# ---------------------------------------------------------------------------

def build_identity_narrative(row: dict) -> str:
    name  = row.get("institution_name") or "Unknown institution"
    ctrl  = CONTROL_LABELS.get(row.get("control"), "")
    level = ICLEVEL_LABELS.get(row.get("iclevel"), "")
    city  = row.get("city") or ""
    state = row.get("state_abbr") or ""
    carn  = CARNEGIE_LABELS.get(row.get("carnegie_basic"))

    location   = f"{city}, {state}" if city and state else (state or city or "unknown location")
    descriptor = " ".join(filter(None, [ctrl, level, "institution"])).strip()

    parts = [f"{name} is a {descriptor} in {location}."]
    if carn:
        parts.append(f"Carnegie Classification: {carn}.")

    badges = []
    if row.get("hbcu") == 1:
        badges.append("Historically Black College or University (HBCU)")
    if row.get("jesuit_institution") == 1:
        badges.append("member of the Association of Jesuit Colleges and Universities (AJCU)")
    if row.get("land_grant") == 1:
        badges.append("land-grant institution")
    if row.get("tribal_college") == 1:
        badges.append("Tribal College or University")
    if badges:
        badge_str = ", ".join(badges)
        parts.append(f"Designated: {badge_str}.")

    ein = row.get("ein")
    uid = row.get("unitid")
    if ein:
        parts.append(f"EIN: {ein}. UNITID: {uid}.")
    else:
        parts.append(f"UNITID: {uid}.")

    return " ".join(parts)


def build_stress_narrative(row: dict) -> str:
    score   = row.get("composite_stress_score") or 0.0
    confirm = row.get("confirmed_signal_count") or 0
    emerge  = row.get("emerging_signal_count") or 0
    single  = row.get("single_year_count") or 0
    yrs     = row.get("years_available") or 0
    yr_rng  = row.get("signal_year_range") or "FY2020–2022"
    comp    = row.get("data_completeness_pct") or 0.0

    band = "Clean"
    for threshold, label in SCORE_BANDS:
        if score >= threshold:
            band = label
            break

    if score == 0:
        return (
            f"Financial stress analysis ({yr_rng}, {yrs}-year window): "
            f"No stress signals detected. Financial metrics within normal operating range. "
            f"Data completeness: {comp:.0f}%."
        )

    sig_parts = []
    for col, label in STRESS_SIGNAL_LABELS:
        val = row.get(col) or 0
        if val > 0:
            sig_parts.append(f"{label} ({val}/{yrs} yrs)")

    signals_str = "; ".join(sig_parts) if sig_parts else "multiple signals"

    parts = [
        f"Financial stress analysis ({yr_rng}, {yrs}-year window): "
        f"{band} stress level (composite score {score:.2f})."
    ]
    if confirm > 0:
        parts.append(
            f"{confirm} confirmed signal(s) — fired in all available years — "
            f"indicating sustained, not transient, distress: {signals_str}."
        )
    elif emerge > 0:
        parts.append(
            f"{emerge} emerging signal(s) — fired in 2 of 3 years — "
            f"indicating developing stress: {signals_str}."
        )
    elif single > 0:
        parts.append(
            f"{single} single-year signal(s) — possible COVID artifact; "
            f"lower confidence: {signals_str}."
        )
    parts.append(f"Data completeness: {comp:.0f}%.")
    return " ".join(parts)


def build_financial_profile_narrative(row: dict) -> str:
    name = row.get("institution_name") or "This institution"
    year = row.get("survey_year", "")
    comp = row.get("data_completeness_pct")

    if comp is not None and comp < 25:
        return (
            f"Financial profile (survey_year {year}): "
            f"Insufficient data for narrative generation (completeness: {comp:.0f}%). "
            f"Likely a public institution (no 990 filing) or an early partial-year row "
            f"where FY filings are not yet available in TEOS."
        )

    parts = [f"Financial profile (survey_year {year}):"]

    op_mgn = row.get("operating_margin_value")
    if op_mgn is not None:
        pct_rank = row.get("operating_margin_peer_pct")
        pct_str  = f" ({pct_rank:.0f}th percentile among Carnegie peers)" if pct_rank is not None else ""
        sign_str = "positive" if op_mgn > 0 else "negative"
        parts.append(f"Operating margin: {op_mgn*100:.1f}% ({sign_str}){pct_str}.")

    td = row.get("tuition_dependency_value")
    if td is not None:
        parts.append(f"Tuition dependency: {td*100:.0f}% of revenue.")

    end_ps = row.get("endowment_per_student_value")
    if end_ps is not None:
        parts.append(f"Endowment per FTE student: ${end_ps:,.0f}.")

    runway = row.get("endowment_runway_value")
    if runway is not None:
        parts.append(f"Endowment runway: {runway:.1f} years of operating expenses.")

    enr_cagr = row.get("enrollment_3yr_cagr_value")
    if enr_cagr is not None:
        direction = "growing" if enr_cagr > 0.001 else ("declining" if enr_cagr < -0.001 else "flat")
        parts.append(f"Enrollment 3-year CAGR: {enr_cagr*100:.1f}% ({direction}).")

    if comp is not None:
        parts.append(f"Data completeness: {comp:.0f}%.")

    if len(parts) == 1:
        parts.append("Detailed financial metrics not yet available for this institution-year.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def dict_rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def upsert(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO institution_narratives
            (unitid, narrative_type, content, confidence,
             valid_from, valid_until, source, formula_version, last_verified)
        VALUES
            (:unitid, :narrative_type, :content, :confidence,
             :valid_from, :valid_until, :source, :formula_version, :last_verified)
    """, {
        "unitid":          row["unitid"],
        "narrative_type":  row["narrative_type"],
        "content":         row["content"],
        "confidence":      row.get("confidence", "medium"),
        "valid_from":      row.get("valid_from"),
        "valid_until":     row.get("valid_until"),
        "source":          row.get("source", "auto_seeded"),
        "formula_version": row.get("formula_version", "1.0"),
        "last_verified":   row.get("last_verified", TODAY),
    })


# ---------------------------------------------------------------------------
# Main seed routine
# ---------------------------------------------------------------------------

def seed(ipeds_db: str, db990: str, quant_db: str, dry_run: bool = False) -> dict:
    q_conn    = sqlite3.connect(quant_db)
    ip_conn   = sqlite3.connect(ipeds_db)
    db9_conn  = sqlite3.connect(db990)

    if not dry_run:
        q_conn.executescript(SCHEMA_PATH.read_text())
        q_conn.commit()
        logger.info("Schema initialized in institution_quant.db")

    # ---- Source data ----
    logger.info("Loading institution_master …")
    masters = dict_rows(ip_conn, "SELECT * FROM institution_master")
    master_by_uid = {r["unitid"]: r for r in masters}
    logger.info(f"  {len(masters):,} institutions")

    logger.info("Loading financial_stress_signals …")
    stress_rows = dict_rows(db9_conn,
        "SELECT * FROM financial_stress_signals WHERE unitid IS NOT NULL")
    stress_by_uid = {r["unitid"]: r for r in stress_rows}
    logger.info(f"  {len(stress_by_uid):,} stress-scored institutions")

    logger.info("Loading institution_quant (latest year per institution) …")
    quant_latest_raw = dict_rows(q_conn, """
        SELECT * FROM institution_quant
        WHERE (unitid, survey_year) IN (
            SELECT unitid, MAX(survey_year) FROM institution_quant GROUP BY unitid
        )
    """)
    quant_by_uid = {}
    for r in quant_latest_raw:
        uid = r["unitid"]
        # attach institution_name from master
        m = master_by_uid.get(uid, {})
        quant_by_uid[uid] = {**r, "institution_name": m.get("institution_name")}
    logger.info(f"  {len(quant_by_uid):,} institutions in institution_quant")

    total = ident = stress = fin = hc = 0

    # ---- Phase 1: identity ----
    logger.info("Seeding identity narratives …")
    for m in masters:
        uid     = m["unitid"]
        content = build_identity_narrative(m)
        if not dry_run:
            upsert(q_conn, {
                "unitid": uid, "narrative_type": "identity",
                "content": content, "confidence": "medium",
                "source": "auto_seeded",
            })
        ident += 1
        total += 1
    logger.info(f"  {ident:,} identity narratives seeded")

    # ---- Phase 2: stress_signal ----
    logger.info("Seeding stress_signal narratives …")
    for uid, s in stress_by_uid.items():
        content = build_stress_narrative(s)
        conf    = "high" if (s.get("years_available") or 0) >= 2 else "medium"
        if not dry_run:
            upsert(q_conn, {
                "unitid": uid, "narrative_type": "stress_signal",
                "content": content, "confidence": conf,
                "valid_from": 2020, "valid_until": 2022,
                "source": "auto_seeded",
            })
        stress += 1
        total  += 1
    logger.info(f"  {stress:,} stress_signal narratives seeded")

    # ---- Phase 3: financial_profile ----
    logger.info("Seeding financial_profile narratives …")
    for uid, q in quant_by_uid.items():
        content = build_financial_profile_narrative(q)
        yr      = q.get("survey_year")
        if not dry_run:
            upsert(q_conn, {
                "unitid": uid, "narrative_type": "financial_profile",
                "content": content, "confidence": "medium",
                "valid_from": yr, "valid_until": yr,
                "source": "auto_seeded",
            })
        fin   += 1
        total += 1
    logger.info(f"  {fin:,} financial_profile narratives seeded")

    # ---- Phase 4: hand-crafted ----
    logger.info("Seeding hand-crafted narratives (5 validation institutions) …")
    for row in HAND_CRAFTED:
        if dry_run:
            logger.info(f"  DRY: unitid={row['unitid']} type={row['narrative_type']}")
        else:
            upsert(q_conn, row)
        hc    += 1
        total += 1
    logger.info(f"  {hc} hand-crafted rows inserted")

    if not dry_run:
        q_conn.commit()

    q_conn.close()
    ip_conn.close()
    db9_conn.close()

    result = {"total": total, "identity": ident, "stress": stress,
              "financial": fin, "hand_crafted": hc}
    logger.info(
        f"Narrative seed complete: {total:,} total rows "
        f"({ident:,} identity, {stress:,} stress, {fin:,} financial, {hc} hand-crafted)"
    )
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="Seed institution_narratives table")
    parser.add_argument("--ipeds",   required=True, help="ipeds_data.db path")
    parser.add_argument("--db990",   required=True, help="990_data.db path")
    parser.add_argument("--quant",   required=True, help="institution_quant.db path (target)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be seeded without writing")
    args = parser.parse_args()

    seed(args.ipeds, args.db990, args.quant, args.dry_run)


if __name__ == "__main__":
    main()
