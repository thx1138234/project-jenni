# Fiscal Year Conventions

One of the trickier aspects of this database is that Form 990, IPEDS, EADA,
and College Scorecard all use different year reference conventions.
This document defines how we standardize.

---

## The Problem

| Source | Year Reference | Example |
|---|---|---|
| Form 990 | "Tax Year" = fiscal year *start* | FY July 2022–June 2023 filed as "Tax Year 2022" |
| IPEDS | Academic Year = fall start through spring end | "AY 2022–23" |
| EADA | Award year = academic year | "2022–23" |
| College Scorecard | Award year same as IPEDS | "2022–23" |

This means a single institution's data for the same real-world period can appear
as "2022" in 990 data and "2022–23" in IPEDS data — for the *same* fiscal year.

---

## Our Standard: Fiscal Year End

**This database uses the fiscal year END calendar year as the canonical year label.**

| Fiscal Period | Our Label | 990 Label | IPEDS Label |
|---|---|---|---|
| July 1, 2022 – June 30, 2023 | **FY2023** | Tax Year 2022 | AY 2022–23 |
| July 1, 2021 – June 30, 2022 | **FY2022** | Tax Year 2021 | AY 2021–22 |

All year fields in the database use this convention. Ingestion scripts
normalize source labels to this standard on load.

---

## Institutions With Non-June Fiscal Year Ends

A minority of institutions use fiscal years not ending June 30.
These are handled case-by-case in the institution_master table
via the `fiscal_year_end_month` field.

| Institution Type | Common FY End |
|---|---|
| Most private universities | June 30 |
| Some universities (e.g., Harvard) | June 30 |
| Some public institutions | Varies — often August 31 |

---

## Joining 990 to IPEDS

When joining 990 financial data to IPEDS operational data, use:

```sql
-- Match FY2023 990 data to AY2022-23 IPEDS data
SELECT *
FROM form990_financials f
JOIN ipeds_enrollment e
  ON f.unitid = e.unitid
  AND f.fiscal_year_end = 2023
  AND e.academic_year = '2022-23'
```

The `cross_source_joins.sql` query file handles this alignment automatically.
