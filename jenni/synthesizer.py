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

import anthropic

from jenni.config import get_api_key, MODEL_HAIKU, MODEL_SONNET, MODEL_OPUS
from jenni.prompts.system import SYSTEM_PROMPT

_MODEL_ROUTING: dict[str, str] = {
    "data":       MODEL_HAIKU,
    "analysis":   MODEL_SONNET,
    "comparison": MODEL_SONNET,
    "trend":      MODEL_SONNET,
    "stress":     MODEL_SONNET,
    "sector":     MODEL_OPUS,
}

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
        pct_str  = f" | {pct:.0f}th pctile" if pct is not None else ""
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
            score = stress.get("composite_stress_score") or 0
            band  = stress.get("narrative_flag") or _score_band(score)
            parts.append(f"STRESS SCORE: {score:.2f} ({band}) | "
                         f"Confirmed signals: {stress.get('confirmed_signal_count', 0)} | "
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


def _score_band(score: float) -> str:
    if score >= 6.5: return "CRITICAL"
    if score >= 5.0: return "HIGH"
    if score >= 3.5: return "Elevated"
    if score >= 2.0: return "Baseline"
    if score >= 0.1: return "Marginal"
    return "Clean"


def synthesize(context: dict) -> dict:
    """
    Call Claude API with the assembled context package.

    Returns
    -------
    dict with keys:
        text      : str   — synthesized narrative from the model
        model     : str   — model ID used
        model_label: str  — human-readable model label
        input_tokens : int
        output_tokens: int
    """
    model = _MODEL_ROUTING.get(context["query_type"], MODEL_SONNET)

    api_key   = get_api_key()
    client    = anthropic.Anthropic(api_key=api_key)
    user_turn = _format_context_for_model(context)

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_turn}],
    )

    return {
        "text":         response.content[0].text,
        "model":        model,
        "model_label":  _MODEL_LABELS.get(model, model),
        "input_tokens": response.usage.input_tokens,
        "output_tokens":response.usage.output_tokens,
    }
