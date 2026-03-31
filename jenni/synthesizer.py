"""
jenni/synthesizer.py
--------------------------------------
Claude API integration. Receives a context package from query_resolver,
formats it for the model, and returns the synthesized response text.

Model routing:
  haiku  — 'data' queries: simple factual lookups, raw table requests
  sonnet — 'analysis', 'comparison', 'trend', 'stress': standard analytical work
  opus   — 'sector': complex synthesis, multi-institution patterns, sector-wide analysis

The API key is loaded from .env via jenni.config.get_api_key().
It is NEVER logged, printed, or included in any output.
"""

from __future__ import annotations

import time

import anthropic

from jenni.config import get_api_key, MODEL_HAIKU, MODEL_SONNET, MODEL_OPUS
from jenni.prompts.system import SYSTEM_PROMPT

_MODEL_ROUTING: dict[str, str] = {
    "data":               MODEL_HAIKU,
    "analysis":           MODEL_SONNET,
    "institution_profile":MODEL_SONNET,
    "comparison":         MODEL_SONNET,
    "trend":              MODEL_SONNET,
    "stress":             MODEL_SONNET,
    "sector":             MODEL_OPUS,
}

# Carnegie Basic Classification codes for research-intensive tiers
# (c18basic / c21basic: 15=R1, 16=R2).  These produce denser context
# and require a larger token budget.
_RESEARCH_CARNEGIE = {15, 16}

_MAX_TOKENS_STANDARD = 3072   # sonnet; single institution, M1/M3 peer group
_MAX_TOKENS_COMPLEX  = 4096   # sonnet with large peer group or R1/R2 Carnegie
_MAX_TOKENS_OPUS     = 4096   # opus sector queries


def _is_complex_context(context: dict) -> bool:
    """Return True when the context warrants an expanded token budget."""
    peer_n = (context.get("peer_data") or {}).get("carnegie_peer_group_size") or 0
    if peer_n > 20:
        return True
    for entity in context.get("entities", []):
        if entity.get("carnegie_basic") in _RESEARCH_CARNEGIE:
            return True
    return False

# Display labels for the footer
_MODEL_LABELS: dict[str, str] = {
    MODEL_HAIKU:  "Haiku 4.5 (fast lookup)",
    MODEL_SONNET: "Sonnet 4.6 (standard analysis)",
    MODEL_OPUS:   "Opus 4.6 (complex synthesis)",
}

# Metric display table: (label, column_suffix, format_str)
_DISPLAY_METRICS: list[tuple[str, str, str]] = [
    ("Operating Margin",        "operating_margin",        "{:+.1%}"),
    ("Tuition Dependency",      "tuition_dependency",      "{:.1%}"),
    ("Debt-to-Assets",          "debt_to_assets",          "{:.1%}"),
    ("Debt-to-Revenue",         "debt_to_revenue",         "{:.1f}×"),
    ("Endowment / Student",     "endowment_per_student",   "${:,.0f}"),
    ("Endowment Runway",        "endowment_runway",        "{:.1f} yrs"),
    ("Endowment Spending Rate", "endowment_spending_rate", "{:.1%}"),
    ("Program Services %",      "program_services_pct",    "{:.1%}"),
    ("Overhead Ratio",          "overhead_ratio",          "{:.1%}"),
    ("Fundraising Efficiency",  "fundraising_efficiency",  "{:.1f}×"),
    ("Revenue / FTE",           "revenue_per_fte",         "${:,.0f}"),
    ("Expense / FTE",           "expense_per_fte",         "${:,.0f}"),
    ("Enrollment CAGR 3yr",     "enrollment_3yr_cagr",     "{:+.1%}"),
    ("Yield Rate",              "yield_rate",              "{:.1%}"),
    ("Admit Rate",              "admit_rate",              "{:.1%}"),
    ("Application CAGR 3yr",    "app_3yr_cagr",            "{:+.1%}"),
    ("Grad Rate (150%)",        "grad_rate_150",           "{:.1%}"),
    ("Retention Rate",          "retention_rate",          "{:.1%}"),
    ("Grad Enrollment %",       "grad_enrollment_pct",     "{:.1%}"),
    ("Pell % Students",         "pell_pct",                "{:.1%}"),
    ("Net Price",               "net_price",               "${:,.0f}"),
    ("Earnings/Debt Ratio",     "earnings_to_debt_ratio",  "{:.2f}×"),
    ("Net Price/Earnings",      "net_price_to_earnings",   "{:.2f}"),
    ("Athletics % Expenses",    "athletics_to_expense_pct","{:.1%}"),
    ("Athletics Net",           "athletics_net",           "${:,.0f}"),
    ("Athletics / Student",     "athletics_per_student",   "${:,.0f}"),
]


def _fmt(fmt_str: str, value) -> str:
    try:
        return fmt_str.format(value)
    except (ValueError, TypeError):
        return str(value)


def _format_quant_block(q: dict) -> str:
    """Format institution_quant row as a readable metrics block."""
    lines = []
    for label, suffix, fmt in _DISPLAY_METRICS:
        val = q.get(f"{suffix}_value")
        if val is None:
            continue
        val_str  = _fmt(fmt, val)
        pct      = q.get(f"{suffix}_peer_pct")
        trend    = q.get(f"{suffix}_trend_dir") or ""
        pct_str  = f" | {pct*100:.0f}th pctile" if pct is not None else ""
        trend_str = f" | {trend}" if trend else ""
        lines.append(f"  {label:<28} {val_str:<14}{pct_str}{trend_str}")

    comp = q.get("data_completeness_pct")
    if comp is not None:
        lines.append(f"  {'Data Completeness':<28} {comp:.1f}%")
    peer_n = q.get("carnegie_peer_group_size")
    if peer_n:
        lines.append(f"  {'Carnegie Peers (n)':<28} {peer_n}")
    return "\n".join(lines) if lines else "  (No metric data available for this year)"


def _format_history_summary(history: list[dict]) -> str:
    """Summarize multi-year history into a compact block."""
    if not history:
        return "  No historical data."
    years   = [r["survey_year"] for r in history]
    margins = [r.get("operating_margin_value") for r in history]
    endows  = [r.get("endowment_per_student_value") for r in history]
    enr     = [r.get("enrollment_3yr_cagr_value") for r in history]

    def series(label, values, fmt):
        pairs = [(y, v) for y, v in zip(years, values) if v is not None]
        if not pairs:
            return ""
        return f"  {label}: " + "  ".join(
            f"{y}: {_fmt(fmt, v)}" for y, v in pairs[-5:]
        )

    lines = [f"  Years in DB: {min(years)}–{max(years)} ({len(years)} years)"]
    s = series("Op. Margin", margins, "{:+.1%}")
    if s:
        lines.append(s)
    s = series("Endow/Student", endows, "${:,.0f}")
    if s:
        lines.append(s)
    s = series("Enr. CAGR 3yr", enr, "{:+.1%}")
    if s:
        lines.append(s)
    return "\n".join(lines)


def _format_context_for_model(context: dict) -> str:
    """Convert the context package into the user-turn prompt."""
    parts: list[str] = []

    # Header
    parts.append(f"QUERY: {context['query']}")
    parts.append(f"QUERY TYPE: {context['query_type'].upper()}")
    acc = context["accordion"]
    parts.append(
        f"ACCORDION POSITION: {acc['zone'].upper()} — "
        f"epistemic posture: {acc['epistemic_posture'].upper()}"
    )
    parts.append(f"POSTURE NOTE: {acc['posture_note']}")
    if acc.get("years_in_db"):
        parts.append(
            f"DATA YEARS AVAILABLE: {acc['years_in_db'][0]}–{acc['years_in_db'][-1]} "
            f"({len(acc['years_in_db'])} years)"
        )
    parts.append(f"PRIMARY YEAR: {acc['primary_year']}")
    parts.append("")

    # Institution blocks
    for uid, data in context["institution_data"].items():
        m     = data.get("master", {})
        q     = data.get("quant_latest", {})
        hist  = data.get("quant_history", [])
        stress = data.get("stress")
        narrs  = data.get("narratives", {})

        name = m.get("institution_name", f"UNITID {uid}")
        state = m.get("state_abbr", "")
        ctrl  = m.get("control_label", "")
        carn  = m.get("carnegie_basic", "")
        parts.append(f"{'='*60}")
        parts.append(f"INSTITUTION: {name} | {state} | {ctrl} | Carnegie {carn}")
        parts.append(f"{'='*60}")

        # Pre-encoded narratives — explicitly labeled
        for narr_type in ("identity", "financial_profile", "enrollment_profile",
                          "peer_context", "stress_signal", "athletics", "governance"):
            content = narrs.get(narr_type)
            if content:
                parts.append(f"[pre-encoded:{narr_type}] {content}")
        parts.append("")

        # Stress
        if stress:
            score    = stress.get("composite_stress_score") or 0
            conf     = stress.get("confirmed_signal_count") or 0
            band     = stress.get("narrative_flag") or _score_band(score, conf)
            parts.append(f"STRESS SCORE: {score:.2f} ({band}) | "
                         f"Confirmed signals: {conf} | "
                         f"Years: {stress.get('years_available', 0)}")
            parts.append("")

        # Key metrics
        if q:
            sy = q.get("survey_year", acc["primary_year"])
            parts.append(f"KEY METRICS (institution_quant, survey_year={sy}):")
            parts.append(_format_quant_block(q))
            parts.append("")

        # History
        if len(hist) > 1:
            parts.append(f"HISTORICAL SUMMARY ({len(hist)} years):")
            parts.append(_format_history_summary(hist))
            parts.append("")

        # Part IX functional expense detail — included when query involves expense
        # analysis or for comparison/profile queries with TEOS data available.
        part_ix = data.get("part_ix_history", [])
        if part_ix and _needs_part_ix(context["query"], context["query_type"]):
            parts.append(f"PART IX — FUNCTIONAL EXPENSES (form990_part_ix, TEOS/irsx, {len(part_ix)} years):")
            parts.append(_format_part_ix_block(part_ix))
            parts.append("")

    # Scorecard single-year caveat — always present; model must cite when
    # referencing net_price, earnings_to_debt_ratio, net_price_to_earnings,
    # or grad_rate_150.
    sc_note = context.get("scorecard_single_year_note")
    if sc_note:
        parts.append("SCORECARD DATA CAVEAT:")
        parts.append(f"  {sc_note}")
        parts.append("")

    # Current web context — present only when search layer activated
    search_results = context.get("search_results") or []
    web_results = [r for r in search_results if r.domain in ("web", "news")]
    if web_results:
        parts.append("CURRENT WEB CONTEXT:")
        parts.append(
            "  (Retrieved via live web search — external sources, not structured database."
            " Treat as supplemental current-events context; verify before citing.)"
        )
        parts.append("")
        for result in web_results:
            for doc in result.documents[:8]:
                if not doc.content.strip():
                    continue
                parts.append(f"  [external:web] {doc.content.strip()}")
                if doc.url:
                    parts.append(f"    Source: {doc.url}")
        parts.append("")

    # Data quality footer
    dq = context.get("data_quality", {})
    parts.append("─" * 60)
    parts.append("DATA QUALITY:")
    parts.append(f"  Primary year:    {dq.get('primary_year', 'unknown')}")
    parts.append(f"  Completeness:    {dq.get('completeness_pct', 'unknown')}%")
    parts.append(f"  Sources:         {', '.join(dq.get('sources', []))}")
    missing = dq.get("missing_metrics", [])
    if missing:
        parts.append(f"  Missing:         {'; '.join(missing)}")
    parts.append("─" * 60)

    return "\n".join(parts)


# Words that trigger inclusion of Part IX functional expense detail in the prompt
_EXPENSE_WORDS = {
    "advertising", "marketing", "spend", "spending", "budget",
    "promotion", "promotional", "expense", "expenses", "expenditure",
    "expenditures", "cost", "costs",
}


def _needs_part_ix(query: str, query_type: str) -> bool:
    """Return True when Part IX functional expense detail should be included."""
    if query_type in ("comparison", "institution_profile"):
        return True
    q_tokens = set(query.lower().split())
    return bool(q_tokens & _EXPENSE_WORDS)


def _format_part_ix_block(history: list[dict]) -> str:
    """Format form990_part_ix rows into a readable expense block."""
    if not history:
        return "  (No Part IX data available)"
    lines = []
    for row in history:
        fy  = row.get("fiscal_year_end", "?")
        adv_prog = row.get("advertising_prog") or 0
        adv_mgmt = row.get("advertising_mgmt") or 0
        adv_fund = row.get("advertising_fundraising") or 0
        adv_total = adv_prog + adv_mgmt + adv_fund
        it_prog   = row.get("it_prog") or 0
        pf_fees   = row.get("prof_fundraising_fees") or 0
        inv_fees  = row.get("invest_mgmt_fees") or 0
        tot_exp   = (
            (row.get("total_prog_services") or 0)
            + (row.get("total_mgmt_general") or 0)
            + (row.get("total_fundraising_exp") or 0)
        )
        adv_pct = adv_total / tot_exp if tot_exp else None

        lines.append(f"  FY{fy}:")
        lines.append(
            f"    Advertising & Promo (Ln 12)  ${adv_total:>12,.0f}"
            f"  (prog: ${adv_prog:,.0f} | mgmt: ${adv_mgmt:,.0f}"
            f" | fundraising: ${adv_fund:,.0f})"
        )
        if adv_pct is not None:
            lines.append(f"    Advertising % total exp      {adv_pct:.2%}")
        if it_prog:
            lines.append(f"    IT expenses — prog svc (Ln14) ${it_prog:>11,.0f}")
        if pf_fees:
            lines.append(f"    Prof fundraising fees (Ln11e) ${pf_fees:>11,.0f}")
        if inv_fees:
            lines.append(f"    Investment mgmt fees (Ln11f)  ${inv_fees:>11,.0f}")
        lines.append(
            f"    Program services %           {(row.get('prog_services_pct') or 0):.1%}"
            f"   Overhead: {(row.get('overhead_ratio') or 0):.1%}"
        )
    return "\n".join(lines)


def _score_band(score: float, confirmed: int = 0) -> str:
    if score >= 6.5: return "CRITICAL"
    if score >= 5.0: return "HIGH"
    if score >= 3.5: return "Elevated"
    if score >= 2.0: return "Baseline"
    if score >= 0.1:
        return "Marginal" if confirmed > 0 else "Baseline — no confirmed signals"
    return "Clean"


def _build_request_params(context: dict) -> tuple[str, int, str]:
    """Return (model, max_tokens, user_turn) for the given context."""
    model = _MODEL_ROUTING.get(context["query_type"], MODEL_SONNET)
    if model == MODEL_OPUS:
        max_tokens = _MAX_TOKENS_OPUS
    elif _is_complex_context(context):
        max_tokens = _MAX_TOKENS_COMPLEX
    else:
        max_tokens = _MAX_TOKENS_STANDARD
    user_turn = _format_context_for_model(context)
    return model, max_tokens, user_turn


def synthesize(context: dict) -> dict:
    """
    Non-streaming API call.  Used for --json output where the full response
    is needed before any rendering begins.

    Returns dict with keys:
        text, model, model_label, input_tokens, output_tokens, synthesizer_ms
    """
    model, max_tokens, user_turn = _build_request_params(context)
    client = anthropic.Anthropic(api_key=get_api_key())

    t0 = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_turn}],
    )
    return {
        "text":           response.content[0].text,
        "model":          model,
        "model_label":    _MODEL_LABELS.get(model, model),
        "input_tokens":   response.usage.input_tokens,
        "output_tokens":  response.usage.output_tokens,
        "synthesizer_ms": int((time.monotonic() - t0) * 1000),
    }


def synthesize_stream(context: dict):
    """
    Streaming API call.  Yields str text chunks as the model generates them,
    then yields one final dict (same shape as synthesize() return value) when
    the stream is exhausted.

    Usage:
        syn = None
        for item in synthesize_stream(ctx):
            if isinstance(item, str):
                sys.stdout.write(item)
                sys.stdout.flush()
            else:
                syn = item   # final result dict
    """
    model, max_tokens, user_turn = _build_request_params(context)
    client = anthropic.Anthropic(api_key=get_api_key())

    t0 = time.monotonic()
    collected: list[str] = []

    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_turn}],
    ) as stream:
        for chunk in stream.text_stream:
            collected.append(chunk)
            yield chunk
        final = stream.get_final_message()

    yield {
        "text":           "".join(collected),
        "model":          model,
        "model_label":    _MODEL_LABELS.get(model, model),
        "input_tokens":   final.usage.input_tokens,
        "output_tokens":  final.usage.output_tokens,
        "synthesizer_ms": int((time.monotonic() - t0) * 1000),
    }
