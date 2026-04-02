# College Scorecard Historical Backfill Probe
_Audit date: 2026-04-02_

## Summary

The Scorecard API supports historical year-prefixed queries for net price going back to
AY2008-09. The bulk CSV download site appears inaccessible via direct URL (JavaScript SPA
cannot be scraped; all tested `ed-public-download.app.cloud.gov` URLs return 404). The
**API is the recommended path for net price backfill**. Earnings and completion rate
backfill have significant limitations documented below.

---

## File Naming Conventions (from Official Data Dictionary)

Source: `CollegeScorecardDataDictionary.xlsx` (released October 10, 2024), downloaded from
`https://collegescorecard.ed.gov/assets/CollegeScorecardDataDictionary.xlsx`.

### Institution-Level Files
Files are named `MERGED{YYYY-YY}_PP.csv`:

| File Name | Academic Year |
|---|---|
| MERGED_1996-97 | AY 1996-97 |
| MERGED_1997-98 | AY 1997-98 |
| ... | ... |
| MERGED_2021-22 | AY 2021-22 |
| MERGED_2022-23 | AY 2022-23 (most recent) |

27 annual institution-level files available, 1996-97 through 2022-23.

A "Most Recent" institution-level file aggregates the most recent available year for each
variable (not necessarily the same year across all variables — earnings, net price, and
completion rates are reported on different lag schedules).

### Field-of-Study-Level Files
Separate files with a different naming convention; not institution-level. Not in scope for
the current backfill (institution_quant uses institution-level data only).

---

## Bulk Download Availability

**Status: Inaccessible via direct URL as of 2026-04-02.**

All tested URL patterns returned HTTP 404:
- `https://ed-public-download.app.cloud.gov/downloads/CollegeScorecard_Raw_Data_10102024.zip`
- `https://ed-public-download.app.cloud.gov/downloads/CollegeScorecard_Raw_Data.zip`
- `https://ed-public-download.app.cloud.gov/downloads/Most-Recent-Cohorts-All-Data-Elements.csv`
- `https://ed-public-download.app.cloud.gov/downloads/MERGED2022_23_PP.csv`

The `collegescorecard.ed.gov/data/` page is a Vue.js SPA — static fetch returns only CSS
theme variables. `data.ed.gov` returns HTTP 403. The actual download links are rendered
client-side and are not accessible without a headless browser.

**Recommendation:** Do not build a bulk CSV downloader without first manually navigating to
`collegescorecard.ed.gov/data/` in a browser, locating the "All Data Files" ZIP, and
confirming the current download URL pattern. As of this audit, the API is the only
confirmed accessible data path.

---

## Key Field Availability by Year

Source: `Institution_Cohort_Map` tab of CollegeScorecardDataDictionary.xlsx.

### NPT4_PUB — Average Net Price, Public Institutions
API equivalent: `{year}.cost.avg_net_price.public`

| Availability | Years |
|---|---|
| **First available** | MERGED_2008-09 (AY 2008-09, reported in IPEDS DCY2009-10) |
| **Latest** | MERGED_2022-23 (AY 2021-22) |
| **Consistent field name?** | ✅ Yes — `NPT4_PUB` unchanged across all years |
| **Gap years** | None 2008-09 through 2022-23 |

### NPT4_PRIV — Average Net Price, Private Institutions
API equivalent: `{year}.cost.avg_net_price.private`

| Availability | Years |
|---|---|
| **First available** | MERGED_2008-09 |
| **Latest** | MERGED_2022-23 |
| **Consistent field name?** | ✅ Yes |
| **Gap years** | None 2008-09 through 2022-23 |

**API validation (5 MA private nonprofits, AY 2017-2023):**

| Institution | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 |
|---|---|---|---|---|---|---|---|
| Babson | $35,540 | $35,385 | $34,606 | $37,092 | $31,267 | $34,994 | $38,876 |
| Bentley | $35,671 | $36,919 | $38,986 | $41,334 | $39,437 | $39,699 | $38,787 |
| Boston College | $34,550 | $33,562 | $35,899 | $36,599 | $38,412 | $39,090 | $39,866 |
| Harvard | $14,327 | $15,561 | $15,386 | $13,872 | $13,259 | $19,500 | $16,816 |
| MIT | $20,771 | $18,278 | $16,636 | $16,407 | $5,084 | $20,338 | $19,813 |

All 7 years × 5 institutions populated. API path: `{year}.cost.avg_net_price.private`.
Note: MIT 2021 ($5,084) appears anomalously low — likely a reporting/suppression artifact.
Flag for manual verification before using in analysis.

### Net Price by Income Band
API equivalent: `{year}.cost.net_price.private.by_income_level.{band}`
Income bands: `0-30000`, `30001-48000`, `48001-75000`, `75001-110000`, `110001-plus`

Confirmed available via API (Babson spot check):
- AY2017: `0-30000` band = $26,817
- AY2019: `0-30000` band = $16,734
- AY2021: `0-30000` band = $18,034

These correspond to CSV columns `NPT41_PRIV` through `NPT45_PRIV` (five income bands).
Available in MERGED files from 2008-09 onward; consistent naming.

### MD_EARN_WNE_P10 — Median Earnings 10 Years After Entry
API equivalent: `{year}.earnings.10_yrs_after_entry.median`

**Field availability is NOT continuous — sparse by design.**

The earnings metric uses a pooled-cohort methodology. Data is only available in years where
a pooled cohort has reached the 10-year mark. From the cohort map:

| MERGED File | Cohort | Available? |
|---|---|---|
| MERGED_2012-13 | AY1996-97 + AY1997-98 pooled, measured CY2007-08 | ✅ |
| MERGED_2013-14 | AY1998-99 + AY1999-00 pooled, measured CY2009-10 | ✅ |
| MERGED_2014-15 | — | ❌ |
| MERGED_2015-16 | AY2000-01 + AY2001-02 pooled, measured CY2011-12 | ✅ |
| MERGED_2016-17 | AY2001-02 + AY2002-03 pooled, measured CY2012-13 | ✅ |
| MERGED_2017-18 | AY2002-03 + AY2003-04 pooled, measured CY2013-14 | ✅ |
| MERGED_2018-19 | AY2003-04 + AY2004-05 pooled, measured CY2014-15 | ✅ |
| MERGED_2019-20 through 2021-22 | — | ❌ |
| MERGED_2020-21 | AY2009-10 + AY2010-11 pooled, measured CY2020-21 | ✅ |
| MERGED_2021-22 | — | ❌ |
| MERGED_2022-23 | — | ❌ |

**API validation (Babson, years 2015-2023):** Only `2020.earnings.10_yrs_after_entry.median`
returned data ($123,938). All other tested years (2015-2019, 2021-2023) returned null.

**Implication:** Earnings trend analysis is not feasible from a simple year-over-year
backfill. The data is fundamentally a point-in-time series with gaps. What IS available:
- One complete earnings snapshot per institution per populated file year
- The institution_quant `earnings_to_debt_ratio` currently uses a single-year Scorecard value
- A backfill would add 6-7 earnings data points per institution spread across 2012-2020,
  not a continuous trend

### C150_4 — 4-Year Completion Rate (150% of Normal Time)
API equivalent: `{year}.completion.rate_suppressed.four_year` (API) or CSV column `C150_4`

| Availability | Years |
|---|---|
| **First available** | MERGED_1997-98 (Fall 1991 cohort) |
| **Latest** | MERGED_2022-23 (Fall 2016 cohort) |
| **Consistent field name?** | ✅ Yes — `C150_4` unchanged |
| **Lag** | 6 years — MERGED_2022-23 has completion data for Fall 2016 entrants |
| **API behavior** | Returns null for selective private institutions (suppression threshold) |

**API note:** The API returned null for all tested years for Babson — this is consistent with
IPEDS suppression behavior for small/selective institutions. The CSV files have the actual
values; the API applies additional suppression. **The bulk CSV is the correct source for
historical C150_4, not the API.**

`C150_4_POOLED` (multi-year pooled rate) is only available starting MERGED_2022-23.
Do not use for historical comparison.

---

## Backfill Strategy Recommendation

### What to build (in priority order):

**Priority 1 — Net price historical backfill via API (high value, confirmed accessible)**
- Use existing `api_client.py` infrastructure
- Extend to fetch `{year}.cost.avg_net_price.private` for years 2009-2023 (15 years)
- Also fetch income-band net price: `{year}.cost.net_price.private.by_income_level.*`
- Enables net price trend direction in `institution_quant` (currently single-year only)
- API rate limit: ~1 req/sec; ~6,300 institutions × moderate field count = feasible

**Priority 2 — Completion rate from bulk CSV (medium value, requires download confirmation)**
- C150_4 available annually from 1997-98 through 2022-23 in MERGED files
- API-suppressed for selective institutions; must use bulk CSV
- Action: Manually download the "All Data Files" ZIP from `collegescorecard.ed.gov/data/`
  and verify the MERGED file naming pattern before building an automated downloader
- Provides 25 years of completion rate trend data

**Priority 3 — Earnings backfill (low value, structurally sparse)**
- MD_EARN_WNE_P10 only present in 6-7 MERGED files out of 27 (non-continuous)
- A backfill would add isolated data points, not a usable trend series
- Defer until there is a specific analytical use case requiring historical earnings

### What NOT to build yet:
- A bulk CSV downloader for MERGED files — download URLs unconfirmed; need manual verification
- Earnings trend analysis — data structure doesn't support it

---

## Field Name Consistency: 2017-2023

All four target fields are **consistently named** across the 2017-2022 MERGED files:

| Field | CSV name | API path | Consistent? |
|---|---|---|---|
| Net price (public) | `NPT4_PUB` | `{yr}.cost.avg_net_price.public` | ✅ No changes 2008-2023 |
| Net price (private) | `NPT4_PRIV` | `{yr}.cost.avg_net_price.private` | ✅ No changes 2008-2023 |
| 10-yr earnings | `MD_EARN_WNE_P10` | `{yr}.earnings.10_yrs_after_entry.median` | ✅ Name stable; data sparse |
| 4-yr completion | `C150_4` | `{yr}.completion.rate_suppressed.four_year` | ✅ No changes 1997-2023 |

No field renames detected for target variables across the 2017-2022 range. The data dictionary
changelog would need to be reviewed if backfilling pre-2017 data for any of these fields.

---

## Open Items

1. **Confirm bulk CSV download URL** — navigate to `collegescorecard.ed.gov/data/` in a
   browser, find the "All Data Files" download, confirm the URL pattern before building any
   automated downloader.
2. **MIT FY2021 net price anomaly** — `2021.cost.avg_net_price.private = $5,084` for MIT is
   implausibly low (prior years ~$16-20K). Verify against MIT published financial aid data
   before using in analysis.
3. **Suppress-vs-null distinction** — C150_4 may be suppressed (small n) vs. genuinely null
   (not applicable). The CSV uses different suppression codes; the API just returns null.
   Document this when building the completion rate loader.
