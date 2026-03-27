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
| Score | Band | Interpretation |
|---|---|---|
| 6.5+ | CRITICAL | Confirmed multi-domain crisis: financial + severe enrollment decline co-occurring |
| 5.0–6.4 | HIGH | Multiple confirmed stress trends; acute risk without intervention |
| 3.5–4.9 | Elevated | Confirmed stress across multiple signals; monitoring required |
| 2.0–3.4 | Baseline | Confirmed stress in 1–2 signals; emerging pattern |
| 0.1–1.9 | Marginal | Isolated or single-year signals; likely noise or COVID artifact |
| 0 | Clean | No signals fired across any year |

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

The authoritative signal layer is **`institution_quant`**, currently being designed. When
`institution_quant` is built, it will supersede `financial_stress_signals` as the primary
stress scoring surface. Do not build downstream product features that hard-depend on
`financial_stress_signals` column names or score bands — treat it as exploratory scaffolding.

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

### Phase 2 Complete
- [ ] GitHub repo public
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

When adding new data years annually:
1. Run `downloader.py` — it will skip already-downloaded files
2. Run `loader.py --year {new_year}` for the new year only
3. Update `CHANGELOG.md`
4. Run integrity tests
5. Commit schema and code changes only (not .db files)
