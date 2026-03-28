"""
jenni/delivery.py
--------------------------------------
Renders JENNI output to the terminal using Rich, or as JSON.

Two modes:
  render_response(context, synthesis, verbose=False)  — Rich terminal output
  to_json(context, synthesis)                          — JSON dict for programmatic use

Terminal layout:
  1. Institution header panel
  2. Metrics table (numbers first)
  3. Narrative synthesis (model output)
  4. Data quality footer
"""

from __future__ import annotations

import json

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

# Stress band colors
_BAND_COLORS = {
    "CRITICAL": "bold red",
    "HIGH":     "red",
    "Elevated": "yellow",
    "Baseline": "dark_orange",
    "Marginal": "cyan",
    "Clean":    "green",
}

# Metric display spec: (label, column_suffix, format_str, higher_is_better)
_METRICS: list[tuple[str, str, str, bool]] = [
    ("Operating Margin",      "operating_margin",       "{:+.1%}", True),
    ("Tuition Dependency",    "tuition_dependency",     "{:.1%}",  False),
    ("Debt-to-Assets",        "debt_to_assets",         "{:.1%}",  False),
    ("Debt-to-Revenue",       "debt_to_revenue",        "{:.1f}×", False),
    ("Endowment / Student",   "endowment_per_student",  "${:,.0f}", True),
    ("Endowment Runway",      "endowment_runway",       "{:.1f} yrs", True),
    ("Program Services %",    "program_services_pct",   "{:.1%}",  True),
    ("Overhead Ratio",        "overhead_ratio",         "{:.1%}",  False),
    ("Fundraising Eff.",      "fundraising_efficiency", "{:.1f}×", True),
    ("Revenue / FTE",         "revenue_per_fte",        "${:,.0f}", True),
    ("Expense / FTE",         "expense_per_fte",        "${:,.0f}", False),
    ("Enrollment CAGR 3yr",   "enrollment_3yr_cagr",    "{:+.1%}", True),
    ("Yield Rate",            "yield_rate",             "{:.1%}",  True),
    ("Admit Rate",            "admit_rate",             "{:.1%}",  False),
    ("App. CAGR 3yr",         "app_3yr_cagr",           "{:+.1%}", True),
    ("Grad Rate 150%",        "grad_rate_150",          "{:.1%}",  True),
    ("Grad Enrollment %",     "grad_enrollment_pct",    "{:.1%}",  True),
    ("Pell % Students",       "pell_pct",               "{:.1%}",  True),
    ("Net Price",             "net_price",              "${:,.0f}", False),
    ("Earnings/Debt",         "earnings_to_debt_ratio", "{:.2f}×", True),
    ("Athletics % Exp.",      "athletics_to_expense_pct","{:.1%}", False),
    ("Athletics Net",         "athletics_net",          "${:,.0f}", True),
]

_DIR_SYMBOLS = {
    "improving":    "[green]↑[/green]",
    "stable":       "[dim]→[/dim]",
    "deteriorating":"[red]↓[/red]",
}


def _fmt(fmt_str: str, value) -> str:
    try:
        return fmt_str.format(value)
    except (ValueError, TypeError):
        return "—"


def _score_band(score: float) -> str:
    if score >= 6.5: return "CRITICAL"
    if score >= 5.0: return "HIGH"
    if score >= 3.5: return "Elevated"
    if score >= 2.0: return "Baseline"
    if score >= 0.1: return "Marginal"
    return "Clean"


def _metrics_table(institution_name: str, q: dict, survey_year: int) -> Table:
    """Build a Rich Table of key metrics for one institution."""
    t = Table(
        title=f"{institution_name} — survey_year {survey_year}",
        box=box.SIMPLE_HEAD,
        show_lines=False,
        header_style="bold",
        title_style="bold cyan",
    )
    t.add_column("Metric",           style="dim",   width=24)
    t.add_column("Value",            justify="right", width=14)
    t.add_column("Peer Median",      justify="right", style="dim", width=13)
    t.add_column("Pctile",           justify="right", width=7)
    t.add_column("Trend",            justify="center", width=8)

    for label, suffix, fmt, higher_better in _METRICS:
        val = q.get(f"{suffix}_value")
        if val is None:
            continue

        val_str    = _fmt(fmt, val)
        peer_med   = q.get(f"{suffix}_peer_median")
        peer_pct   = q.get(f"{suffix}_peer_pct")
        trend_dir  = q.get(f"{suffix}_trend_dir")

        peer_str   = _fmt(fmt, peer_med) if peer_med is not None else "—"
        pctile_str = f"{peer_pct*100:.0f}" if peer_pct is not None else "—"
        trend_str  = _DIR_SYMBOLS.get(trend_dir or "", "")

        # Color value by peer percentile position (peer_pct stored as 0–1 fraction)
        if peer_pct is not None:
            good_pct = peer_pct * 100 if higher_better else (100 - peer_pct * 100)
            if good_pct >= 75:
                val_markup = f"[green]{val_str}[/green]"
            elif good_pct >= 25:
                val_markup = val_str
            else:
                val_markup = f"[red]{val_str}[/red]"
        else:
            val_markup = val_str

        t.add_row(label, val_markup, peer_str, pctile_str, trend_str)

    return t


def _stress_badge(stress: dict | None) -> str:
    if not stress:
        return ""
    score = stress.get("composite_stress_score") or 0.0
    band  = stress.get("narrative_flag") or _score_band(score)
    color = _BAND_COLORS.get(band, "white")
    conf  = stress.get("confirmed_signal_count") or 0
    yrs   = stress.get("signal_year_range") or "FY2020–2022"
    return (
        f"[{color}]STRESS: {band}[/{color}]  "
        f"Score: {score:.2f}  Confirmed signals: {conf}  "
        f"Window: {yrs}"
    )


def render_response(
    context: dict,
    synthesis: dict,
    verbose: bool = False,
) -> None:
    """Render the full JENNI response to the terminal."""

    # ── Institution header(s) ─────────────────────────────────────────────
    for uid, data in context["institution_data"].items():
        m     = data.get("master", {})
        q     = data.get("quant_latest", {})
        stress = data.get("stress")
        narrs  = data.get("narratives", {})

        name   = m.get("institution_name", f"UNITID {uid}")
        state  = m.get("state_abbr", "")
        ctrl   = m.get("control_label", "")

        header_lines = [f"[bold cyan]{name}[/bold cyan]  {state}  |  {ctrl}"]
        badge = _stress_badge(stress)
        if badge:
            header_lines.append(badge)

        console.print(Panel("\n".join(header_lines), expand=False))

        # ── Metrics table ─────────────────────────────────────────────────
        if q:
            sy = q.get("survey_year", context["accordion"]["primary_year"])
            table = _metrics_table(name, q, sy)
            console.print(table)
        elif data.get("quant_history"):
            console.print("[dim]  institution_quant data available — use --year to specify.[/dim]")
        else:
            console.print("[dim]  No quantitative data in institution_quant for this institution.[/dim]")

        # ── Verbose: pre-encoded narratives ───────────────────────────────
        if verbose:
            for narr_type, content in narrs.items():
                console.print(Panel(
                    content,
                    title=f"[pre-encoded] {narr_type}",
                    title_align="left",
                    border_style="dim",
                    expand=False,
                ))

    # ── Synthesized narrative ─────────────────────────────────────────────
    console.print()
    console.print(Panel(
        synthesis["text"],
        title="[bold]JENNI Analysis[/bold]",
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
    ))

    # ── Data quality footer ───────────────────────────────────────────────
    dq  = context.get("data_quality", {})
    acc = context.get("accordion", {})

    footer = Table(box=box.MINIMAL, show_header=False, padding=(0, 1))
    footer.add_column(style="dim", width=20)
    footer.add_column(style="dim")

    footer.add_row("Model",        synthesis.get("model_label", synthesis.get("model", "")))
    footer.add_row("Primary year", str(dq.get("primary_year", "—")))
    footer.add_row("Completeness", f"{dq.get('completeness_pct', '—')}%")
    footer.add_row("Sources",      ", ".join(dq.get("sources", [])))
    footer.add_row("Accordion",    f"{acc.get('zone', '—')} — {acc.get('posture_note', '')}"[:80])
    footer.add_row("Tokens",
        f"in: {synthesis.get('input_tokens', '—')}  "
        f"out: {synthesis.get('output_tokens', '—')}")

    console.print(footer)


def to_json(context: dict, synthesis: dict) -> dict:
    """Return a JSON-serializable dict of the full JENNI response."""

    def _quant_row(q: dict) -> dict:
        out = {}
        for label, suffix, fmt, _ in _METRICS:
            val = q.get(f"{suffix}_value")
            if val is not None:
                out[suffix] = {
                    "value":       val,
                    "peer_median": q.get(f"{suffix}_peer_median"),
                    "peer_pct":    q.get(f"{suffix}_peer_pct"),
                    "trend_dir":   q.get(f"{suffix}_trend_dir"),
                }
        return out

    institutions = {}
    for uid, data in context["institution_data"].items():
        m  = data.get("master", {})
        q  = data.get("quant_latest", {})
        institutions[uid] = {
            "institution_name": m.get("institution_name"),
            "state_abbr":       m.get("state_abbr"),
            "control_label":    m.get("control_label"),
            "carnegie_basic":   m.get("carnegie_basic"),
            "ein":              m.get("ein"),
            "metrics":          _quant_row(q) if q else {},
            "narratives":       data.get("narratives", {}),
            "stress":           data.get("stress"),
            "years_available":  [r["survey_year"] for r in data.get("quant_history", [])],
        }

    return {
        "query":        context["query"],
        "query_type":   context["query_type"],
        "accordion":    context["accordion"],
        "institutions": institutions,
        "synthesis":    synthesis["text"],
        "model":        synthesis.get("model"),
        "data_quality": context.get("data_quality"),
        "tokens": {
            "input":  synthesis.get("input_tokens"),
            "output": synthesis.get("output_tokens"),
        },
    }
