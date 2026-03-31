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
| `990_data.db` | IRS Form 990 — TEOS portal (2019+) / ProPublica API (2012–2018) | Audited financials for private nonprofits | **Complete** (16,071 rows, 1,790 target EINs, FY2012–2024, commit 1e1e26b) |
| `ipeds_data.db` | NCES IPEDS | Enrollment, admissions, outcomes — all institutions | **Complete** (6.6M rows, 2000–2024, commit c3a4680) |
| `eada_data.db` | Dept. of Education EADA | Athletics financials | Complete |
| `scorecard_data.db` | College Scorecard API | Post-grad earnings & debt by program | **Complete** (6,322 rows `scorecard_institution`, 217,530 rows `scorecard_programs`) |

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

## The Accordion of Time — Permanent Architectural Principle

The database is not a snapshot. It is a temporal instrument. Understanding its
boundaries — in both directions — is essential to using it honestly.

### The Termini

**Backward terminus — structured quantitative data: approximately 1960.**
Systematic federal data collection at scale begins roughly here. IPEDS components
reach back to 2000 in machine-readable form; 990 XML filings to 2012; EADA to 2003.
These are our operational limits. But institutional history extends further, and
*narrative context* — founding story, mission evolution, major strategic pivots,
accreditation history, closures and mergers — can and should reach back to
institutional founding. A college founded in 1863 carries that context even when
the structured data only goes back 25 years. The backward terminus is not where
knowledge ends; it is where the character of knowledge changes.

**Forward terminus — defensible projection: 3–5 years.**
Trend extrapolation grounded in multi-year data is legitimate analysis. Enrollment
CAGR, revenue trajectory, demographic exposure — these project forward with
defensible confidence over a planning horizon. Beyond 5 years, the honest posture
is scenario-building, not prediction. The forward terminus is not a wall; it is
where conditionals replace indicatives.

**Inner terminus — what financial data cannot see.**
This is the most important terminus. The database captures what institutions
*report*. It does not capture:
- Leadership quality: whether the president has the confidence of the board
- Mission authenticity: whether the institution actually does what it says
- Community vitality: faculty morale, student belonging, alumni loyalty
- Strategic execution: whether a turnaround plan is real or a press release
- Accreditor relationships: the tone of the last site visit, the unsent letter

These are the things that make institutions great — or that determine whether
a distressed institution survives or closes. A school can score clean on every
financial signal and be hollowing out. Another can carry a high stress score
and be executing a genuine recovery. Financial data is a necessary but not
sufficient lens. The inner terminus is the boundary of what numbers can know.

**The music lives between the termini.** JENNI's value is in the space that
structured data can actually illuminate: longitudinal financial trends, peer
benchmarking, enrollment dynamics, demographic exposure, the pre-distress signals
that emerge years before a closure announcement. That space is large and largely
unoccupied by existing tools. Stay in it.

### Intelligence Layer Epistemic Rules

These rules govern how JENNI speaks. They are not stylistic preferences — they
are epistemic commitments that protect the product's credibility.

**Near the center of the data window — speak with authority.**
When referencing well-covered years with multiple confirming sources:
> "Boston College's tuition dependency increased 6 points between 2016 and 2022,
> from 48% to 54% of total revenue."

**Approaching the backward terminus — speak with humility.**
As data thins toward the early years of coverage:
> "The data suggests enrollment growth beginning around 2008, though evidence thins
> before 2012 when XML filings begin."

Do not fabricate continuity. If a metric is NULL before a certain year, say so.
Silence about a data gap is a form of misrepresentation.

**Approaching the forward terminus — speak in conditionals.**
> "If current enrollment trends continue, Babson would cross 4,000 undergraduates
> by 2027 — though demographic headwinds in the Northeast create meaningful downside risk."

The conditional is not hedging. It is precision.

**Beyond either terminus — acknowledge the boundary explicitly.**
> "I don't have structured data on Babson's founding period. What I can tell you
> is that their financial model as of 2022..."

Never confabulate. The boundary is not a failure — it is the shape of honest knowledge.

### The 2023 Refresh as Accordion in Practice

The survey_year=2023 data illustrates how the accordion works in the forward direction:
- **Demand and athletics** extended cleanly to 2023 — these sources release on
  predictable schedules aligned with the academic year
- **Financial rows** are pending — FY2024 990 filings require the TEOS 2025 index
  release (~March 2026); only 95 early filers are present of ~1,200 expected
- **INSERT OR IGNORE** ensures the accordion expands non-destructively — partial
  rows coexist with complete rows; financial data fills in when filings arrive

This is the correct behavior. A 2023 row with demand data and NULL financial data
is honest. A row that refuses to exist until all fields are populated would be
epistemically convenient but practically useless.

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
   of Business at Babson College" must all resolve to UNITID 164580.
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
│   ├── 990_part_ix_schema.sql       ← Part IX functional column breakdowns (Phase A)
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

### 0. Empirical Evidence Beats Documentation
When instructions, docstrings, or external documentation conflict with empirical
file content or database state, always trust the empirical evidence. Flag the
conflict before proceeding. Example: NCES F1A files are documented as FASB
(private nonprofit) but empirically contain public institutions — the data wins.

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

### Part IX Functional Breakdown — form990_part_ix (Phase A)

`form990_part_ix` stores the Column B/C/D functional breakdowns from Part IX (Statement of
Functional Expenses). TEOS/IRSx rows only — ProPublica rows are NULL by design (ProPublica
API does not expose functional column splits).

**Phase A fields (5,171 TEOS rows loaded):**
- Line 25 totals: `total_prog_services` (col B), `total_mgmt_general` (col C), `total_fundraising_exp` (col D)
- Line 12 advertising: all three columns
- Line 14 IT expenses: all three columns
- Line 11e professional fundraising fees (`FeesForServicesProfFundraising.TotalAmt`)
- Line 11f investment management fees (`FeesForSrvcInvstMgmntFeesGrp.TotalAmt`)
- Calculated at load: `prog_services_pct`, `overhead_ratio`, `fundraising_efficiency`

**Validation benchmarks (FY2023):**
- Boston College: 86.0% program services, 14.0% overhead, 14.2% fundraising efficiency
- Harvard: 87.8% program services, 12.2% overhead
- MIT: 78.2% program services, 21.8% overhead (research overhead is expected to be higher)

**Phase B** (full line item detail, all Part IX lines) — deferred until after intelligence layer.

### Officer Compensation — form990_compensation (Schedule J)

`form990_compensation` stores per-person compensation from Schedule J Part II, augmented by
Part VII Section A role/hours fields. TEOS/IRSx source only — ProPublica API does not expose
per-person Schedule J breakdowns (it only has aggregate `compnsatncurrofcr`). Pre-2019 per-person
data would require downloading pre-2019 TEOS XML (IRS has index years 2013–2018); not yet loaded.

**Coverage:** FY2020–2024 (TEOS), 4,383 filings, 40,352 person-rows

**Key fields per officer:**
- Schedule J Part II: `comp_base`, `comp_bonus`, `comp_other`, `comp_deferred`, `comp_nontaxable`, `comp_total`, `related_org_comp`
- Part VII Section A (joined by name): `hours_per_week`, `former_officer`, `is_officer`, `is_key_employee`, `is_highest_comp`

**Validation benchmarks (FY2023):**
- Harvard — Lawrence S. Bacow (President): $1,757,109
- MIT — L. Rafael Reif (President, outgoing): $1,845,810
- BC — Fr. Leahy (S.J.) not on Schedule J; Jesuit priests receive stipends via religious order, not institutional salary. Highest-paid: Jeffrey Hafley (football coach) $3,835,259

**PRIMARY KEY:** `(object_id, officer_name)` — one row per person per filing.

**Jesuit institution presidents:** Jesuit priests serving as university presidents (e.g., Fr. William Leahy at BC) will NOT appear on Schedule J. Their compensation flows through their religious order (Society of Jesus), not through the institution. This is expected behavior — **not a data gap**. The institution's highest Schedule J earner is often a head coach or investment professional. Use `institution_master.jesuit_institution = 1` to identify these institutions before interpreting NULL or missing president comp.

### Endowment Detail — form990_schedule_d (Schedule D Part V)

`form990_schedule_d` stores annual endowment activity from Schedule D Part V.
TEOS/IRSx rows only. One row per filing (PRIMARY KEY `object_id`).

**Coverage:** 4,360 filings with endowment data (of 5,171 TEOS XML; 800 non-990 filers, 11 have Schedule D but no endowment fund)

**Fields:**
- Activity: `endowment_boy`, `contributions_endowment`, `investment_return_endowment`, `grants_from_endowment`, `other_endowment_changes`, `admin_expenses_endowment`, `endowment_eoy`
- Breakdown percentages (lines 3a–3c): `board_designated_pct`, `perm_restricted_pct`, `temp_restricted_pct`
- Calculated dollar breakdowns (pct × EOY): `endowment_board_designated`, `endowment_restricted_perm`, `endowment_restricted_temp`, `endowment_unrestricted`

**Validation benchmarks (FY2022):**
- Harvard: $49.4B EOY (25.6% board-designated, 21.6% perm restricted, 52.8% temp restricted)
- MIT: $24.7B EOY (28.9% board-designated, 16.3% perm restricted, 54.8% temp restricted)
- BC: $3.7B EOY; Babson: $662M EOY; Bentley: $333M EOY
- `endowment_runway` = endowment_eoy / total_functional_expenses (years of operating runway).
  FY2023: Harvard 7.89 yrs, MIT 4.82 yrs, BC 2.75 yrs, Babson 2.24 yrs. All 4,360 rows populated.
- Endowment spending rate analysis: use `grants_from_endowment > 0` filter. Negative values
  (reverse flows) and $0 values (routing artifacts like Penn) distort spending rate calculations.

### Financial Stress Signals — financial_stress_signals

Pre-computed multi-year financial stress scoring. One row per EIN (institution system),
not per UNITID (campus). Built by `ingestion/990/stress_signals_builder.py`.

**Purpose:** Surface institutions with sustained, multi-year financial distress patterns
distinguishable from single-year COVID noise. The primary output of the wedge use case.

**Schema summary (`financial_stress_signals`):**
- Identity: `ein`, `unitid`, `institution_name`, `state_abbr`, `hbcu`, `jesuit_institution`, `carnegie_basic`
- Coverage: `signal_year_range` (e.g. '2020-2022'), `years_available` (1–3)
- Per-signal year counts (0–3): `sig_deficit_yrs`, `sig_neg_assets_yrs`, `sig_asset_decline_yrs`,
  `sig_high_debt_yrs`, `sig_low_cash_yrs`, `sig_end_stress_yrs`, `sig_low_runway_yrs`, `sig_low_prog_yrs`
- Trend summary: `confirmed_signal_count`, `emerging_signal_count`, `single_year_count`
- Score: `composite_stress_score` = confirmed×1.0 + emerging×0.5 + single×0.25
- Quality: `data_completeness_pct` = years_available / 3 × 100

**Three production fixes applied:**
1. **EIN-level dedup**: Multi-campus systems collapsed to canonical EIN with MIN(unitid).
   DeVry (104 unitids), Altierus/Everest (40), Strayer (40), etc. each become one row.
2. **Cash signal endowment suppression**: `sig_low_cash` requires endowment_runway IS NULL
   OR endowment_runway < 1.0 — wealthy institutions managing cash via endowment draws
   are not distressed by low checking account balances.
3. **Multi-year trending**: Each signal evaluated independently for FY2020, FY2021, FY2022.
   - `confirmed`: fires in all available years (requires ≥2 years of data)
   - `emerging`: fires in 2 of 3 years (when 3 years available)
   - `single`: fires in exactly 1 year — potential COVID distortion, lower weight

**Score band definitions (updated for expanded enrollment scale, max ~8.0):**
| Score | Band | Confirmed signals | Interpretation |
|---|---|---|---|
| 6.5+ | CRITICAL | ≥1 | Confirmed multi-domain crisis: financial + severe enrollment decline co-occurring |
| 5.0–6.4 | HIGH | ≥1 | Multiple confirmed stress trends; acute risk without intervention |
| 3.5–4.9 | Elevated | ≥1 | Confirmed stress across multiple signals; monitoring required |
| 2.0–3.4 | Baseline | ≥1 | Confirmed stress in 1–2 signals; emerging pattern |
| 0.1–1.9 | Marginal | ≥1 | Single-year signals that recur; genuine but limited pattern |
| 0.1–1.9 | Baseline — no confirmed signals | 0 | Isolated single-year noise; likely COVID artifact. Financially clean institutions with minor scoring artifacts land here. |
| 0 | Clean | 0 | No signals fired across any year |

The "Baseline — no confirmed signals" band matters for interpretation: research-intensive institutions (Harvard, MIT, BC) with score ~0.50 and zero confirmed signals are in this band. The score reflects isolated single-year signal artifacts, not a genuine watch-list indicator. Do not conflate with "Marginal" which requires at least one confirmed multi-year signal.

The Critical threshold of 6.5 is meaningful: it requires confirmed multi-year financial
distress (financial_stress_score ≥ 4.5) plus severe confirmed enrollment decline (enr
score ≥ 2.0). A score of 6.5+ is not statistical noise — it is an institution in acute,
multi-domain crisis.

**Current results (FY2020–2022, 1,363 institutions scored):**
- CRITICAL (4.0+): 30 institutions (2.2%)
- HIGH (3.0–3.9): 90 institutions (6.6%)
- 97 institutions have confirmed_signal_count ≥ 3 (multi-confirmed sustained stress)
- 1,098 institutions (80.6%) have full 3-year coverage

**Top scorers (composite_stress_score, as of March 2026 build):**
- Mount Sinai Phillips School of Nursing (NY): 5.50 — deficit + high debt + asset decline, all 3 years
- The Chicago School-College of Nursing (TX): 5.25 — negative net assets all 3 years, 450% debt ratio
- San Francisco Art Institute (CA): 5.25 — **closed 2022; confirms signal validity**
- University of Valley Forge (PA): 5.00
- St. Francis College (NY): 4.50 — deficit all 3 years, 96% debt ratio
- Centenary University (NJ): 4.50 — negative net assets all 3 years, 132% debt

**San Francisco Art Institute as validation case:** SFAI scored 5.25 with only 2 years of data.
It closed in May 2022 after 150 years. The confirmed signals (deficit + low runway + low cash, both
available years) predate the closure announcement. This is the clearest available confirmation that
the composite_stress_score identifies genuine at-risk institutions, not statistical noise.

**HBCU confirmed multi-signal stress (confirmed_signal_count ≥ 2, 11 institutions):**
Saint Augustine's Univ (NC, 3.50), Florida Memorial Univ (FL, 3.25), Knoxville College (TN, 3.25),
Shaw University (NC, 2.75), Wilberforce (OH, 2.50), Miles College (AL, 2.50) are the top six.
All show confirmed multi-year stress predating COVID.

**narrative_flag column — ⚠️ REBUILD WARNING:**
`narrative_flag` is manually seeded for 26 institutions and is **NOT** automatically
recalculated on rebuild. Any full rebuild of `financial_stress_signals` (via
`stress_signals_builder.py`) will set `narrative_flag` to NULL for all rows. Narratives
must be re-applied manually after any rebuild.

The 26 seeded institutions and their exact assigned narratives are documented in commit
history at **eb4515d**. To restore after a rebuild, retrieve them from that commit and
re-run as UPDATE statements against the live DB.

Pattern vocabulary (use these exact phrases for consistency):
- "Structural financial distress" — deficit + debt + negative assets, multi-year confirmed
- "Enrollment collapse" — severe enrollment decline (>20%) driving combined stress
- "Technically insolvent" — negative net assets confirmed across multiple years
- "Business model stress, not demand problem" — financial distress with enrollment growth
- "Terminal financial distress" — use only for confirmed closures or imminent closure risk

These narratives are the seed of JENNI's stress signal language. Do not alter the pattern
vocabulary without a deliberate decision — consistency of language matters for the intelligence layer.

**Status — research artifact, not authoritative:**
`financial_stress_signals` is a **research artifact** representing one interpretive framework
applied at a single point in time (March 2026, FY2020–2022 window). It is useful for
exploration, benchmarking signal logic, and seeding JENNI's language. It is **not** the
authoritative quantitative signal layer for the product.

The authoritative signal layer is **`institution_quant`** (v1.0, March 2026 — see section below).
`institution_quant` supersedes `financial_stress_signals` as the primary stress scoring surface.
Do not build downstream product features that hard-depend on `financial_stress_signals` column
names or score bands — treat it as exploratory scaffolding.

**Known limitations:**
- **TEOS data only (FY2020–2022)**: ProPublica years (FY2012–2019) are not included in trend
  calculation. Institutions with pre-2020 stress history are not penalized for pre-window distress.
  The 3-year window was chosen to match TEOS coverage while spanning COVID.
- **990-only financial signals**: All 8 financial signals derive from 990 filings.
  Enrollment cross-validation (ipeds_ef) is included as the 9th signal but IPEDS Finance,
  graduation rates, and net price trends are not yet incorporated.
- **Supplemental signal coverage is partial**: `sig_end_stress` and `sig_low_runway` require
  Schedule D data (4,360 of ~5,171 TEOS filings). `sig_low_prog` requires Part IX data.
  Institutions missing supplemental data have those signals conservatively set to 0 —
  scores may be understated.
- **Single-year-only institutions (43 rows)**: Cannot generate confirmed or emerging signals;
  scores capped at 2.0. Treat with lower confidence.

### institution_quant — Authoritative Quant Layer

`institution_quant` is the authoritative, fully rebuildable quantitative layer.
One row per (unitid, survey_year). Pure math only — no thresholds, no composite scores,
no judgments. Built by `ingestion/institution_quant_builder.py`.

**Coverage by metric domain (by design — each uses best available source):**
| Domain | Metric group | Coverage | Source |
|---|---|---|---|
| Financial | 12 metrics (margins, debt, endowment, etc.) | FY2019–2022 only | 990 TEOS window |
| Demand | 8 metrics (enrollment, yield, admit rate, etc.) | survey_year 2016–2022 | IPEDS (full range) |
| Value | 3 metrics (grad rate, earnings, net price) | survey_year 2022 only | College Scorecard |
| Athletics | 3 metrics (net, per student, % of expense) | survey_year 2019–2022 | EADA |

This asymmetry is by design — financial metrics are limited to the TEOS window (FY2019+),
demand metrics use the full IPEDS longitudinal range, and value metrics reflect the single
Scorecard year loaded. As additional years are loaded, coverage expands without schema changes.

**Current build (v1.0, March 2026): 25,376 rows, survey_years 2019–2022**
- Financial: 5,070 institution-years (private nonprofits with 990 filings)
- Demand: 24,882 institution-years (all IPEDS institutions)
- Value: 5,784 institutions (Scorecard 2022 only, mapped to survey_year=2022)
- Athletics: 7,985 institution-years; 3,117 with `athletics_to_expense_pct`
- Peers: Carnegie peer group stats (min 5 peers); 3,911 with peer data in 2022
- Trends: 1yr, 3yr, direction for all metrics where ≥2 years available

**Rebuild path:**
```bash
rm data/databases/institution_quant.db
.venv/bin/python3 ingestion/institution_quant_builder.py \
    --db990   data/databases/990_data.db \
    --ipeds   data/databases/ipeds_data.db \
    --eada    data/databases/eada_data.db \
    --scorecard data/databases/scorecard_data.db \
    --out     data/databases/institution_quant.db \
    --stage   all
```
Expected: 25,376 rows, Babson survey_year=2022 data_completeness_pct=96.2.

**Known gaps (carry forward):**
- `retention_rate`: populated from EF Part D `ret_pcf` (first-time full-time, 0–100 → stored as fraction). Coverage 65.6% (117,970 of 160,861 ipeds_ef rows). Institutions not in EF Part D (typically non-degree-granting or specialized) are NULL.
- `grad_rate_150`: uses Scorecard `completion_rate_4yr` (single year 2022 only); ipeds_gr.gba_cohort always NULL
- `net_price`, `earnings_to_debt_ratio`, `net_price_to_earnings`: Scorecard single year only — confirmed: scorecard_institution has only data_year=2023 (6,322 rows). Historical Scorecard data requires separate bulk download from data.ed.gov (institution-level files available back to ~2010). Add to roadmap as Scorecard historical backfill.
- `athletics_to_expense_pct`: private nonprofits only (requires 990 functional expenses as denominator)
- `formula_version = '1.0'`: bump this when metric formulas change; enables git isolation of formula changes

### Related Organizations — form990_related_orgs + form990_related_transactions (Schedule R)

`form990_related_orgs` stores all entities listed on Schedule R — disregarded entities,
related tax-exempt orgs, taxable partnerships, and taxable corporations/trusts.
`form990_related_transactions` stores dollar transactions with related orgs (Part V).
TEOS/IRSx source only. One row per entity per filing; transactions can be many-per-filing.

**Coverage:** TEOS FY2020–FY2024; extended to ~FY2015 by Zone 2 fill.
**Scale varies dramatically**: Harvard reports 400+ related orgs per year; small institutions
typically 1–10. The `relationship_type` column distinguishes the four Schedule R groups.

**Key fields:**
- `org_name`, `org_ein`: identity of related entity (org_ein NULL for foreign entities)
- `relationship_type`: 'disregarded' | 'tax_exempt' | 'partnership' | 'corp_trust'
- `direct_controlling_entity`: who controls the related org
- `controlled_org_ind`: 1 if the filing organization controls this entity
- `total_income`, `eoy_assets`, `share_of_total_income`, `share_of_eoy_assets`: financial summary
- `transaction_type` (in transactions table): letter codes A–S per IRS Schedule R Part V

### Governance — form990_governance (Part VI)

`form990_governance` stores board composition and governance policy flags from Part VI.
One row per filing (PRIMARY KEY `object_id`).

**Coverage:** TEOS FY2020–FY2024; extended to ~FY2015 by Zone 2 fill.

**Key fields:**
- `voting_members_governing_body`, `voting_members_independent`: board size and independence
- `total_employees`: W-2 headcount
- `conflict_of_interest_policy`, `whistleblower_policy`, `document_retention_policy`: 0/1 flags
- `financials_audited`, `audit_committee`: audit governance
- `government_grants_amt`: federal/state grant revenue (Part VIII context)
- `family_or_business_relationship`: 1 if officers/directors have family or business relationships

**Validation (FY2022):**
- Harvard: 13 board members, 10 independent; COI/whistleblower/doc retention all 1; 34,241 employees
- BC: 52 board members, 50 independent; all three policies 1; 11,553 employees
- MIT: 13 board members, 9 independent; all policies 1; 25,671 employees
- Babson: 33 board members, 32 independent; all policies 1; 2,032 employees

### Source — Two-Mode Pipeline (confirmed March 2026)

**Mode 1 — IRS TEOS Portal (2019–present):**
The IRS Tax Exempt Organization Search (TEOS) portal at `apps.irs.gov` is the
current authoritative source for 990 XML filings. No authentication required.

- Index CSV: `https://apps.irs.gov/pub/epostcard/990/xml/{YEAR}/index_{YEAR}.csv`
- XML ZIPs:  `https://apps.irs.gov/pub/epostcard/990/xml/{YEAR}/{YEAR}_TEOS_XML_{PART}.zip`
- Coverage: tax years 2019–present. Each ZIP contains batches of XML files.
  The index CSV maps EIN → object ID → ZIP filename for targeted extraction.

**Mode 2 — ProPublica Nonprofit Explorer API (2012–2018):**
For pre-2019 filings, the ProPublica API returns parsed JSON per EIN per year.
Rate limit: ~1 req/sec. Covers our five validation institutions individually.
Does not require bulk ZIP download; returns structured data directly.

**⚠️ IRS Form 990 AWS S3 bucket (`s3://irs-form-990`) is DISCONTINUED.**
The IRS announced on December 16, 2021 that it would discontinue updates to the
`irs-form-990` AWS Open Data Registry bucket, effective December 31, 2021.
The bucket exists in `us-east-1` but access policy has been revoked — all
requests return `AccessDenied` regardless of IAM policy or requester-pays header.
Do not attempt to use this bucket. Use TEOS portal (2019+) or ProPublica (2012–2018).

XML e-filing is reliable from 2012 onward. Pre-2012 = PDFs only = out of scope.
Effective 990 coverage: **FY2012–present** for most institutions.

### Current State
- Babson College UNITID = **164580** (EIN 042103544) — primary spot-check institution
- IRSx installed in .venv; TEOS downloader (`ingestion/990/downloader.py`) and parser (`ingestion/990/parser.py`) complete
- Target: five validation institutions, FY2019–2023 via TEOS + FY2012–2018 via ProPublica (Mode 2 not yet built)

### Ground Truth — Babson College 990 Spot Check Values
Confirmed from IRSx-parsed XML, cross-verified against ProPublica (must match exactly):

| Fiscal Year End | TAX_PERIOD | TEOS Index Year | Total Revenue |
|---|---|---|---|
| FY2022 | 202206 | 2023 | **$397,619,450** |
| FY2023 | 202306 | 2024 | **$344,014,371** |

**Validation standard:** IRSx parse and ProPublica API must agree exactly. Agreement between
both sources is the canonical confirmation — no CSV reference files are used or required.

Note: An earlier session referenced $358,779,440 as a Babson ground truth — this value
does not correspond to any Babson 990 filing and should be disregarded.

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

## Validation Institutions

These five institutions are the primary validation set for the 990 pipeline
and the financial stress signal layer. All are private nonprofits in MA with
confirmed EINs in `institution_master`. Use them for spot checks, smoke tests,
and regression checks whenever the 990 schema or loader changes.

| Institution | UNITID | EIN |
|---|---|---|
| Babson College | 164580 | 042103544 |
| Bentley University | 164739 | 041081650 |
| Boston College | 164924 | 042103545 |
| Harvard University | 166027 | 042103580 |
| Massachusetts Institute of Technology | 166683 | 042103594 |

All five have been verified against `institution_master` (name, state, control,
EIN, OPEID all correct as of March 2026).

### Finance Gut Check — Run After Any Finance Loader Change or Full Reload

**FASB check (private nonprofits) — all five validation institutions:**

```sql
SELECT im.institution_name, f.survey_year, f.reporting_framework,
       f.rev_total, f.exp_total, f.netassets_total,
       f.assets_total, f.liab_total
FROM institution_master im
JOIN ipeds_finance f ON im.unitid = f.unitid
WHERE im.unitid IN (164580, 164739, 164924, 166027, 166683)
  AND f.survey_year = (SELECT MAX(survey_year) FROM ipeds_finance
                       WHERE unitid = im.unitid)
ORDER BY im.institution_name;
```

For each row, confirm:
1. `reporting_framework = 'FASB'` — all five are private nonprofits; GASB here means a loader label bug
2. `rev_total` is in the hundreds of millions (≥ $50M) — values in the thousands indicate wrong field mapping (e.g., mapping to a line item instead of a total)
3. `exp_total` is in the hundreds of millions (≥ $50M) — same signal as rev_total
4. `netassets_total` is positive and plausible (negative is a red flag; zero suggests NULL stored as 0)
5. `assets_total > liab_total` — basic balance sheet sanity; reversal suggests wrong field mapping

**GASB check (public institutions) — UCCS and Prairie View:**

```sql
SELECT im.institution_name, f.survey_year, f.reporting_framework,
       f.rev_total, f.exp_total, f.netassets_total
FROM institution_master im
JOIN ipeds_finance f ON im.unitid = f.unitid
WHERE im.unitid IN (126580, 227526)   -- UCCS, Prairie View A&M
  AND f.survey_year = (SELECT MAX(survey_year) FROM ipeds_finance
                       WHERE unitid = im.unitid)
ORDER BY im.institution_name;
```

For each row, confirm:
6. `reporting_framework = 'GASB'` — both are public; FASB here means a loader label bug
   `rev_total` is in the hundreds of millions — UCCS ~$260M, Prairie View ~$343M as of 2022

Running both checks together ensures FASB and GASB field mappings are validated every time.

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
- **EF enrollment backfill (2000–2007) deferred**: `enrtot` is NULL for all
  2000–2007 rows due to old NCES column schema (`efrace`-based totals, uppercase
  column names pre-2008). The wedge use case (financial early warning, trend
  analysis) requires 2008–present, giving 15+ years of longitudinal data —
  sufficient for the core product. Pre-2008 enrollment is a backfill candidate;
  defer until there is a specific analytical need.

**Open:**
- Hugging Face dataset publication — when and how
- NACUBO endowment study integration (licensed data, needs access)
- College Scorecard additional years / refresh cadence (loaded: 6,322 institution rows, 217,530 program rows)
- Whether to add program-level table for HF/UX/XD MS programs
  (CIP codes identified; actual program titles require scraping)

---

## What "Done" Looks Like for Each Phase

### Phase 1 Complete ✓
- [x] IPEDS fully loaded: all 9 core components, 2000–2024, 13,609 institutions — commit c3a4680
- [x] 990 pipeline: 16,071 rows, 1,790 target EINs, FY2012–2024, TEOS+ProPublica — commit 1e1e26b
- [x] `institution_master` complete with EIN + UNITID for all 990 institutions
- [x] All schema SQL files committed (990_schema.sql, 990_part_ix_schema.sql, ipeds_schema.sql)
- [ ] `tests/test_schema_integrity.py` passes clean
- [x] `CHANGELOG.md` current
- [x] Full foundation gut check complete — 990 and IPEDS Finance validated across FASB and GASB (March 2026)
- [x] `financial_stress_signals` table built — 1,363 institutions scored, EIN-level, FY2020-2022, 3-year trending (commit b402f3c)

**IPEDS known open items (carry forward):**
- `enrtot` NULL for **2000–2007** EF rows (expanded from 2000–2001):
  - 2000–2001: EF Part A uses `line`/`section` layout — no `efalevel` column at all.
  - 2002–2007: `efalevel` present but `eftotlt` (enrollment total) not yet introduced
    by NCES. Enrollment totals were stored in `efrace`-based columns. Additionally,
    2004–2007 use uppercase column names (`EFALEVEL`, `EFTOTLT`) which the loader
    does not currently handle. All eight years require loader updates.
  - `eftotlt` was introduced in 2008. All years 2008+ load correctly.
  - Total affected rows: ~47,000 (years 2000–2007).
- `ipeds_finance` has incomplete institution coverage: NCES Finance survey
  participation is not universal. Well-known private nonprofits (Babson, Harvard,
  Boston College, etc.) are absent from NCES FASB submissions for many years.
  This is source data behavior — not a loader bug. The validation institution
  spot check uses 2016 (most recent year all five institutions are present).
- `ipeds_hr` starts at 2012: NCES does not publish `S{year}_SIS.zip` before 2012.
  No HR coverage for 2000–2011.
- `ipeds_e12` starts at 2012: EFIA format (EFTEUG/EFTEGD/FTEDPP for FTE) begins with
  EFIA2012.zip. Pre-2012 E12 files use EF12{year} naming and different column schemas.
  Coverage: 80,628 rows, survey_year 2012–2023, **fte12 is 100% populated** (no NULLs).
  `fte12` = ugfte12 + grfte12 + dpp_fte12; this is the per-student ratio denominator.
  Note: headcount fields (ug12, gr12, total12) do NOT exist in EFIA format — only
  credit-hour-based FTE and credit hour totals (ug_credit_hrs, gr_credit_hrs).
  Validation (survey_year=2022): Harvard 27,869 FTE, BC 14,398, MIT 14,055, Babson 3,840.
- `ipeds_ic` tuition NULL for 2024: `IC2024_AY.zip` not yet released by NCES as of
  2026-03-22 (manifest: `not_found`). All tuition/fee/room-board fields NULL for
  survey_year=2024. Retry `--component IC --year 2024 --force` when AY 2024-25
  data is published.
- `ipeds_sfa.netprice` NULL for wealthy private institutions: IPEDS suppresses the
  `netprice` field (and all income-band net price fields) when fewer than 30 students
  fall into the applicable aid category. Highly selective private schools — Babson,
  Bentley, Boston College, Harvard, MIT — are systematically NULL in `netprice` and
  `netprice_0_30k` through `netprice_over110k` for this reason. **Do not assume missing
  data means the institution does not report net price.** Use `scorecard_institution.avg_net_price_priv`
  (or income-band fields `np_priv_0_30k` through `np_priv_110k_plus`) as the preferred
  net price source for wealthy private institutions. Scorecard reports these without the
  30-student suppression threshold.
- `ipeds_sfa.avg_pell` was incorrectly mapped to `grntwf2`/`pellofr` (a count/flag field,
  values 0–36). **Corrected 2026-03-25** to map to `upgrnta` (average Pell grant for
  full-time first-time undergraduates). All rows reloaded. Plausible values now present:
  BC ranges $4,463–$5,587 across SY2015–2022. If querying earlier loader output, distrust
  any `avg_pell` values in the 0–36 range.
- `ipeds_sfa.pct_any_grant` and `pct_pell` both map to `upgrntp` — they return identical
  values for every institution. `pct_any_grant` is the broader "any grant" metric and
  should be mapped to a different field. Deferred; check IPEDS SFA data dictionary for
  the correct field name before using `pct_any_grant` in analysis.

**EADA sports-level data (eada_sports):**
- 349,581 rows loaded, 18 years (survey_year 2007–2024), 2,288 unique institutions
- Fields: sport_code, sport_name, participants_men/women, total_revenue, total_expenses, rev/exp by gender
- NO coaching salary dollars at sport level — per-sport salary is not collected by DOE.
  Institutional totals (hdcoach_salary_men, hdcoach_salary_women) are in eada_instlevel.
- EADA sport codes are institution-reported, NOT NCES standard: football=7, basketball=2
  (not the codes listed in older NCES documentation). Use `sport_name` column for filtering.
- 2019-2020 has 62,168 rows (vs ~17,000 other years) — expanded reporting scope, not an error.
  No duplicate (unitid, sport_code) pairs; all loaded.
- 2000-2004: no Schools file in ZIPs. 2005-2006: file uses generic `A3`...`A114` column names
  (pre-standard format) — not loadable for sport-level analysis.

**990 known data points (carry forward):**
- **University of Pennsylvania endowment spending — expected $0 in grants_from_endowment**:
  Penn routes endowment distributions through internal transfers, not as `GrantsOrScholarshipsAmt`
  on Schedule D Part V. Their `grants_from_endowment = 0` is expected reporting behavior, not a
  financial stress signal or data error. Penn has a $18B+ endowment and is financially sound.
  Filter `grants_from_endowment > 0` for any endowment spending rate analysis to avoid false
  low-spend signals from routing artifacts.
- **Yale, Washington University in St. Louis, Emory — endowment distribution routing artifacts**:
  These institutions (and likely others among major research universities) route endowment
  distributions through investment income or internal transfers rather than as
  `GrantsOrScholarshipsAmt` on Schedule D Part V. Their `grants_from_endowment` is near zero
  and `endowment_spending_rate` will be NULL or effectively zero even though they actively
  spend from the endowment. This is an accounting/routing convention, not financial distress.
  These institutions will appear as `stress_endowment = -1` (routing artifact flag) in the
  database. Do NOT interpret a near-zero spending rate as endowment hoarding for these large
  research universities. The `stress_endowment = -1` flag is designed to identify this exact
  pattern: spending_rate < 0.03 with endowment > $100M.
- **Boston College FY2022 — expenses exceed revenue (IPEDS Finance)**: `exp_total` ($1,020,413,247)
  exceeds `rev_total` ($896,965,701) for survey_year 2022. This is a valid data point — investment
  year, not a financial stress signal. Net assets of $4,706,176,061 confirms strong financial health.
  Do not flag as anomalous in any analysis without checking net assets context.

**990 known gaps (carry forward):**
- **MIT FY2013 missing from ProPublica structured dataset**: EIN 042103594,
  fiscal_year_end=2013 (TAX_PERIOD=201306) is absent from `filings_with_data`
  in the ProPublica Nonprofit Explorer API. No error — the year simply was not
  structured by ProPublica. A PDF filing may exist but there is no machine-readable
  source for this year. Total coverage for MIT: FY2012–FY2023 minus FY2013 = 11 rows.
  Workaround: manual PDF extraction or accept the gap; not worth engineering for one row.

### JENNI v1.0 — Production-Ready ✓ (2026-03-28)

The JENNI intelligence layer has been validated against all five core MA private nonprofit
institutions and is declared production-ready as of 2026-03-28. All five outputs rendered
completely with no truncation after the token budget fix. The felt moment — the sense that
the model is genuinely reasoning about institutions rather than summarizing data — was
confirmed across the full validation set.

**What was built (commits in order):**
- `institution_narratives` table + hybrid seeder (21,962 rows: identity, stress_signal,
  financial_profile, hand-crafted for 5 validation institutions)
- `jenni/` package: config, system prompt (accordion epistemic rules, domain conventions),
  query_resolver, synthesizer, delivery, CLI
- `institution_quant` v1.0: 25,376 rows, 25 metrics, peer percentiles, Carnegie peer groups
- pell_pct storage bug fixed (was 0–100, corrected to 0–1 fraction; 22,952 rows patched)
- retention_rate populated from EF Part D `ret_pcf` (65.6% coverage, 2000–2023)
- All peer_pct display bugs fixed (synthesizer + delivery: `pct*100`)
- Scorecard single-year caveat in context package and model prompt
- Partial-year warning in CLI (fires when completeness < 50% and no --year flag)
- retention_rate added to `_METRICS` and `_DISPLAY_METRICS`
- max_tokens raised to 3,072 (standard) / 4,096 (R1/R2 Carnegie or peer_n > 20)
- Stress band refined: "Baseline — no confirmed signals" for score 0.1–1.9 with zero
  confirmed signals (Harvard, MIT, BC, Bentley now render green, not amber)

**Five-institution validation results (survey_year 2022, 2026-03-28):**

| Institution | Carnegie | Peer n | Stress Band | Completeness | Tokens out | Status |
|---|---|---|---|---|---|---|
| Babson College | M3 | 13 | Clean (0.00) | 96.2% | 1,976 | ✓ Complete |
| Bentley University | M1 | 144 | Baseline — no confirmed signals (0.25) | 96.2% | 1,851 | ✓ Complete |
| Boston College | R1 | 36 | Baseline — no confirmed signals (0.50) | 96.2% | 2,133 | ✓ Complete |
| Harvard University | R1 | 36 | Baseline — no confirmed signals (0.50) | 96.2% | 2,390 | ✓ Complete |
| MIT | R1 | 36 | Baseline — no confirmed signals (0.50) | 96.2% | 1,700 | ✓ Complete |

**Key validation findings:**

**BC — confirmed as richest cross-source output.** All four data sources (990, IPEDS, EADA,
Scorecard) at 96.2% completeness. Model surfaced Jesuit presidency compensation convention
(Father Leahy not on Schedule J per Society of Jesus convention), ACC athletics as structural
commitment rather than variable cost, and revenue productivity gap (22nd pctile revenue/FTE
despite top-quartile selectivity) — all unprompted. Operating margin story (normalization
from pandemic peaks, not deterioration) rendered fully at 2,133 tokens; previously truncated
mid-sentence at 2,048 before the token budget fix.

**Harvard — correctly handled Ivy Plus tier limitation and endowment spending rate anomaly.**
Model opened with the peer group caveat unprompted — R1 Carnegie (n=36) is not an appropriate
financial benchmark for Harvard, named the correct peer set (MIT, Stanford, Yale, Princeton,
Penn, Columbia, Duke), and called the R1 percentile "sector-relative positioning, not meaningful
peer comparison." Endowment spending rate anomaly (0.7% reported vs. ~5% policy) explained
correctly: the ratio reflects ending endowment denominator size, not actual payout policy.
Recommended cross-referencing published financial statements before citing in board materials.
This was not prompted; the model derived it from context.

**MIT — surfaced asset vs. revenue leverage distinction unprompted.** Debt-to-assets (14th
pctile — low) and debt-to-revenue (75th pctile — elevated) were correctly identified as
measuring different things: asset-base conservatism vs. revenue-service coverage. The model
stated: "This is not a stress signal, but it is not the same as being low-leverage on both
dimensions." Overhead ratio (97th pctile) and program services (0th pctile) inversion
explained from pre-encoded narrative as indirect cost recovery convention, not inefficiency.

**Bentley — inner terminus correctly placed for strategic questions data cannot answer.**
The model explicitly placed Bentley's enrollment contraction story at the inner terminus:
"Whether Bentley's enrollment contraction reflects a structural market shift or a cyclical
correction is a strategic judgment the data alone cannot make." The endowment deployment
question ("Is Bentley deliberately building the endowment, or simply not drawing on it?")
was correctly identified as unanswerable from financial data alone. Monitoring cadence
recommendation ("net tuition revenue weekly, not annually") was a practical deliverable
that goes beyond what the data says into how to act on it.

**Three pre-production fixes applied and confirmed:**
1. retention_rate populated from EF Part D `ret_pcf` — 65.6% coverage, Babson 95%
2. Stress band "Baseline — no confirmed signals" — zero-confirmed institutions render green
3. Partial-year warning active — fires when completeness < 50% with no `--year` flag set

**Known gaps carried forward to Phase 2:**
- Scorecard historical data: single vintage (2022) only. Bulk download from data.ed.gov
  required for trend direction on net_price, earnings_to_debt_ratio, net_price_to_earnings,
  grad_rate_150. No trend data should be inferred from these metrics until resolved.
- retention_rate NULL for ~34% of institutions (not in EF Part D for non-degree-granting
  and specialized institutions). No alternative source identified.
- Peer group for Harvard/MIT is R1 Carnegie (n=36) — includes public flagships that are
  not financially comparable. Named-peer comparison tier (endowment >$10B) requires a
  separate peer list table not yet built.
- Model narrative label inconsistency: in one Harvard run the model used "Marginal/Clean"
  rather than "Baseline — no confirmed signals." This is acceptable — the terminal header
  is the authoritative display and renders correctly. Model narrative language is
  interpretive and the framing was still accurate.
- `jenni compare` multi-institution command exists but was not included in validation run.
  Validate before using for named-peer side-by-side outputs.

### JENNI Search Layer + Observability ✓ (2026-03-31)

**Search layer (vector-compatible architecture):**
- `jenni/retrieval/` package: `InstitutionRetriever` abstract base, `JENNIDocument` (embedding=None
  until vector layer enabled), `RetrievalResult` envelope, `SQLRetriever`, `WebRetriever`
- `JENNISearchLayer` orchestrates institution/web/news/narrative domains — each independently swappable
- Web search via Anthropic `web_search_20250305` tool activates only on explicit current-awareness
  terms (`recent`, `news`, `appointed`, `merger`, `accreditation`, etc.)
- Retrieved documents persisted to `jenni_documents` table in `jenni_documents.db`
- Vector-ready: `embedding BLOB` column pre-wired; activate by populating at save time

**Observability:**
- `jenni_query_log` table in `jenni_documents.db`: every API call logged on success and failure
- Fields: query_id, query_text, query_type, institutions (JSON), model_used, tokens_in, tokens_out,
  latency_ms, resolver_ms, db_query_ms, synthesizer_ms, delivery_ms, completeness, accordion_position, error
- System backup events logged with `query_type='system_backup'`, `model_used='system'`

**Query classifier — new type:**
- `institution_profile`: catches "tell me about / overview / financial health / profile" queries
  that were previously misrouted to `stress`. Routes to Sonnet, same token budget as `analysis`.
- Stress classification tightened: requires unambiguous distress language (stress, distress,
  closure, bankrupt, struggling, troubled, vulnerable). "financial health" and "risk" removed.

**GitHub + S3:**
- Remote: https://github.com/thx1138234/project-jenni (public)
- S3 backup: `aws s3 sync data/databases/ s3://project-jenni-data/databases/` — all 6 databases
- Weekly cron: `0 2 * * 0` runs `scripts/s3_backup.sh` → dated path `backups/YYYY-MM-DD/`

### Performance Benchmarks ✓ (2026-03-31)

Measured against: `jenni analyze "Tell me about Harvard University financial health" --year 2022`

| Stage | Latency | Notes |
|---|---|---|
| `resolver_ms` | **<100ms** | Entity match (difflib) + context assembly + 3 SQLite connections |
| `db_query_ms` | **<10ms** | Pure SQLite query time — effectively free |
| `synthesizer_ms` | **~40,000ms total** | Claude Sonnet API; streaming so first token ~2–3s |
| `delivery_ms` | **<10ms** | Rich terminal rendering — effectively free |
| **perceived latency** | **~2s to first output** | Metrics table renders before API call; synthesis streams |

**Architecture decisions behind the numbers:**
- Resolver was 15,822ms before web search gating fix (2026-03-31). Tightening `needs_web_search()`
  to require explicit current-awareness signals dropped it to <100ms for all standard queries.
  Web search only fires on queries containing: `recent`, `news`, `latest`, `appointed`, `merger`,
  `accreditation`, `closure`, `layoffs`, `strike`, and year patterns ≥2024.
- SQLite is not the bottleneck. 4ms for full institution_quant + 990 + IPEDS joins. Do not
  migrate to PostgreSQL for performance reasons — the motivation is shared access, not speed.
- Claude API is 99.6% of total latency and is non-negotiable. The only mitigation is streaming:
  `synthesize_stream()` in `jenni/synthesizer.py` yields str chunks via `client.messages.stream()`.
- Metrics table renders immediately from `context` (before API call) via `render_before_stream()`
  in `jenni/delivery.py`. User sees quantitative data within 100ms; synthesis arrives in stream.

**Streaming implementation notes:**
- `synthesize_stream(context)` — generator; yields `str` chunks then one final `dict`
- `synthesize(context)` — non-streaming, used for `--json` output path only
- `render_before_stream(ctx)` — header + metrics table, called before API round-trip
- `render_stream_header()` — rule separator before streaming text begins
- `render_stream_footer(ctx, syn)` — data quality footer after stream completes
- JSON path still uses `synthesize()` (non-streaming) since the full text is needed before serialisation

### Supplemental Context Trigger Audit ✓ (2026-03-31)

**Trigger condition:** A supplemental table is only useful to the model if it is (a) loaded
into `institution_data` by `_load_institution_data()` in `query_resolver.py` AND (b) formatted
into the prompt by `_format_context_for_model()` in `synthesizer.py`, subject to an optional
trigger condition (query type or keyword match).

**Audit results — as of 2026-03-31:**

| Supplemental Table | Loaded? | Formatted? | Trigger Condition | Status |
|---|---|---|---|---|
| `form990_part_ix` | ✅ | ✅ | `query_type in (comparison, institution_profile)` OR `_EXPENSE_WORDS` in query | **Wired** (2026-03-31) |
| `form990_schedule_d` | ❌ | ❌ | None | **Silent gap** |
| `form990_compensation` | ❌ | ❌ | None | **Silent gap** |
| `eada_instlevel` | ❌ | ❌ | None | **Silent gap** |
| `eada_sports` | ❌ | ❌ | None | **Silent gap** |
| `form990_governance` | ❌ | ❌ | None | **Silent gap** |
| `form990_related_orgs` | ❌ | ❌ | None | Out of scope for now |

**What each silent gap means for the model:**

- **schedule_d**: Model gets `endowment_runway` and `endowment_per_student` from `institution_quant`
  (derived values), but NOT the raw year-by-year endowment flows: BOY balance, investment return,
  new contributions, grants from endowment, EOY balance, spending rate, corpus breakdown
  (board-designated / perm-restricted / temp-restricted). A query like "Tell me about Harvard
  endowment management" gets only the derived summary — the underlying 4-year Schedule D
  detail ($49B EOY, $1.3B investment return FY2023, 7.89yr runway) never reaches the model.

- **compensation**: Model gets nothing about officer pay from live data. Pre-encoded narratives
  (auto_seeded) may contain some officer comp text, but no Schedule J data is formatted into
  the prompt. "What does the Harvard president earn" produces a response from institutional
  knowledge only — the 104 Harvard compensation rows ($1.3M Bacow FY2022, etc.) are invisible.

- **eada_instlevel / eada_sports**: Model gets `athletics_net`, `athletics_to_expense_pct`,
  `athletics_per_student` from `institution_quant` (derived from EADA), plus a pre-encoded
  `athletics` narrative. But sport-by-sport detail (football: $47.2M revenue / $38.1M expense
  at BC FY2024; basketball, ice hockey) never reaches the model. "Tell me about BC athletics
  economics" gets the aggregate summary — the sport-level P&L is a silent gap.

**Test queries run (2026-03-31):**
- `jenni analyze 'Tell me about Harvard endowment management'` → no schedule_d block in context
- `jenni analyze 'What does the Harvard president earn'` → no compensation block in context
- `jenni analyze 'Tell me about Boston College athletics economics'` → no eada_sports block in context

**Wiring priority (next session):**
1. `form990_schedule_d` — high value; endowment management is a common analytical question.
   Trigger: `query_type in (comparison, institution_profile)` OR `_ENDOWMENT_WORDS` in query
   (endowment, runway, distribution, spending, corpus, investment return).
2. `form990_compensation` — high value; compensation questions are common and specific.
   Trigger: `_COMP_WORDS` in query (earn, salary, compensation, paid, president, coach, officer).
3. `eada_sports` — medium value; sport-level detail needed for athletics economics questions.
   Trigger: `_ATHLETICS_WORDS` in query (athletics, sport, football, basketball, coaching).
   Note: eada_data.db requires a fourth DB connection in `_load_institution_data()`.
4. `form990_governance` — lower priority; governance questions are less frequent.

**Data availability confirmed:**
- Harvard: schedule_d 4 rows (FY2020-2023), compensation 104 rows, eada_instlevel 18 rows, eada_sports 367 rows
- BC: schedule_d 4 rows (FY2020-2023), compensation 74 rows (incl. Hafley $3.8M FY2023), eada_instlevel 19 rows, eada_sports 327 rows

### Phase 2 Complete
- [x] GitHub repo public — https://github.com/thx1138234/project-jenni
- [ ] PostgreSQL on Supabase, migrated from SQLite
- [x] College Scorecard loaded (scorecard_data.db: 6,322 institution rows, 217,530 program rows)
- [ ] Read-only API endpoint live

---

## Environment

- **OS:** Linux Mint (Ubuntu Noble base)
- **Python:** 3.x (standard library sqlite3; `requests` required for downloader)
- **Git:** initialized at commit c3a4680 (Phase 1 IPEDS checkpoint, March 2026)
- **Database:** SQLite at `data/databases/ipeds_data.db` (.gitignored — rebuild from source)

---

## Contact / Maintenance Notes

This database is maintained as a research repository.
Data is sourced entirely from public federal sources (IRS, NCES, Dept. of Education).
All source data is public domain. Code is MIT licensed.

---

## Annual Refresh Policy — Comprehensive Collection (Standing Policy)

**The policy is: ingest everything available. No selective ingestion.**

When NCES, IRS, EADA, or Scorecard releases new data, the default action is:
download all new files and run all parsers and loaders. Do not filter by schedule,
component, or field set. Comprehensive collection now costs nothing (compute is
cheap, storage is cheap); selective ingestion costs research value that is hard
to recover later.

### The Rhythms of the Forward Hand — Annual Release Cadence

These are the rhythms by which the accordion's forward terminus advances.
Check these dates when assessing whether new data is available.

| Source | Typical release | What it adds | Notes |
|---|---|---|---|
| **IRS TEOS** | ~March each year | New index year (prior calendar year's filings) | TEOS 2025 (~March 2026) = FY2024 filings. Financial metrics for survey_year N require FY(N+1) filings. |
| **NCES IPEDS** | Rolling, ~18 months after AY end | All 12 components for completed academic year | AY 2023–24 (survey_year=2023) final release ~early 2026. Provisional data available sooner. HD, IC, EF released first; Finance, GR, completions released later. |
| **Dept. of Education EADA** | ~January each year | Athletics financials for prior academic year | EADA 2024 (survey_year=2024) released ~January 2025. Usually the earliest of the four sources. |
| **College Scorecard** | ~October each year | Earnings, debt, completion by program | Scorecard 2024 (~October 2024) = earnings data for students who entered ~2017–2018. Lags enrollment by ~6 years. |

**Practical implication for the accordion:**
- **January**: Check for new EADA data. Run athletics refresh if available.
- **March**: Watch for new TEOS index year. When it drops, run full 990 pipeline + supplemental runner + institution_quant refresh.
- **October**: Check for new Scorecard. Run scorecard loader + institution_quant value refresh.
- **Rolling (check quarterly)**: IPEDS components release on different schedules. HD and EF often arrive before Finance and GR. Do not wait for all components — load each as it appears.

The INSERT OR IGNORE architecture means partial refreshes are always safe.
A new EADA year can be loaded without touching 990 or IPEDS rows.

### 990 Annual Refresh (IRS TEOS — new index year released ~March each year)

```bash
# 1. Download new TEOS index year (e.g., year 2025 for FY2024 filings)
.venv/bin/python3 ingestion/990/downloader.py \
    --db   data/databases/ipeds_data.db \
    --years 2025 \
    --out  data/raw/990_xml

# 2. Parse main form into form990_filings
.venv/bin/python3 ingestion/990/parser.py \
    --db data/databases/990_data.db

# 3. Run ALL supplemental parsers in one pass
.venv/bin/python3 ingestion/990/supplemental_runner.py \
    --db  data/databases/990_data.db \
    --xml data/raw/990_xml
# Parsers: schedule_d, part_ix, compensation, schedule_r, governance
# All are idempotent — safe to re-run; replaces rows for updated filings.

# 4. Rebuild derived layers
.venv/bin/python3 ingestion/990/stress_signals_builder.py \
    --db data/databases/990_data.db
.venv/bin/python3 ingestion/institution_quant_builder.py \
    --db990 data/databases/990_data.db \
    --ipeds data/databases/ipeds_data.db \
    --eada  data/databases/eada_data.db \
    --scorecard data/databases/scorecard_data.db \
    --out   data/databases/institution_quant.db \
    --stage all
```

### IPEDS Annual Refresh (NCES — released throughout the year by component)

```bash
# Download all new components for the new year
python3 ingestion/ipeds/downloader.py --year {new_year}

# Load all components — loader skips already-loaded rows
python3 ingestion/ipeds/loader.py --db data/databases/ipeds_data.db --year {new_year}

# Load E12 FTE (separate loader)
python3 ingestion/ipeds/e12_loader.py --db data/databases/ipeds_data.db

# Rebuild institution_quant for the new year
python3 ingestion/institution_quant_builder.py ... --stage all
```

**Do not cherry-pick components.** If NCES releases ADM, EF, HR, Finance,
Completions, and GR for the same year, load all of them. Skipping one now
means a gap in longitudinal analysis that is painful to backfill.

### EADA Annual Refresh (Dept. of Education — released ~January each year)

```bash
python3 ingestion/eada/downloader.py
python3 ingestion/eada/loader.py     --db data/databases/eada_data.db
python3 ingestion/eada/sports_loader.py --db data/databases/eada_data.db
```

### College Scorecard Refresh (annual — API pull)

```bash
python3 ingestion/scorecard/api_client.py
python3 ingestion/scorecard/loader.py --db data/databases/scorecard_data.db
```

### After Any Refresh

1. Verify row counts against previous build (should only increase)
2. Run validation institution spot checks (5 MA private nonprofits)
3. Update `CHANGELOG.md` with new year and row counts
4. Commit schema and code changes only (.db files are .gitignored)
5. Re-run `institution_quant_builder.py --stage all` to refresh the quant layer

### 990 Zone Coverage and Supplemental Table Availability

| Zone | TEOS index years | Approx fiscal years | form990_filings | Supplemental schedules |
|---|---|---|---|---|
| Zone 1 (historical) | n/a — ProPublica | FY2012–FY2019 | ✓ (propublica source) | ✗ — ProPublica JSON has no schedule detail |
| Zone 3 (current) | 2021–2024 | FY2019–FY2024 | ✓ (irsx source) | ✓ — all supplemental parsers run |
| Zone 3+ (refresh) | 2025+ | FY2024+ | ongoing | ongoing |

**Zone 2 (TEOS index years 2017–2020) is inaccessible**: The IRS TEOS bulk ZIPs for
index years 2017, 2018, 2019, and 2020 all return HTTP 302 redirecting to
`https://www.irs.gov/404`. The index CSVs are accessible but the actual ZIP files
are not downloadable. This was confirmed March 2026 by probing all 12 monthly ZIP
patterns for each year. Only index years 2021+ have accessible bulk ZIPs.

**Practical result**: Supplemental schedule coverage (Schedule D, Part IX, Schedule J,
Schedule R, Part VI governance) begins at FY2019/FY2020 and cannot be extended
further back via TEOS bulk download. The Zone 1 supplemental gap (FY2012–FY2019) is
permanent under the current architecture.

**When to add backfill if TEOS changes**: If the IRS ever restores bulk ZIP access
for pre-2021 index years, run the downloader for those years and re-run
`supplemental_runner.py`. The runner is idempotent and will add new rows without
disturbing existing data.

---

### Supplemental Table Summary

| Table | Parser | Schedule / Part | Rows | TEOS coverage |
|---|---|---|---|---|
| `form990_schedule_d` | schedule_d_parser.py | Schedule D Part V (endowment) | 4,360 | FY2019–FY2024 |
| `form990_part_ix` | part_ix_parser.py | Part IX (functional expenses) | 5,171 | FY2019–FY2024 |
| `form990_compensation` | compensation_parser.py | Schedule J (officer comp) | 40,350 | FY2019–FY2024 |
| `form990_related_orgs` | schedule_r_parser.py | Schedule R (related orgs) | 33,600 | FY2020–FY2024 |
| `form990_related_transactions` | schedule_r_parser.py | Schedule R Part V (transactions) | 7,790 | FY2020–FY2024 |
| `form990_governance` | governance_parser.py | Part VI (board/policy) | 5,171 | FY2019–FY2024 |

All row counts as of March 2026. Zone 2 backfill not feasible (pre-2021 TEOS ZIPs inaccessible).
