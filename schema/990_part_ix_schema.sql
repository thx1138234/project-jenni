-- 990_part_ix_schema.sql
-- IRS Form 990 Part IX — Statement of Functional Expenses (Phase A)
--
-- One row per TEOS/IRSx filing. NULL for ProPublica rows by design —
-- ProPublica API does not expose functional column breakdowns.
--
-- Columns B/C/D = Program Services / Management & General / Fundraising.
-- Column A totals live in form990_filings.total_functional_expenses (join on object_id).
--
-- Phase A fields (column breakdowns + key line items):
--   Line 25 — Total functional expenses (cols B, C, D)
--   Line 12 — Advertising and promotion (cols B, C, D)
--   Line 14 — Information technology (cols B, C, D)
--   Line 11e — Professional fundraising service fees (TotalAmt)
--   Line 11f — Investment management fees (TotalAmt)
--
-- Phase B (full line item detail) deferred — to be added after intelligence layer.
--
-- Calculated ratios stored at load time (require form990_filings join):
--   prog_services_pct      = total_prog_services / total_functional_expenses
--   overhead_ratio         = (total_mgmt_general + total_fundraising) / total_functional_expenses
--   fundraising_efficiency = total_fundraising / contributions_grants

CREATE TABLE IF NOT EXISTS form990_part_ix (
    object_id               TEXT    PRIMARY KEY,  -- FK → form990_filings.object_id
    ein                     TEXT    NOT NULL,
    fiscal_year_end         INTEGER,

    -- Line 25 — Total functional expenses by column
    total_prog_services     INTEGER,              -- col B: program services
    total_mgmt_general      INTEGER,              -- col C: management & general
    total_fundraising_exp   INTEGER,              -- col D: fundraising

    -- Line 12 — Advertising and promotion
    advertising_prog        INTEGER,              -- col B
    advertising_mgmt        INTEGER,              -- col C
    advertising_fundraising INTEGER,              -- col D

    -- Line 14 — Information technology
    it_prog                 INTEGER,              -- col B
    it_mgmt                 INTEGER,              -- col C
    it_fundraising          INTEGER,              -- col D

    -- Line 11e — Professional fundraising service fees (total; predominantly col D)
    prof_fundraising_fees   INTEGER,

    -- Line 11f — Investment management fees (total; predominantly col C)
    invest_mgmt_fees        INTEGER,

    -- Calculated ratios (NULL if denominator is NULL or zero)
    prog_services_pct       REAL,   -- total_prog_services / total_functional_expenses
    overhead_ratio          REAL,   -- (total_mgmt_general + total_fundraising_exp) / total_functional_expenses
    fundraising_efficiency  REAL,   -- total_fundraising_exp / contributions_grants

    -- Metadata
    loaded_at               TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_partix_ein       ON form990_part_ix (ein);
CREATE INDEX IF NOT EXISTS idx_partix_year      ON form990_part_ix (fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_partix_ein_year  ON form990_part_ix (ein, fiscal_year_end);
