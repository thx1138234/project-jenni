# Data Sources Reference

Detailed documentation on each data source: what it contains, where to get it,
update cadence, known limitations, and ingestion notes.

---

## 1. IRS Form 990

**What it is:** Annual information return filed by tax-exempt organizations.
Mandatory for 501(c)(3) organizations with gross receipts ≥ $200,000 or
total assets ≥ $500,000.

**Why it's valuable:** Audited, standardized, mandatory. The most reliable
source of financial data for private nonprofit universities.

**Access:**
- ProPublica Nonprofit Explorer: https://projects.propublica.org/nonprofits/
- IRS bulk data (XML): https://www.irs.gov/charities-non-profits/form-990-series-downloads

**Format:** XML (e-filed returns). PDFs also available but not machine-readable.

**Parts ingested:**

| Part | Title | Key Fields |
|---|---|---|
| Part VIII | Statement of Revenue | Tuition, contributions, investment income, total revenue |
| Part IX | Statement of Functional Expenses | Program, management, fundraising expenses by category |
| Part X | Balance Sheet | Assets, liabilities, net assets (BOY and EOY) |
| Part XI | Reconciliation of Net Assets | Net asset change, investment gains/losses |

**Known limitations:**
- 12–18 month lag between fiscal year end and public availability
- Fiscal years vary by institution (most end June 30)
- IRS labels fiscal year by start year (e.g., FY ending June 2023 = "Tax Year 2022")
- 990-EZ filers (smaller orgs) have less detail — not in scope for this database
- Form 990-T (unrelated business income) excluded by design — data already captured in aggregate on Form 990

**Ingestion method:** Download XML from ProPublica; parse with `ingestion/990/parser.py`

---

## 2. IPEDS — Integrated Postsecondary Education Data System

**What it is:** Annual federal survey system collecting institution-level data
from all Title IV-eligible postsecondary institutions (~6,000 schools).
Managed by NCES (National Center for Education Statistics).

**Why it's valuable:** The operational complement to Form 990 financials.
Provides enrollment, admissions, graduation rates, staffing — things Form 990
doesn't capture.

**Access:**
- Data Center: https://nces.ed.gov/ipeds/datacenter/
- Bulk CSV download: https://nces.ed.gov/ipeds/use-the-data
- API: Limited; bulk download preferred

**Survey components ingested:**

| Component | Key Fields |
|---|---|
| Institutional Characteristics (IC) | Control, Carnegie class, calendar system, degrees offered |
| Enrollment (EF) | Total, undergrad, graduate; FT/PT; by race/gender |
| Admissions (ADM) | Applications, admits, enrollees, SAT/ACT scores, admit rate |
| Completions (C) | Degrees awarded by CIP code, level, gender, race |
| Student Financial Aid (SFA) | % receiving aid, avg grant amount, net price by income band |
| Graduation Rates (GR) | 4-year, 6-year rates; first-time full-time cohort |
| Finance (F) | Revenue, expenses, endowment — for public institutions primarily |
| Human Resources (HR) | Faculty count, staff count, avg salary |

**Known limitations:**
- Tuition data is institution-level only — not broken out by program
- Program title data uses CIP code labels, not marketed program names
- Finance component is less reliable for private institutions (Form 990 is better)
- Data lags ~12 months after the academic year

**Ingestion method:** Bulk CSV download from NCES; load with `ingestion/ipeds/loader.py`

---

## 3. EADA — Equity in Athletics Disclosure Act

**What it is:** Annual federal disclosure required of all Title IV institutions
with intercollegiate athletics programs. Submitted to U.S. Dept. of Education.

**Why it's valuable:** The only public source with program-level athletics
financials. Form 990 buries athletics costs in generic functional categories.

**Access:**
- https://ope.ed.gov/athletics/
- Direct CSV download available by year

**Key fields:** Total athletics revenues and expenses, coaching salaries (by
sport and gender), recruiting expenses, scholarship amounts, participation
counts by sport and gender.

**Coverage in this database:** 30,753 records, 2,269 institutions, 2010–2024.

**Known limitations:**
- Self-reported; methodology varies across institutions
- Some schools allocate indirect costs differently
- Does not distinguish between varsity and club sports at all institutions

**Ingestion method:** CSV download; loaded with `ingestion/eada/loader.py`

---

## 4. College Scorecard

**What it is:** U.S. Dept. of Education transparency tool combining IPEDS
institutional data with IRS earnings records and NSLDS federal loan data.
Provides post-graduation outcomes at institution and field-of-study level.

**Why it's valuable:** The only public source linking specific programs (by
CIP code + credential level) to post-graduation earnings and federal debt.
Earnings data comes directly from IRS W-2 records — not self-reported.

**Access:**
- Data portal: https://collegescorecard.ed.gov/data/
- API: https://collegescorecard.ed.gov/data/api/ (free, 1,000 req/hr default)
- API key required: https://api.data.gov/signup/

**Two data layers:**

| Layer | Unit of Analysis | Key Fields |
|---|---|---|
| Institution-level | School | Tuition, net price, graduation rate, median earnings |
| Field-of-study-level | School × 4-digit CIP × credential level | Median earnings 1yr/4yr post-grad, median federal debt |

**Known limitations:**
- Field-of-study uses 4-digit CIP (not 6-digit) — less granular
- Earnings measured only for Title IV federal aid recipients — not all graduates
- Does not capture private student loan debt
- Program title still not available — CIP code label only
- Data suppressed for small cohorts (privacy protection)

**Ingestion method:** API client `ingestion/scorecard/api_client.py`; 
supplement with bulk CSV for full institution coverage.

**Status:** Schema designed; ingestion pipeline planned for Phase 2.
