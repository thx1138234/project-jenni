# GASB / FASB Accounting Framework Crosswalk

## Why This Exists

Public universities follow **GASB** (Governmental Accounting Standards Board).
Private nonprofits follow **FASB** (Financial Accounting Standards Board).
The two frameworks use different terminology, different line items, and
different structural logic for financial statements.

IPEDS collects finance data through two separate survey instruments:
- **F1A**: For private nonprofit institutions (FASB)
- **F2**:  For public institutions (GASB)
- **F3**:  For private for-profit institutions (different again)

This database normalizes both into a single `ipeds_finance` table with
a `reporting_framework` column. This crosswalk documents how.

---

## Revenue Crosswalk

| Our Column | FASB Concept (F1A) | GASB Concept (F2) | Notes |
|---|---|---|---|
| `rev_tuition_fees` | Net tuition & fees (after discounts) | Tuition & fees (gross) | FASB nets out discounts; GASB often gross |
| `tuition_discounts` | Scholarship allowances/discounts | Not separately captured | FASB only |
| `rev_fed_approp` | N/A | Federal appropriations | Public schools only (e.g., land-grant formula) |
| `rev_state_approp` | N/A | State appropriations | Public schools only — major revenue source |
| `rev_local_approp` | N/A | Local appropriations | Community colleges primarily |
| `rev_fed_grants` | Federal grants & contracts | Federal grants & contracts | Comparable |
| `rev_state_grants` | State grants & contracts | State/local grants & contracts | Comparable |
| `rev_private_grants` | Private grants & contracts | Private grants & contracts | Comparable |
| `rev_private_gifts` | Contributions/gifts | Gifts | Comparable |
| `rev_investment` | Investment return (total) | Investment income | FASB includes unrealized gains; GASB may differ |
| `rev_auxiliary` | Auxiliary enterprises | Auxiliary enterprises | Comparable (housing, dining, etc.) |
| `rev_hospitals` | Hospital revenues | Hospital revenues | Only institutions with teaching hospitals |
| `rev_other` | Other revenues | Other revenues | Catch-all; use with caution for comparisons |
| `rev_total` | Total revenues & other additions | Total revenues | **Use with caution cross-sector** |

## Expense Crosswalk

| Our Column | FASB (F1A) | GASB (F2) | Notes |
|---|---|---|---|
| `exp_instruction` | Instruction | Instruction | Comparable |
| `exp_research` | Research | Research | Comparable |
| `exp_public_service` | Public service | Public service | Comparable |
| `exp_academic_support` | Academic support | Academic support | Comparable |
| `exp_student_services` | Student services | Student services | Comparable |
| `exp_institutional_support` | Institutional support | Institutional support | Comparable |
| `exp_net_scholarships` | Net student aid (grants - revenue) | Scholarships/fellowships | FASB nets against tuition revenue; watch for double-counting |
| `exp_aux_enterprises` | Auxiliary enterprises | Auxiliary enterprises | Comparable |
| `exp_hospitals` | Hospital services | Hospital services | Comparable |
| `exp_depreciation` | Included in functional expenses | Reported separately | GASB shows depreciation as separate line; FASB embeds it |
| `exp_total` | Total expenses | Total expenses | **Use with caution cross-sector** |

## Balance Sheet Crosswalk

| Our Column | FASB (F1A) | GASB (F2) | Notes |
|---|---|---|---|
| `assets_total` | Total assets | Total assets | Comparable |
| `assets_current` | Current assets | Current assets | Comparable |
| `assets_capital_net` | Property/plant/equipment net | Capital assets net | Comparable |
| `assets_endowment` | Long-term investments | Endowment investments | FASB includes all long-term investments; GASB may be narrower |
| `liab_total` | Total liabilities | Total liabilities | Comparable |
| `liab_current` | Current liabilities | Current liabilities | Comparable |
| `liab_longterm_debt` | Long-term debt | Noncurrent liabilities (debt portion) | Comparable |
| `netassets_total` | Total net assets | Total net position | **Label differs; concept comparable** |
| `netassets_unrestricted` | Unrestricted net assets | Unrestricted net position | Comparable |
| `netassets_restricted_temp` | Temporarily restricted net assets | N/A (FASB only) | No GASB equivalent |
| `netassets_restricted_perm` | Permanently restricted net assets | N/A (FASB only) | No GASB equivalent |
| `netassets_invested_capital` | N/A (FASB only) | Net invested in capital assets | No FASB equivalent |

---

## Cross-Sector Comparison Guidance

### Safe to Compare Across Sectors
- Instruction expenses per FTE student
- Research expenses (absolute and % of total)
- Student services expenses
- Tuition & fees revenue (with caveat on net vs gross)
- Graduate rates, enrollment trends (from other tables)

### Use With Caution
- Total revenue (FASB nets some items GASB reports gross)
- Total net assets (conceptually similar but structurally different)
- Endowment values (definitional differences in what's included)

### Do Not Compare Directly
- State appropriations (public only — creates structural asymmetry)
- Temporarily/permanently restricted net assets (FASB only)
- Net invested in capital assets (GASB only)
- Depreciation as separate line (GASB only)

---

## Query Recommendations

Always filter by `reporting_framework` when doing financial comparisons:

```sql
-- Correct: Compare only within same framework
SELECT institution_name, rev_tuition_fees, rev_total
FROM v_financial_summary
WHERE survey_year = 2023
  AND reporting_framework = 'FASB'    -- Private nonprofits only
ORDER BY rev_total DESC;

-- Correct: Instruction expense is comparable cross-sector
SELECT institution_name, control_label, inst_exp_per_fte
FROM v_financial_summary
WHERE survey_year = 2023
ORDER BY inst_exp_per_fte DESC;

-- Risky: Cross-sector total revenue comparison (use only with disclaimer)
SELECT institution_name, reporting_framework, rev_per_fte
FROM v_financial_summary
WHERE survey_year = 2023;
```

---

## NACUBO as a Supplementary Source

For endowment-specific data, NACUBO (National Association of College
and University Business Officers) publishes the annual Endowment Study
with consistent methodology across public and private institutions.
This is the gold standard for endowment comparisons — better than
what either IPEDS F1A or F2 provides. However, it is not fully public
(summary data is public; detailed data requires membership).

See `docs/roadmap.md` for notes on potential NACUBO integration.
