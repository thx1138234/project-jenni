# Database Roadmap

---

## Phase 1 — Stable Local Prototype
*Goal: A fully reproducible, documented local database worth pushing to a repo.*

### 990 Pipeline
- [ ] Ingest XML for 10+ institutions (beyond Babson)
- [ ] Cover at least FY2020–FY2023 per institution
- [ ] Validate parser output against CSV samples
- [ ] Document all Part VIII / IX / X / XI field mappings

### Institution Master
- [ ] Build `institution_master.csv` with EIN + UNITID + OPEID for all target schools
- [ ] Validate all three identifiers against source systems
- [ ] Define initial institution scope (MA-focused? National top-100?)

### Schema & Documentation
- [ ] Commit all schema .sql files
- [ ] Complete field_definitions.md data dictionary
- [ ] All ingestion scripts run clean from scratch on a fresh machine

### Tests
- [ ] Row count assertions for each database
- [ ] Referential integrity checks (all foreign keys resolve)
- [ ] Year coverage checks per institution

---

## Phase 2 — Repository Launch
*Goal: Shared, live-queryable database with clean public repo.*

### Infrastructure
- [ ] Push to GitHub
- [ ] Migrate SQLite → PostgreSQL
- [ ] Host on Supabase (free tier to start)
- [ ] Set up read-only API endpoint for external queries

### College Scorecard
- [ ] Build API client (`ingestion/scorecard/api_client.py`)
- [ ] Define schema for institution-level and field-of-study-level tables
- [ ] Load initial data for all institutions in institution_master

### Documentation
- [ ] GitHub README badges (build status, record counts)
- [ ] Contributor guide
- [ ] Example Jupyter notebooks for common analyses

---

## Phase 3 — Expansion
*Goal: Broader institutional coverage and richer program-level data.*

### Coverage
- [ ] Expand 990 to 50+ institutions nationally
- [ ] Add program-level table (seed with HF/UX/XD MS programs)
- [ ] Consider Executive DBA / doctoral program tuition table (web-scraped)

### Analytics Layer
- [ ] Derived metrics views:
  - Endowment per student
  - Tuition dependency ratio
  - Instruction expense per student
  - Revenue diversification index
- [ ] Year-over-year trend calculations
- [ ] Peer group benchmarking queries

### Public Release
- [ ] Publish as Hugging Face dataset
- [ ] DOI / citation metadata
- [ ] Data update automation (annual refresh scripts)

---

## Open Questions / Decisions Needed

1. **Institution scope:** Start MA-only and expand, or define a national target list upfront?
2. **Database hosting:** Supabase vs Render vs self-hosted PostgreSQL?
3. **990 coverage depth:** All parts, or continue with Parts VIII/IX/X/XI only?
4. **Program title enrichment:** Build scraping pipeline for actual program names, or keep CIP-code-only for now?
5. **Public vs private repo:** Research archive (public) or controlled access first?
