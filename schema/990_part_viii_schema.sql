-- 990_part_viii_schema.sql
-- IRS Form 990 Part VIII — Statement of Revenue (Tier 1)
--
-- One row per TEOS/IRSx filing. NULL for ProPublica rows by design —
-- ProPublica API does not expose Part VIII sub-line detail.
--
-- Tier 1 fields (granular sub-lines not captured in form990_filings):
--   Line 1e — Government grants (GovernmentGrantsAmt)
--   Line 1f — All other contributions (AllOtherContributionsAmt)
--   Lines 2a–2e — Program service revenue by program (up to 5 named programs)
--                 Each slot: revenue amount + program description
--
-- form990_filings already captures the Part VIII aggregate totals:
--   contributions_grants (Line 1h), program_service_revenue (Line 2g),
--   investment_income (Line 3), net_gain_investments (Line 7),
--   other_revenue (Part I aggregate), total_revenue (Line 12).
-- This table adds the sub-line detail not captured there.

CREATE TABLE IF NOT EXISTS form990_part_viii (
    object_id                   TEXT    PRIMARY KEY,  -- FK → form990_filings.object_id
    ein                         TEXT    NOT NULL,
    fiscal_year_end             INTEGER,

    -- ── Line 1 — Contributions, Gifts, Grants ─────────────────────────────
    -- Line 1e: Government grants (federal, state, local)
    govt_grants_amt             INTEGER,
    -- Line 1f: All other contributions, gifts, grants, and similar amounts
    all_other_contributions_amt INTEGER,

    -- ── Lines 2a–2e — Program Service Revenue by Program ──────────────────
    -- The 990 allows up to 7 named program revenue lines (2a–2g).
    -- We capture the first 5 (covers >95% of institutions; 2f–2g are rare).
    -- Amounts are TotalRevenueColumnAmt (col A = related + unrelated + excluded).
    -- Descriptions are institution-reported free text.

    -- Line 2a
    prog_svc_revenue_2a         INTEGER,
    prog_svc_desc_2a            TEXT,
    -- Line 2b
    prog_svc_revenue_2b         INTEGER,
    prog_svc_desc_2b            TEXT,
    -- Line 2c
    prog_svc_revenue_2c         INTEGER,
    prog_svc_desc_2c            TEXT,
    -- Line 2d
    prog_svc_revenue_2d         INTEGER,
    prog_svc_desc_2d            TEXT,
    -- Line 2e
    prog_svc_revenue_2e         INTEGER,
    prog_svc_desc_2e            TEXT,

    -- Metadata
    loaded_at                   TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_partviii_ein       ON form990_part_viii (ein);
CREATE INDEX IF NOT EXISTS idx_partviii_year      ON form990_part_viii (fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_partviii_ein_year  ON form990_part_viii (ein, fiscal_year_end);
