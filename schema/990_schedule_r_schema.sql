-- 990_schedule_r_schema.sql
-- IRS Form 990 Schedule R — Related Organizations and Unrelated Partnerships
--
-- Two tables:
--
--   form990_related_orgs:         one row per related entity per filing
--   form990_related_transactions: one row per dollar transaction with a
--                                 related org per filing
--
-- Relationship type values:
--   'disregarded'   IdDisregardedEntitiesGrp    (wholly-owned LLCs, etc.)
--   'tax_exempt'    IdRelatedTaxExemptOrgGrp    (related 501(c) orgs)
--   'partnership'   IdRelatedOrgTxblPartnershipGrp
--   'corp_trust'    IdRelatedOrgTxblCorpTrGrp
--
-- Source: TEOS/IRSx only. ProPublica API does not expose Schedule R.
-- One filing may have hundreds of related orgs (see Harvard: 400+ entities).

CREATE TABLE IF NOT EXISTS form990_related_orgs (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id                   TEXT    NOT NULL,    -- FK → form990_filings.object_id
    ein                         TEXT    NOT NULL,    -- filing institution EIN
    fiscal_year_end             INTEGER,

    -- Related entity identity
    org_name                    TEXT,               -- BusinessNameLine1Txt
    org_ein                     TEXT,               -- EIN of related org (NULL if foreign/unavailable)
    relationship_type           TEXT    NOT NULL,    -- disregarded | tax_exempt | partnership | corp_trust
    primary_activities          TEXT,               -- PrimaryActivitiesTxt
    legal_domicile              TEXT,               -- state abbr or country code
    direct_controlling_entity   TEXT,               -- DirectControllingEntityName

    -- Ownership/control
    controlled_org_ind          INTEGER,            -- 1=controlled, 0=not controlled (NULL if not reported)

    -- Financial summary (available for some relationship types)
    total_income                INTEGER,            -- TotalIncomeAmt (disregarded, partnerships)
    eoy_assets                  INTEGER,            -- EndOfYearAssetsAmt (disregarded)
    share_of_total_income       INTEGER,            -- ShareOfTotalIncomeAmt (partnerships, corp/trust)
    share_of_eoy_assets         INTEGER,            -- ShareOfEOYAssetsAmt (partnerships, corp/trust)

    data_source                 TEXT    DEFAULT 'irsx',
    loaded_at                   TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rorg_object   ON form990_related_orgs (object_id);
CREATE INDEX IF NOT EXISTS idx_rorg_ein      ON form990_related_orgs (ein);
CREATE INDEX IF NOT EXISTS idx_rorg_year     ON form990_related_orgs (fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_rorg_type     ON form990_related_orgs (relationship_type);
CREATE INDEX IF NOT EXISTS idx_rorg_org_ein  ON form990_related_orgs (org_ein);


-- ---------------------------------------------------------------------------
-- Related-org transactions (Schedule R Part V)
-- ---------------------------------------------------------------------------
-- One row per transaction line reported.
-- TransactionTypeTxt values from IRS: A=receipt of interest/annuities/rents/royalties,
-- B=gift/grant to other org, C=gift/grant from other org, D=loans/guarantees to,
-- E=loans/guarantees from, F=dividends from, G=sale of assets to, H=purchase from,
-- I=exchange of assets, J=lease of facilities to, K=lease from, L=performance of
-- services for, M=performance of services by, N=sharing of facilities, O=shared
-- employees, P=reimbursement paid to, Q=reimbursement paid by, R=transfer to,
-- S=transfer from other org.

CREATE TABLE IF NOT EXISTS form990_related_transactions (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id                   TEXT    NOT NULL,
    ein                         TEXT    NOT NULL,
    fiscal_year_end             INTEGER,

    other_org_name              TEXT,               -- OtherOrganizationName
    transaction_type            TEXT,               -- single letter code (A-S)
    amount                      INTEGER,            -- InvolvedAmt
    amount_method               TEXT,               -- MethodOfAmountDeterminationTxt

    data_source                 TEXT    DEFAULT 'irsx',
    loaded_at                   TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rtx_object ON form990_related_transactions (object_id);
CREATE INDEX IF NOT EXISTS idx_rtx_ein    ON form990_related_transactions (ein);
CREATE INDEX IF NOT EXISTS idx_rtx_year   ON form990_related_transactions (fiscal_year_end);
