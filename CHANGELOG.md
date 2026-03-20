# Changelog

All notable changes to this database project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased] — Phase 1 In Progress

### Added — IPEDS full build, all years 2000–2024 (March 2026)
- Full project structure migrated to `~/claude/projects/project-jenni/`
- `schema/ipeds_schema.sql` — all 9 tables + 4 analytical views
- `ingestion/ipeds/downloader.py` — NCES bulk file fetcher with manifest tracking
- `ingestion/ipeds/loader.py` — full component loader (IC, ADM, EF, C, GR, SFA, F, HR, INST)

#### Final row counts (all years loaded):

| Table | Rows | Year Range | Notes |
|---|---|---|---|
| `institution_master` | 13,609 institutions | — | HD source; 2000/2001 = stubs only (no HD on NCES) |
| `ipeds_ic` | 174,441 | 2000–2024 | IC + IC_AY merged per year |
| `ipeds_adm` | 20,571 | 2014–2023 | ADM standalone from 2014 only |
| `ipeds_ef` | 160,861 | 2000–2023 | enrtot NULL for 2000/2001 (old EF format, see known issues) |
| `ipeds_completions` | 5,911,068 | 2000–2024 | |
| `ipeds_gr` | 106,234 | 2000–2023 | |
| `ipeds_sfa` | 139,781 | 2001–2022 | AY 2023-24 not yet released |
| `ipeds_finance` | 87,020 | 2000–2022 | 43,510 FASB + 43,510 GASB; AY 2023-24 not yet released |
| `ipeds_hr` | 46,768 | 2012–2023 | HR files start 2012 on NCES |
| **Total** | **6,660,353** | | |

- IPEDS 2022 & 2023 initial build (before full range):
  - `institution_master`: 6,349 institutions (HD source, includes EIN + OPEID)
  - `ipeds_ic`: 12,187 rows (merged IC + IC_AY per year)
  - `ipeds_adm`: 3,963 rows
  - `ipeds_ef`: 11,353 rows
  - `ipeds_completions`: 561,828 rows
  - `ipeds_gr`: 7,510 rows
  - `ipeds_sfa`: 5,653 rows (2022 only — AY 2023-24 not yet released)
  - `ipeds_finance`: 3,832 rows — 1,916 FASB + 1,916 GASB (see note below)
  - `ipeds_hr`: 7,142 rows

### Decisions & Clarifications
- **GASB finance data loaded alongside FASB** — the original deferral policy
  (FASB-only) was never enforced in `FinanceLoader`; `_load_gasb()` runs
  unconditionally. Both F1A and F2 rows loaded cleanly and are correctly labeled
  with `reporting_framework`. Decision: accept both as loaded. The cross-sector
  comparison warnings in `docs/gasb_fasb_crosswalk.md` still apply.
  CLAUDE.md updated to reflect actual state.

### Fixed — EF loader and room & board (March 2026)
- **EF enrollment totals now correct**: `_load_part_a` was filtering on
  `lstudy in ("", "1")` which missed the all-student aggregate row
  (`efalevel=1`, `lstudy=4`). Fixed to index Part A rows by `efalevel` and
  pull totals from `efalevel=1` (all students), `efalevel=2` (undergrad),
  `efalevel=12` (grad). Also discovered Part D (`ef{year}d.csv`) contains
  retention/cohort data, not enrollment totals — enrollment lives in Part A.
  Part A now uses UPDATE instead of INSERT OR REPLACE to preserve `stufacr`
  from Part D without clobbering it. EF reloaded for 2022 & 2023.
  Babson confirmed: enrtot=3,989 (2022), enrtot=3,943 (2023).
- **Room & board now room + board**: `roomboard_oncampus` was mapping to
  `chg4ay0` (room charge only). Fixed to sum `chg4ay0` + `chg5ay0` (board).
  Babson confirmed: $17,920 (2022), $18,852 (2023).

### Known Issues (open)
- **EF enrollment NULL for 2000/2001**: Pre-2002 IPEDS EF Part A files use
  `line`/`section` column layout instead of the modern `efalevel` column.
  The loader expects `efalevel` and finds no matching rows; `enrtot`,
  `enrugrd`, and `enrgrad` are NULL for all 2000 and 2001 institutions.
  EF-D rows exist (6,083 for 2000; 6,560 for 2001) but enrollment totals
  are unpopulated. Race/ethnicity columns also unresolved for these years.
  Fix requires reverse-engineering the old EF Part A format mapping.
- **HR full professors field**: `sisprof` may be 0 for institutions that classify
  faculty without academic rank (e.g., Babson). Needs verification against a
  school with traditional faculty rank structure before trusting HR rank data.
- **SFA/Finance 2023 not available**: AY 2023-24 NCES files not yet released
  as of March 2026.
- **HR starts 2012**: `S{year}_SIS.zip` files do not appear on NCES before
  2012. `ipeds_hr` has no coverage for 2000–2011.

### Added — prior work (Jan 2026)
- Repository structure established
- Master README with full source documentation
- Babson College FY2023 Form 990 sample CSVs (Parts VIII, IX, X, XI)
- 990 database schema (SQLite)
- 990 XML parser (Python)
- EADA database: 30,753 records, 2,269 institutions, 2010–2024
- IPEDS prototype: 16 Massachusetts institutions, AY2024–2025
- Institution master schema (EIN + UNITID + OPEID join keys)

### Planned (Phase 1 completion)
- 990 XML ingestion for 10+ institutions
- Expand IPEDS build to full year range (2000–present)
- College Scorecard schema and API client

---

## Data Source Versions

| Source | Version / Year | Date Accessed |
|---|---|---|
| Form 990 — Babson College | FY2023 (Tax Year 2022) | Jan 2026 |
| EADA | 2010–2024 | Jan 2026 |
| IPEDS | AY2024–2025 | Jan 2026 |
| College Scorecard | — | Not yet ingested |
