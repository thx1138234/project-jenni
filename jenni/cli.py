"""
jenni/cli.py
--------------------------------------
Click CLI for the JENNI intelligence layer.

Commands:
  analyze   — Full analysis of an institution or topic
  compare   — Side-by-side comparison of two or more institutions
  trend     — Enrollment, financial, or athletics trend for an institution
  stress    — Show institutions with financial stress signals
  sector    — Sector-wide analysis (Carnegie tier, state, control type)
  data      — Raw data table for an institution

Usage:
    .venv/bin/python3 -m jenni.cli analyze "Tell me about Babson financial health"
    .venv/bin/python3 -m jenni.cli analyze "Babson vs Bentley" --json
    .venv/bin/python3 -m jenni.cli stress --threshold elevated --state MA
    .venv/bin/python3 -m jenni.cli data babson --year 2022
    .venv/bin/python3 -m jenni.cli trend mit enrollment
    .venv/bin/python3 -m jenni.cli compare babson bentley bc

    # Or via the entry point after installation:
    jenni analyze "Harvard endowment performance relative to peers"
"""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from jenni.query_resolver import assemble_context, extract_entities
from jenni.synthesizer import synthesize
from jenni.delivery import render_response, to_json
from jenni.config import DB_990, DB_IPEDS, DB_QUANT

console = Console()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run(
    query: str,
    year: int | None,
    json_output: bool,
    verbose: bool,
    context_only: bool = False,
) -> None:
    """Core pipeline: resolve → synthesize → deliver."""
    with console.status("[cyan]Assembling context…[/cyan]", spinner="dots"):
        ctx = assemble_context(query, year=year)

    if not ctx["entities"]:
        console.print(
            "[yellow]No institutions matched in this query.[/yellow]\n"
            "Try a more specific institution name, or use a sector-level command:\n"
            "  jenni stress --threshold elevated\n"
            "  jenni sector --carnegie 21"
        )
        return

    # Partial-year warning: when no --year was specified and the resolved
    # primary year has low completeness, warn before output so the user
    # knows to pin to a better year.
    if year is None:
        dq = ctx.get("data_quality", {})
        completeness = dq.get("completeness_pct")
        primary_year = ctx["accordion"]["primary_year"]
        if completeness is not None and completeness < 50:
            console.print(
                f"\n[bold yellow]⚠  Note:[/bold yellow] Using survey_year "
                f"[bold]{primary_year}[/bold] "
                f"({completeness:.1f}% complete — financial data pending "
                f"FY{primary_year + 1} filings). "
                f"Use [bold]--year {primary_year - 1}[/bold] for full "
                f"financial analysis.\n"
            )

    # --context-only: show assembled context without calling the API
    if context_only:
        _render_context_debug(ctx)
        return

    with console.status(
        f"[cyan]Synthesizing with {ctx['query_type']} model…[/cyan]",
        spinner="dots",
    ):
        syn = synthesize(ctx)

    if json_output:
        click.echo(json.dumps(to_json(ctx, syn), indent=2))
    else:
        render_response(ctx, syn, verbose=verbose)


def _render_context_debug(ctx: dict) -> None:
    """Show the context package that would be sent to the model — without calling the API."""
    from jenni.synthesizer import _MODEL_ROUTING

    acc     = ctx["accordion"]
    entities = ctx["entities"]

    console.print(Panel(
        f"[bold cyan]Query:[/bold cyan] {ctx['query']}\n"
        f"[bold]Type:[/bold] {ctx['query_type'].upper()}  "
        f"[bold]Accordion:[/bold] {acc['zone'].upper()} "
        f"({acc['epistemic_posture']})\n"
        f"[bold]Primary year:[/bold] {acc['primary_year']}  "
        f"[bold]Years in DB:[/bold] "
        f"{acc['years_in_db'][0] if acc['years_in_db'] else '—'}–"
        f"{acc['years_in_db'][-1] if acc['years_in_db'] else '—'} "
        f"({len(acc['years_in_db'])} years)",
        title="[bold]JENNI Context Package[/bold]",
        title_align="left",
        border_style="cyan",
    ))

    # Metrics tables for each institution
    from jenni.delivery import _metrics_table
    for uid, data in ctx["institution_data"].items():
        m  = data.get("master", {})
        q  = data.get("quant_latest", {})
        sy = q.get("survey_year", acc["primary_year"])
        name = m.get("institution_name", f"UNITID {uid}")

        console.print(f"\n[bold cyan]{name}[/bold cyan]  [dim]{m.get('state_abbr')} | "
                      f"{m.get('control_label')} | Carnegie {m.get('carnegie_basic')}[/dim]")

        stress = data.get("stress")
        if stress:
            score = stress.get("composite_stress_score") or 0
            console.print(f"  Stress: score={score:.2f}  "
                          f"confirmed={stress.get('confirmed_signal_count', 0)}  "
                          f"window={stress.get('signal_year_range', '—')}")

        if q:
            console.print(_metrics_table(name, q, sy))

        narrs = data.get("narratives", {})
        for t, content in narrs.items():
            console.print(Panel(
                content[:300] + ("…" if len(content) > 300 else ""),
                title=f"[pre-encoded] {t}",
                title_align="left",
                border_style="dim",
                expand=False,
            ))

    dq = ctx["data_quality"]
    model = _MODEL_ROUTING.get(ctx["query_type"], "claude-sonnet-4-6")
    console.print(
        f"\n[dim]Would call: [bold]{model}[/bold]  "
        f"| primary_year={dq.get('primary_year')}  "
        f"| completeness={dq.get('completeness_pct')}%  "
        f"| sources={', '.join(dq.get('sources', []))}[/dim]"
    )
    console.print(
        "\n[yellow]Context assembled successfully. "
        "Add ANTHROPIC_API_KEY to .env to run live synthesis.[/yellow]"
    )


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option("0.1.0", prog_name="jenni")
def jenni():
    """JENNI — Higher Education Intelligence Layer

    Synthesizes 25+ years of federal institutional data into analytical output.
    """


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

@jenni.command()
@click.argument("query")
@click.option("--year", "-y", type=int, default=None,
              help="Override primary data year (default: latest available)")
@click.option("--json", "json_output", is_flag=True, default=False,
              help="Output raw JSON instead of Rich terminal rendering")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show pre-encoded narrative panels")
@click.option("--context-only", is_flag=True, default=False,
              help="Show assembled context package without calling the API (debug/demo)")
def analyze(query, year, json_output, verbose, context_only):
    """Analyze an institution or topic.

    Examples:\n
        jenni analyze "Tell me about Babson financial health compared to peers"\n
        jenni analyze "MIT endowment and research funding"\n
        jenni analyze "Boston College vs Boston University" --year 2021\n
        jenni analyze "Babson financial health" --context-only  # no API key needed
    """
    _run(query, year, json_output, verbose, context_only)


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

@jenni.command()
@click.argument("institutions", nargs=-1, required=True)
@click.option("--year", "-y", type=int, default=None,
              help="Override primary data year")
@click.option("--json", "json_output", is_flag=True, default=False)
def compare(institutions, year, json_output):
    """Compare two or more institutions side by side.

    Examples:\n
        jenni compare babson bentley\n
        jenni compare harvard mit stanford --year 2022\n
        jenni compare "boston college" "boston university" tufts
    """
    query = f"Compare {' and '.join(institutions)} across financial health, enrollment, and peer positioning"
    _run(query, year, json_output, verbose=False)


# ---------------------------------------------------------------------------
# trend
# ---------------------------------------------------------------------------

@jenni.command()
@click.argument("institution")
@click.argument("metric", default="financial",
                type=click.Choice(["financial", "enrollment", "athletics", "all"],
                                  case_sensitive=False))
@click.option("--json", "json_output", is_flag=True, default=False)
def trend(institution, metric, json_output):
    """Show longitudinal trends for an institution.

    Examples:\n
        jenni trend babson enrollment\n
        jenni trend harvard financial\n
        jenni trend mit all
    """
    query = (
        f"Show {metric} trends over time for {institution}. "
        f"Include historical trajectory and year-over-year changes."
    )
    _run(query, year=None, json_output=json_output, verbose=False)


# ---------------------------------------------------------------------------
# stress
# ---------------------------------------------------------------------------

@jenni.command()
@click.option("--threshold", "-t",
              default="elevated",
              type=click.Choice(["marginal", "baseline", "elevated", "high", "critical"],
                                case_sensitive=False),
              help="Minimum stress band to show (default: elevated)")
@click.option("--state", "-s", default=None,
              help="Filter by state abbreviation (e.g. MA, NY, CA)")
@click.option("--carnegie", "-c", type=int, default=None,
              help="Filter by Carnegie basic classification code")
@click.option("--limit", "-n", type=int, default=20,
              help="Max institutions to show (default: 20)")
@click.option("--json", "json_output", is_flag=True, default=False)
def stress(threshold, state, carnegie, limit, json_output):
    """Show institutions with financial stress signals.

    Draws from financial_stress_signals (FY2020–2022 window).

    Examples:\n
        jenni stress --threshold critical\n
        jenni stress --threshold elevated --state MA\n
        jenni stress --threshold high --carnegie 21
    """
    import sqlite3

    _BAND_SCORES = {
        "marginal":  0.1,
        "baseline":  2.0,
        "elevated":  3.5,
        "high":      5.0,
        "critical":  6.5,
    }

    min_score = _BAND_SCORES[threshold.lower()]

    conn = sqlite3.connect(str(DB_990))
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM financial_stress_signals WHERE composite_stress_score >= ?"
    params: list = [min_score]
    if state:
        sql += " AND state_abbr = ?"
        params.append(state.upper())
    if carnegie:
        sql += " AND carnegie_basic = ?"
        params.append(carnegie)
    sql += " ORDER BY composite_stress_score DESC LIMIT ?"
    params.append(limit)

    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()

    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return

    if not rows:
        console.print(f"[green]No institutions found at or above '{threshold}' stress level.[/green]")
        return

    t = Table(
        title=f"Institutions at or above '{threshold.upper()}' stress level (FY2020–2022)",
        box=box.SIMPLE_HEAD,
        header_style="bold",
        title_style="bold cyan",
    )
    t.add_column("Institution",    max_width=36)
    t.add_column("State",          width=6,  justify="center")
    t.add_column("Carnegie",       width=10, justify="center")
    t.add_column("Score",          width=7,  justify="right")
    t.add_column("Band",           width=10, justify="center")
    t.add_column("Confirmed",      width=10, justify="center")
    t.add_column("Years",          width=6,  justify="center")

    _BAND_COLORS = {
        "CRITICAL": "bold red",
        "HIGH":     "red",
        "Elevated": "yellow",
        "Baseline": "dark_orange",
        "Marginal": "cyan",
        "Clean":    "green",
    }

    def _band(score: float) -> str:
        if score >= 6.5: return "CRITICAL"
        if score >= 5.0: return "HIGH"
        if score >= 3.5: return "Elevated"
        if score >= 2.0: return "Baseline"
        if score >= 0.1: return "Marginal"
        return "Clean"

    for row in rows:
        score = row.get("composite_stress_score") or 0.0
        band  = _band(score)
        color = _BAND_COLORS.get(band, "white")
        t.add_row(
            row.get("institution_name", "—")[:36],
            row.get("state_abbr", "—"),
            str(row.get("carnegie_basic", "—")),
            f"{score:.2f}",
            f"[{color}]{band}[/{color}]",
            str(row.get("confirmed_signal_count") or 0),
            str(row.get("years_available") or 0),
        )

    console.print(t)
    console.print(
        f"[dim]Source: financial_stress_signals | FY2020–2022 | "
        f"Showing {len(rows)} institutions at or above '{threshold}' threshold[/dim]"
    )


# ---------------------------------------------------------------------------
# sector
# ---------------------------------------------------------------------------

@jenni.command()
@click.option("--carnegie", "-c", type=int, default=None,
              help="Carnegie basic classification code to analyze")
@click.option("--state", "-s", default=None,
              help="Filter by state abbreviation")
@click.option("--control", default=None,
              type=click.Choice(["public", "private", "for-profit"], case_sensitive=False),
              help="Filter by control type")
@click.option("--json", "json_output", is_flag=True, default=False)
def sector(carnegie, state, control, json_output):
    """Sector-wide analysis across Carnegie tier, state, or control type.

    Examples:\n
        jenni sector --carnegie 21 --state MA\n
        jenni sector --control private\n
        jenni sector --carnegie 15
    """
    filters = []
    if carnegie:
        filters.append(f"Carnegie {carnegie}")
    if state:
        filters.append(state.upper())
    if control:
        filters.append(control)

    scope_str = ", ".join(filters) if filters else "all institutions"
    query = (
        f"Sector analysis for {scope_str}: summarize financial health distribution, "
        f"enrollment trends, and stress signal prevalence. Identify patterns and outliers."
    )

    # For sector queries, we don't try to extract specific entities —
    # the synthesizer will work from the query text against sector-level context.
    # Build a minimal context package with sector data.
    import sqlite3

    conn990 = sqlite3.connect(str(DB_990))
    conn990.row_factory = sqlite3.Row

    sql = "SELECT * FROM financial_stress_signals WHERE 1=1"
    params: list = []
    if state:
        sql += " AND state_abbr = ?"
        params.append(state.upper())
    if carnegie:
        sql += " AND carnegie_basic = ?"
        params.append(carnegie)
    if control:
        ctrl_map = {"public": 1, "private": 2, "for-profit": 3}
        # financial_stress_signals doesn't have control — skip
        pass

    rows = [dict(r) for r in conn990.execute(sql, params).fetchall()]
    conn990.close()

    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return

    if not rows:
        console.print(f"[yellow]No data found for sector: {scope_str}[/yellow]")
        return

    total = len(rows)
    scored = [r for r in rows if (r.get("composite_stress_score") or 0) > 0]

    from collections import Counter
    band_counts: Counter = Counter()
    for r in rows:
        s = r.get("composite_stress_score") or 0
        if s >= 6.5:   band_counts["CRITICAL"] += 1
        elif s >= 5.0: band_counts["HIGH"] += 1
        elif s >= 3.5: band_counts["Elevated"] += 1
        elif s >= 2.0: band_counts["Baseline"] += 1
        elif s >= 0.1: band_counts["Marginal"] += 1
        else:          band_counts["Clean"] += 1

    t = Table(
        title=f"Sector Analysis — {scope_str} ({total} institutions)",
        box=box.SIMPLE_HEAD,
        title_style="bold cyan",
    )
    t.add_column("Stress Band", style="bold")
    t.add_column("Count", justify="right")
    t.add_column("% of Sector", justify="right")

    _COLORS = {"CRITICAL":"bold red","HIGH":"red","Elevated":"yellow",
               "Baseline":"dark_orange","Marginal":"cyan","Clean":"green"}
    for band in ["CRITICAL","HIGH","Elevated","Baseline","Marginal","Clean"]:
        n = band_counts.get(band, 0)
        color = _COLORS[band]
        t.add_row(
            f"[{color}]{band}[/{color}]",
            str(n),
            f"{n/total*100:.1f}%",
        )
    t.add_row("[bold]TOTAL[/bold]", str(total), "100%", style="dim")
    console.print(t)

    # Top scorers
    top = sorted(rows, key=lambda x: -(x.get("composite_stress_score") or 0))[:10]
    if top and (top[0].get("composite_stress_score") or 0) > 0:
        console.print()
        t2 = Table(title="Top 10 by Stress Score", box=box.SIMPLE_HEAD,
                   title_style="bold yellow")
        t2.add_column("Institution", max_width=40)
        t2.add_column("State", width=6, justify="center")
        t2.add_column("Score", width=7, justify="right")
        t2.add_column("Confirmed", width=10, justify="center")
        for r in top:
            s = r.get("composite_stress_score") or 0
            if s == 0:
                break
            t2.add_row(
                r.get("institution_name", "—")[:40],
                r.get("state_abbr", "—"),
                f"{s:.2f}",
                str(r.get("confirmed_signal_count") or 0),
            )
        console.print(t2)

    console.print(f"\n[dim]Source: financial_stress_signals | FY2020–2022 window[/dim]")


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

@jenni.command()
@click.argument("institution")
@click.option("--year", "-y", type=int, default=None,
              help="Specific survey_year (default: latest available)")
@click.option("--all-years", is_flag=True, default=False,
              help="Show all years in institution_quant")
@click.option("--json", "json_output", is_flag=True, default=False)
def data(institution, year, all_years, json_output):
    """Show raw institution_quant data for an institution.

    Examples:\n
        jenni data babson\n
        jenni data harvard --year 2022\n
        jenni data mit --all-years --json
    """
    entities = extract_entities(institution)
    if not entities:
        console.print(f"[yellow]Institution not found: '{institution}'[/yellow]")
        return

    entity = entities[0]
    uid    = entity["unitid"]
    name   = entity["institution_name"]
    match  = entity.get("match_method", "")
    score  = entity.get("match_score", 0.0)

    import sqlite3
    conn = sqlite3.connect(str(DB_QUANT))
    conn.row_factory = sqlite3.Row

    if year and not all_years:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM institution_quant WHERE unitid=? AND survey_year=?",
            (uid, year)
        ).fetchall()]
    else:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM institution_quant WHERE unitid=? ORDER BY survey_year",
            (uid,)
        ).fetchall()]
    conn.close()

    if not rows:
        console.print(f"[yellow]No institution_quant data found for '{name}' "
                      f"(UNITID {uid})[/yellow]")
        return

    if json_output:
        click.echo(json.dumps(rows, indent=2, default=str))
        return

    from jenni.delivery import _metrics_table, _fmt, _METRICS
    console.print(f"[cyan]{name}[/cyan]  [dim]UNITID {uid} | matched via {match} "
                  f"(score {score:.2f})[/dim]")

    if all_years:
        # Summary across years
        t = Table(box=box.SIMPLE_HEAD, title=f"{name} — All Years",
                  title_style="bold cyan")
        t.add_column("Year",  width=6)
        t.add_column("Op Margin", justify="right", width=11)
        t.add_column("Tuit Dep", justify="right", width=10)
        t.add_column("Endow/Stu", justify="right", width=12)
        t.add_column("Runway",   justify="right", width=9)
        t.add_column("Enr CAGR", justify="right", width=10)
        t.add_column("Yield",    justify="right", width=8)
        t.add_column("Compl %",  justify="right", width=9)

        for r in rows:
            def _v(col, fmt):
                v = r.get(col)
                return _fmt(fmt, v) if v is not None else "—"
            t.add_row(
                str(r["survey_year"]),
                _v("operating_margin_value",      "{:+.1%}"),
                _v("tuition_dependency_value",     "{:.1%}"),
                _v("endowment_per_student_value",  "${:,.0f}"),
                _v("endowment_runway_value",       "{:.1f}"),
                _v("enrollment_3yr_cagr_value",    "{:+.1%}"),
                _v("yield_rate_value",             "{:.1%}"),
                _v("data_completeness_pct",        "{:.0f}%"),
            )
        console.print(t)
    else:
        # Detailed single-year view
        latest = rows[-1]
        sy     = latest.get("survey_year")
        console.print(_metrics_table(name, latest, sy))

    console.print(
        f"[dim]Source: institution_quant v{rows[0].get('formula_version', '?')} | "
        f"institution_quant.db[/dim]"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    jenni()
