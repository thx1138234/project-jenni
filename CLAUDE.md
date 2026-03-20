# CLAUDE.md — Higher Education Financial & Institutional Database

This file is the persistent context for all Claude Code sessions on this project.
Read it fully before taking any action. It contains architectural decisions,
naming conventions, data quirks, and deferred decisions that are easy to
get wrong without this background.

---

## What This Project Is

A multi-source, AI-ready research database unifying public federal data on
U.S. higher education institutions. The goal is a single queryable repository
that combines rock-solid mandatory financial filings with institutional
operational data, suitable for longitudinal research and AI-driven analysis.

**Four data sources, four databases, one institution master:**

| Database | Source | What It Adds | Status |
|---|---|---|---|
| `990_data.db` | IRS Form 990 via ProPublica | Audited financials for private nonprofits | In progress |
| `ipeds_data.db` | NCES IPEDS | Enrollment, admissions, outcomes — all institutions | Building now |
| `eada_data.db` | Dept. of Education EADA | Athletics financials | Complete |
| `scorecard_data.db` | College Scorecard API | Post-grad earnings & debt by program | Planned |

The join key across all four is **UNITID** (IPEDS 6-digit institution ID).
Form 990 additionally uses **EIN**. Both live in `institution_master`.

---

## Product Vision — Read This Before Writing Anything

This database does not exist in isolation. It is the foundation of a
**Jarvis for higher education** — an always-on, deeply informed intelligence
that combines structured historical data with current search capability to
surface insights that drive action.

### The Core Problem This Solves

Higher education has a massive information asymmetry problem. The data exists —
it's all public — but it's fragmented, technical, and inaccessible to the
people who most need to act on it. A CFO at a small private college cannot
easily benchmark their tuition dependency against 50 peers across 10 years.
A board member cannot quickly assess whether their institution's financial
trajectory resembles schools that have closed. An enrollment director cannot
connect their yield rate decline to sector-wide demographic shifts without
a data team and weeks of work.

This product makes that analysis available in natural language, in minutes,
to the people making the decisions.

### What Jarvis Is

Not a dashboard. Not a search engine. An **intelligence layer** that:

- **Knows the domain cold** — 25 years of audited financials, enrollment
  trends, program completions, outcomes for every Title IV institution
- **Knows what it doesn't know** — routes to search for current data,
  recent news, program descriptions, leadership changes
- **Synthesizes across sources** — combines 990 financials with IPEDS
  outcomes with EADA athletics with current web context without being asked
- **Drives action, not just awareness** — the output is a deliverable,
  not a data dump

### The Two-Layer Architecture

```
STRUCTURED DATABASE (this repo)          SEARCH LAYER
Long-term memory                         Current awareness
─────────────────────────────────────    ──────────────────────────
25 years audited financials              Current tuition & fees
Enrollment trends by institution         Recent news & events
Program completions by CIP code          Leadership changes
Graduation & retention rates             New program launches
Peer group benchmarking                  Accreditation actions
Financial stress signals                 Current rankings
Cross-source joins (990+IPEDS+EADA)      Program descriptions
```

Neither layer alone is sufficient. Together they cover every question
a higher ed professional needs answered.

---

## Use Cases — Who Uses This and What They Do With It

### The Primary User Is Not the C-Suite

Presidents, CFOs, CMOs, and CTOs set direction. They do not query databases.
Their **direct reports** do — the analysts, institutional research staff,
financial planning teams, enrollment management teams, and strategic planning
offices who have to synthesize data and bring recommendations upstairs.

**Jarvis is the analyst that never sleeps, never misses a filing, and always
knows where the data is.**

The output is not an insight — it is a **deliverable**. A memo. A talking
point. A recommendation with the data already attached. Something a direct
report can hand upward with confidence.

### User Map — The Decision Chain

| C-Suite / Leadership | Their Direct Report (Primary User) | The Deliverable Jarvis Produces |
|---|---|---|
| **President / Chancellor** | Chief of Staff, Strategic Planning | Board memo, peer benchmarking summary, scenario analysis |
| **CFO** | VP Finance, Budget Director, Financial Analyst | Stress indicator report, revenue trend analysis, debt capacity assessment |
| **CMO / VP Enrollment** | Enrollment Analyst, Marketing Director | Yield trend analysis, competitor positioning, demographic exposure report |
| **CTO / CIO** | IR Director, Data Analyst | Institutional data package, IPEDS submission prep, accreditor response |
| **Provost / CAO** | Academic Planning, IR | Program viability analysis, completion trends, peer program benchmarking |

### External Users

Beyond the institution itself:

| User | Their Question | The Action |
|---|---|---|
| **Accreditor** | Which institutions need closer scrutiny? | Site visit prioritization |
| **Investor / Lender** | What is the credit risk here? | Bond pricing, loan decisions |
| **Policy maker** | Which institutions are failing their students? | Regulatory action, funding |
| **Journalist** | What is the real story here? | Investigation, accountability reporting |
| **Prospective student / family** | Will this school be here when I graduate? | Enrollment decision |
| **Competitor institution** | Where are we differentiated? | Strategic positioning |

### The Wedge Use Case — Financial Early Warning

The single most compelling entry point for this product:

*"Here are 47 private institutions showing three or more financial stress
indicators based on their last three 990 filings. Here is what the data
says about each one. Here is how they compare to schools that closed in
the last decade."*

This use case:
- Uses data that already exists in this database (990 + IPEDS Finance)
- Serves users with budget and authority (boards, CFOs, accreditors, lenders)
- Has no good existing solution — current tools are manual, expensive, or inaccessible
- Has a clear action: "we need to act on this" or "we are fine"
- Is demonstrable immediately once the 990 pipeline is complete

### What "Insight That Drives Action" Looks Like

Not this:
> "Babson's tuition revenue was $217M in FY2023."

This:
> "Babson's tuition dependency has increased 8 points since 2015 — above
> average for schools in its Carnegie peer group. Their endowment growth
> has lagged comparable institutions since 2019. Three schools with similar
> profiles have already cut programs. They are not in distress but they
> have less margin than their peer group suggests. The next two 990 filings
> will be telling."

The difference is **context, comparison, trend, and implication**.
The database provides the numbers. Jarvis provides the analysis.
The direct report provides the recommendation. The C-suite makes the decision.

---

## Schema Implications of the Product Vision

The use cases above should inform every schema and data decision:

1. **Pre-calculate derived metrics** — tuition dependency ratio, endowment
   per student, instruction expense per FTE, revenue trend slope.
   Jarvis retrieves answers; it does not calculate them at query time.

2. **Build peer group logic into the database** — Carnegie classification,
   control type, size band, regional peers. A query that says "compare to
   peers" needs a defined peer set, not an ad hoc filter.

3. **Design for the deliverable, not the data point** — views and queries
   should produce outputs that map to real deliverables: board memos,
   benchmarking tables, stress indicator reports.

4. **Institution master richness matters** — clean entity resolution is
   critical. "Babson," "Babson College," and "F.W. Olin Graduate School
   of Business at Babson College" must all resolve to UNITID 164739.
   Common name aliases and system membership belong in institution_master.

5. **The signal layer is not optional** — a `financial_health_signals`
   table that stores pre-computed stress indicators per institution per year
   is what enables the wedge use case. Plan for it in Phase 2.

---

## Repo Structure

```
higher-ed-db/
├── CLAUDE.md                        ← You are here
├── README.md                        ← Public-facing documentation
├── CHANGELOG.md                     ← What has been built and when
├── .gitignore                       ← .db files and data/raw/ excluded
│
├── schema/
│   ├── ipeds_schema.sql             ← All 12 IPEDS components + views + ref tables
│   ├── 990_schema.sql               ← Form 990 Parts VIII/IX/X/XI
│   ├── eada_schema.sql              ← Athletics disclosure data
│   ├── scorecard_schema.sql         ← College Scorecard (planned)
│   └── institution_master.sql       ← Shared institution lookup table
│
├── ingestion/
│   ├── ipeds/
│   │   ├── downloader.py            ← Fetches bulk CSVs from NCES
│   │   └── loader.py                ← Normalizes and loads CSVs into DB
│   ├── 990/
│   │   ├── parser.py                ← IRS XML → structured records
│   │   ├── loader.py                ← Records → SQLite
│   │   └── field_map.py             ← Form 990 line item → column mapping
│   ├── eada/
│   │   └── loader.py
│   └── scorecard/
│       ├── api_client.py            ← College Scorecard API wrapper
│       └── loader.py
│
├── data/
│   ├── raw/                         ← Source files (.gitignored)
│   │   ├── ipeds_csv/               ← NCES bulk downloads land here
│   │   │   └── manifest.json        ← Download state tracker
│   │   ├── 990_xml/                 ← IRS XML filings
│   │   └── eada_csv/
│   ├── sample/                      ← Small committed reference files
│   │   └── 990_Babson_2023_*.csv    ← Babson FY2023 990 CSVs
│   └── databases/                   ← .db files (.gitignored)
│       ├── 990_data.db
│       ├── ipeds_data.db
│       ├── eada_data.db
│       └── scorecard_data.db
│
├── docs/
│   ├── data_sources.md
│   ├── fiscal_year_conventions.md
│   ├── gasb_fasb_crosswalk.md
│   └── roadmap.md
│
├── queries/                         ← Reusable analytical SQL
└── tests/
```

---

## Critical Conventions — Read Before Writing Any Code

### 1. Year Convention
**All year fields use fiscal year END as the canonical label.**

- Form 990 calls it "Tax Year" using the fiscal year *start* (confusing).
  FY ending June 2023 = IRS "Tax Year 2022" = our `fiscal_year_end = 2023`.
- IPEDS uses `survey_year` = fall start year of academic year.
  AY 2022-23 = `survey_year = 2022`.
- These are deliberately different field names to make the distinction explicit.
- The join between them: `fiscal_year_end = survey_year + 1`
  (e.g., 990 FY2023 joins to IPEDS survey_year 2022).
- See `docs/fiscal_year_conventions.md` for full rules and example SQL.

### 2. NULL vs 0 — Never Conflate These
- `NULL` = data not reported or not applicable for this institution/year.
- `0` = reported as zero (institution exists, value is genuinely zero).
- NCES uses `-1` and `-2` in raw CSV for suppressed/not-applicable values.
  The loader converts these to `NULL`, not `0`.
- This distinction matters for averages and ratios. Always use `NULLIF(col, 0)`
  in denominators, never just divide.

### 3. UNITID Is the Universal Join Key
Every institution in every table has a UNITID. It is the primary key of
`institution_master` and a foreign key in every other table.
Do not use institution name strings as join keys — names change and have
inconsistent spacing/punctuation across sources.

### 4. EIN Is 990-Only
Only private nonprofit institutions have EINs in this database.
Public institutions have UNITID and OPEID but no EIN.
Never assume EIN is present for a given institution.

---

## IPEDS-Specific Architecture

### Scope
- **Universe:** All ~5,800+ Title IV institutions (full national coverage)
- **Years:** AY 2000-01 through latest available (survey_year 2000–present)
- **Components:** All 12 survey components

### Component Load Order
**Always load in this sequence — institution_master must be populated first:**
1. `INST` → `institution_master` (from **HD** data, not IC — see quirks below)
2. `IC`   → `ipeds_ic`
3. `ADM`  → `ipeds_adm`
4. `EF`   → `ipeds_ef`
5. `C`    → `ipeds_completions`
6. `GR`   → `ipeds_gr`
7. `SFA`  → `ipeds_sfa`
8. `F`    → `ipeds_finance` (see GASB/FASB section below)
9. `HR`   → `ipeds_hr`
10. `E12`, `GR200`, `OM`, `AL` — lower priority, load after above

### IPEDS File Naming Quirks (Do Not Rediscover These)
- **institution_master is loaded from HD, not IC.** `HD{year}.zip` is the Header/Directory
  file containing institution name, control, state, Carnegie class, EIN, and OPEID.
  The IC file contains tuition and program offerings — it does NOT have `instnm`, `control`,
  `iclevel`, etc. Do not confuse them.
- **IC is split into two files per year:**
  - `IC{year}.zip` → program offerings, calendar system, admissions policy
  - `IC{year}_AY.zip` → academic year charges (tuition, fees, room & board)
  The loader merges both by unitid. The downloader fetches both when `--component IC` is specified.
  Room & board in IC_AY is `chg4ay0` (on-campus room charge, published). Board may be separate
  in `chg5ay0`. The `roomboard_oncampus` field mapping needs verification — currently may be
  room-only, not room+board combined.
- **Carnegie classification field changes with each NCES update:**
  `c21basic` (current, 2021 Carnegie) → `c18basic` (2018) → `carnegie` (legacy).
  The loader checks all three in priority order.
- **EF component** has 4 parts: A (race/ethnicity), B (age), C (residence, even years only), D (totals)
- **SFA files** use two-year naming: `SFA2223.zip` for AY 2022-23
- **Finance files** are split by accounting framework: `F2223_F1A.zip` (FASB) and `F2223_F2.zip` (GASB)
- **ADM** is standalone from 2014 only; admissions data for 2000-2013 is embedded in IC
- **E12** files used prefix `EF12` before 2012, then changed to `EFIA`
- The `downloader.py` handles all of these — do not bypass it with manual downloads

### NCES Variable Name Changes
NCES renames variables across survey years. The loader's `FIELD_MAP` dictionaries
handle this with priority-ordered candidate lists. If a new year produces
unexpected NULLs in a field that should have data, check the raw CSV headers
against the field map — a variable rename is the most likely cause.

---

## The GASB / FASB Decision — Read This Carefully

### What It Is
Public universities use GASB accounting. Private nonprofits use FASB.
NCES ships them as separate CSV files with different line items.
The `ipeds_finance` table has a `reporting_framework` column ('GASB' or 'FASB')
that identifies which framework each row uses.

### Current State: Both FASB and GASB Are Loaded
**As of the initial 2022–2023 build, `_load_gasb()` runs unconditionally in
`FinanceLoader`. Both F1A (FASB) and F2 (GASB) rows are present in `ipeds_finance`.**

The original deferral policy (FASB only) was a design decision that was never
enforced in code. During the smoke test build (March 2026) GASB data loaded
alongside FASB without issue. The data is there, labeled correctly with
`reporting_framework = 'GASB'`, and the schema was designed for it.

**Decision: Accept GASB data as loaded. The original deferral rationale still
applies to cross-sector financial *comparisons* — it does not justify deleting
data that is now in the database.**

What this means going forward:
- Both FASB and GASB rows are present. This is the correct long-term state.
- The cross-sector comparison warnings in `docs/gasb_fasb_crosswalk.md` still
  apply — do not silently mix frameworks in financial queries.
- Any query on `ipeds_finance` should either:
  - Filter to `WHERE reporting_framework = 'FASB'` for private-only analysis, or
  - Filter to `WHERE reporting_framework = 'GASB'` for public-only analysis, or
  - Include `reporting_framework` in results so consumers know what they're seeing.
- **Never write a financial query that silently mixes both frameworks.**

---

## Form 990 Architecture

### What We Ingest
Four parts of the Form 990:
- **Part VIII** — Statement of Revenue
- **Part IX** — Statement of Functional Expenses
- **Part X**  — Balance Sheet
- **Part XI** — Reconciliation of Net Assets

We do NOT ingest:
- Form 990-EZ (smaller orgs, less detail, not relevant for universities)
- Form 990-T (unrelated business income — already captured in aggregate on 990)
- Form 990-PF (private foundations — separate use case, not yet in scope)

### Source
ProPublica Nonprofit Explorer API and IRS bulk XML downloads.
XML e-filing is reliable from 2012 onward. Pre-2012 = PDFs only = different problem.
Effective 990 coverage: **FY2012–present** for most institutions.

### Current State
- Babson College FY2023 loaded from CSV (sample data in `data/sample/`)
- XML parser written but pipeline not yet run at scale
- Target: 10+ institutions, FY2020–2024, before repo goes public

### Private Nonprofit Universe for 990
~1,200 private nonprofit degree-granting 4-year institutions file full Form 990.
Public institutions (~1,600) do not file 990 — use IPEDS Finance (FASB only
for now, GASB deferred per above decision).

---

## Database Files

SQLite for local development. Migration to PostgreSQL (Supabase) is planned
for Phase 2 when the database goes live for shared access.

**All .db files are .gitignored.** Do not commit them.
Large raw data files (`data/raw/`) are also .gitignored.
The `data/sample/` directory contains small committed reference files only.

When building databases from scratch:
```bash
# Initialize schema (sqlite3 CLI may not be installed — use python3)
python3 -c "
import sqlite3; from pathlib import Path
conn = sqlite3.connect('data/databases/ipeds_data.db')
conn.executescript(Path('schema/ipeds_schema.sql').read_text())
conn.commit()
"

# Download IPEDS source files (respects manifest, skips already-downloaded)
python3 ingestion/ipeds/downloader.py

# Load all components
python3 ingestion/ipeds/loader.py --db data/databases/ipeds_data.db

# Verify
python3 tests/test_schema_integrity.py
```

---

## Dependencies

```
requests       # IPEDS downloader
sqlite3        # Standard library — no install needed
```

No ORM. Raw SQL and sqlite3 throughout. This is intentional — the database
is the product, not an application backend. Keeping the stack minimal means
anyone can pick this up without a framework dependency chain.

---

## Analytical Views — Use These, Don't Rewrite Them

These views are defined in `ipeds_schema.sql` and handle the common
join/filter patterns. Query them instead of writing raw joins each time:

| View | What It Does |
|---|---|
| `v_enrollment_trends` | Enrollment by year with race/ethnicity percentages |
| `v_financial_summary` | Key financial ratios, GASB/FASB labeled, per-student metrics |
| `v_masters_programs` | Master's completions by CIP code — pre-filtered to awlevel=7 |
| `v_admissions_selectivity` | Admit rate, yield, test scores with enrollment context |

---

## Active Decisions & Open Questions

Document decisions here as they're made so they don't get relitigated.

**Decided:**
- Full national universe (~5,800 institutions), not curated subset
- AY 2000-present (not 1980 — pre-2000 IPEDS is structurally inconsistent)
- All 12 IPEDS components loaded
- GASB finance files deferred until specific analytical need arises
- SQLite for local dev, PostgreSQL (Supabase) for Phase 2 hosting
- No ORM — raw SQL and sqlite3 throughout
- Public university GASB audited statements explicitly out of scope
  (PDF-only, no central repository, not machine-readable at scale)

**Open:**
- Hugging Face dataset publication — when and how
- NACUBO endowment study integration (licensed data, needs access)
- College Scorecard schema and API ingestion (Phase 2)
- Whether to add program-level table for HF/UX/XD MS programs
  (CIP codes identified; actual program titles require scraping)

---

## What "Done" Looks Like for Each Phase

### Phase 1 Complete (current target)
- [ ] IPEDS fully loaded: all 12 components, 2000–present, all 5,800 institutions
- [ ] 990 pipeline: 10+ institutions, FY2020–2024
- [ ] `institution_master` complete with EIN + UNITID for all 990 institutions
- [ ] All schema SQL files committed
- [ ] `tests/test_schema_integrity.py` passes clean
- [ ] `CHANGELOG.md` current

### Phase 2 Complete
- [ ] GitHub repo public
- [ ] PostgreSQL on Supabase, migrated from SQLite
- [ ] College Scorecard loaded
- [ ] Read-only API endpoint live

---

## Contact / Maintenance Notes

This database is maintained as a research repository.
Data is sourced entirely from public federal sources (IRS, NCES, Dept. of Education).
All source data is public domain. Code is MIT licensed.

When adding new data years annually:
1. Run `downloader.py` — it will skip already-downloaded files
2. Run `loader.py --year {new_year}` for the new year only
3. Update `CHANGELOG.md`
4. Run integrity tests
5. Commit schema and code changes only (not .db files)
