# Higher Education Financial & Institutional Database

A multi-source, AI-ready database combining public federal financial and institutional
data for U.S. higher education institutions. Built for longitudinal research, 
benchmarking, and AI-driven analysis.

---

## Project Status

| Database | Status | Records | Coverage |
|---|---|---|---|
| `990_data.db` | 🔄 In Progress | Babson FY2023 loaded | Schema complete; ingestion pipeline built |
| `eada_data.db` | ✅ Complete | 30,753 records | 2,269 institutions, 2010–2024 |
| `ipeds_data.db` | ⚠️ Prototype | 16 MA schools | AY2024–2025; expanding |
| `scorecard_data.db` | 📋 Planned | — | Schema designed; API integration next |

---

## Why This Database Exists

Federal financial data on higher education is rock-solid, mandatory, and public —
but it's fragmented across four separate systems that don't talk to each other.
This project unifies them under a common institution identifier so they can be
queried together.

| Source | What It Adds | Key Identifier |
|---|---|---|
| **IRS Form 990** | Audited financials: revenue, expenses, assets, net assets | EIN |
| **IPEDS** | Enrollment, admissions, tuition, graduation rates, staffing | UNITID |
| **EADA** | Athletics revenues, expenses, coaching salaries by gender | UNITID |
| **College Scorecard** | Post-graduation earnings & debt by program and CIP code | UNITID / OPEID |

---

## Repository Structure

```
higher-ed-db/
│
├── README.md                        ← This file
├── CHANGELOG.md                     ← Version history and data updates
├── .gitignore
│
├── schema/                          ← Source-of-truth schema definitions
│   ├── 990_schema.sql
│   ├── ipeds_schema.sql
│   ├── eada_schema.sql
│   ├── scorecard_schema.sql
│   └── institution_master.sql       ← Shared institution lookup table
│
├── ingestion/                       ← Data pipeline scripts
│   ├── 990/
│   │   ├── parser.py                ← XML → structured records
│   │   ├── loader.py                ← Records → SQLite
│   │   ├── ingest.py                ← CLI entry point
│   │   └── field_map.py             ← Form 990 line item → column mapping
│   ├── ipeds/
│   │   ├── downloader.py            ← NCES bulk file fetcher
│   │   └── loader.py
│   ├── eada/
│   │   └── loader.py
│   └── scorecard/
│       ├── api_client.py            ← College Scorecard API wrapper
│       └── loader.py
│
├── data/
│   ├── raw/                         ← Original source files (gitignored if large)
│   │   ├── 990_xml/
│   │   ├── ipeds_csv/
│   │   └── eada_csv/
│   ├── sample/                      ← Small sample files for testing (committed)
│   │   ├── 990_Babson_2023_partx_balance_sheet.csv
│   │   ├── 990_Babson_2023_partix_functional_expenses.csv
│   │   ├── 990_Babson_2023_partviii_revenue.csv
│   │   └── 990_Babson_2023_partxi_reconciliation_of_net_assets.csv
│   └── databases/                   ← SQLite .db files (gitignored; use Git LFS or external storage)
│       ├── 990_data.db
│       ├── eada_data.db
│       ├── ipeds_data.db
│       └── scorecard_data.db
│
├── institution_master/
│   ├── institution_list.csv         ← Master list: institution name, EIN, UNITID, OPEID
│   └── cip_codes_of_interest.csv    ← Curated CIP code reference table
│
├── queries/                         ← Reusable analytical SQL queries
│   ├── financial_ratios.sql
│   ├── endowment_trends.sql
│   ├── revenue_by_source.sql
│   └── cross_source_joins.sql       ← 990 + IPEDS + EADA combined views
│
├── docs/
│   ├── data_sources.md              ← Source descriptions, URLs, update cadence
│   ├── field_definitions.md         ← Column-level data dictionary
│   ├── cip_code_guide.md            ← CIP codes relevant to this project
│   ├── fiscal_year_conventions.md   ← How we handle 990 vs IPEDS year alignment
│   └── roadmap.md                   ← Planned expansions
│
└── tests/
    ├── test_990_parser.py
    ├── test_loader.py
    └── test_schema_integrity.py
```

---

## Data Sources

### Form 990 (IRS via ProPublica Nonprofit Explorer)
- **URL:** https://projects.propublica.org/nonprofits/
- **Format:** XML (e-filed returns)
- **Update cadence:** Annual; typically 12–18 months lag after fiscal year end
- **Coverage:** All 501(c)(3) organizations; mandatory for revenue > $200K
- **Key parts ingested:**
  - Part VIII — Statement of Revenue
  - Part IX — Statement of Functional Expenses
  - Part X — Balance Sheet
  - Part XI — Reconciliation of Net Assets

### IPEDS (NCES — National Center for Education Statistics)
- **URL:** https://nces.ed.gov/ipeds/
- **Format:** CSV bulk download or REST API
- **Update cadence:** Annual (fall/winter/spring survey windows)
- **Key survey components:** Institutional Characteristics, Enrollment, Admissions,
  Completions, Graduation Rates, Finance, Human Resources

### EADA (Equity in Athletics Disclosure Act — U.S. Dept. of Education)
- **URL:** https://ope.ed.gov/athletics/
- **Format:** CSV bulk download
- **Update cadence:** Annual
- **Coverage:** All Title IV institutions with intercollegiate athletics programs

### College Scorecard (U.S. Dept. of Education)
- **URL:** https://collegescorecard.ed.gov/data/
- **API:** https://collegescorecard.ed.gov/data/api/
- **Format:** REST API + CSV bulk download
- **Update cadence:** Annual
- **Key data:** Post-graduation earnings and federal debt by 4-digit CIP code
  and credential level (institution-level and field-of-study-level)

---

## Institution Identifiers — The Join Keys

Every institution in this database carries three identifiers:

| Field | Source | Description |
|---|---|---|
| `ein` | IRS / Form 990 | Employer Identification Number — 9 digits |
| `unitid` | IPEDS | 6-digit federal institution ID — primary join key for IPEDS, EADA, Scorecard |
| `opeid` | Dept. of Education | 8-digit OPE ID — used by College Scorecard (6-digit version for main campus rollups) |

The `institution_master` table is the canonical lookup that maps all three.
All source-specific tables foreign-key to `institution_master.unitid`.

---

## Fiscal Year Convention

Form 990 and IPEDS use different year reference conventions. This database
standardizes on **fiscal year end date** as the canonical year label.

| Institution Type | Typical Fiscal Year | 990 Tax Year Label |
|---|---|---|
| Most private universities | July 1 – June 30 | Year the FY *began* (e.g., FY ending June 2023 = Tax Year 2022) |
| Some universities | June 1 – May 31 | Same convention |
| Public institutions | Varies by state | Same convention |

See `docs/fiscal_year_conventions.md` for full handling rules.

---

## Quickstart (Local)

```bash
# Clone the repo
git clone https://github.com/[org]/higher-ed-db.git
cd higher-ed-db

# Install dependencies
pip install -r requirements.txt

# Build databases from source files
python ingestion/990/ingest.py --source data/raw/990_xml/
python ingestion/ipeds/loader.py --source data/raw/ipeds_csv/
python ingestion/eada/loader.py --source data/raw/eada_csv/

# Verify integrity
python tests/test_schema_integrity.py

# Run a sample query
sqlite3 data/databases/990_data.db < queries/financial_ratios.sql
```

---

## Roadmap

**Phase 1 — Stable Prototype** *(current)*
- [ ] Load 990 XML for 10+ institutions, FY2020–2024
- [ ] Standardize institution_master table across all four DBs
- [ ] Complete schema documentation
- [ ] All ingestion scripts reproducible from scratch

**Phase 2 — Repository Launch**
- [ ] Push to GitHub with full documentation
- [ ] Migrate to PostgreSQL on Supabase for shared live access
- [ ] Add College Scorecard ingestion pipeline

**Phase 3 — Expansion**
- [ ] Expand 990 coverage to 50+ institutions nationally
- [ ] Add program-level data table (HF/UX/XD MS programs as pilot)
- [ ] Build derived metrics views (endowment per student, tuition dependency ratio, etc.)
- [ ] Publish as Hugging Face dataset for AI research community

---

## Data Licensing

All data in this repository derives from public federal sources:
- IRS Form 990 filings are public domain
- IPEDS data is public domain (U.S. government work)
- EADA data is public domain (U.S. government work)
- College Scorecard data is public domain (U.S. government work)

Code in this repository is licensed under MIT.

---

## Contributing

See `docs/roadmap.md` for planned work. Key immediate needs:
1. Additional 990 XML files for institutions beyond Babson
2. Validation of IPEDS UNITID ↔ EIN mappings
3. College Scorecard API client and schema

---

*Maintained as a research database for higher education financial analysis.*
*Not affiliated with IRS, NCES, or U.S. Department of Education.*
