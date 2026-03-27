-- 990_governance_schema.sql
-- IRS Form 990 Part VI — Governance, Management, and Disclosure
--
-- One row per filing (PRIMARY KEY object_id).
-- All fields sourced from the IRS990 schedule (main form body).
-- Source: TEOS/IRSx only.
--
-- Field sources (IRS990 element names):
--   VotingMembersGoverningBodyCnt  → voting_members_governing_body
--   VotingMembersIndependentCnt    → voting_members_independent
--   TotalEmployeeCnt               → total_employees
--   GovernmentGrantsAmt            → government_grants_amt
--   FamilyOrBusinessRlnInd         → family_or_business_relationship
--   ConflictOfInterestPolicyInd    → conflict_of_interest_policy
--   WhistleblowerPolicyInd         → whistleblower_policy
--   DocumentRetentionPolicyInd     → document_retention_policy
--   MinutesOfGoverningBodyInd      → minutes_of_governing_body
--   Form990ProvidedToGvrnBodyInd   → form990_provided_to_board
--   FSAuditedInd / ConsolidatedAuditFinclStmtInd → financials_audited
--   AuditCommitteeInd              → audit_committee
--   FederalGrantAuditRequiredInd   → federal_grant_audit_required
--
-- Note: ElectionOfBoardMembersInd marks whether board elections are described
-- in org documents. ChangeToOrgDocumentsInd marks material amendments.

CREATE TABLE IF NOT EXISTS form990_governance (
    object_id                       TEXT    PRIMARY KEY,  -- FK → form990_filings.object_id
    ein                             TEXT    NOT NULL,
    fiscal_year_end                 INTEGER,

    -- Board composition (Part VI Section A)
    voting_members_governing_body   INTEGER,  -- total voting board members
    voting_members_independent      INTEGER,  -- independent voting members
    total_employees                 INTEGER,  -- TotalEmployeeCnt (W-2 headcount)

    -- Governance flags (Part VI Section A)
    family_or_business_relationship INTEGER,  -- 1=officer/director family/biz relationship exists
    change_to_org_documents         INTEGER,  -- 1=material change to articles/bylaws
    election_of_board_members       INTEGER,  -- 1=election described in org docs
    minutes_of_governing_body       INTEGER,  -- 1=minutes kept
    form990_provided_to_board       INTEGER,  -- 1=990 provided to board before filing

    -- Policy flags (Part VI Section B)
    conflict_of_interest_policy     INTEGER,  -- 1=written COI policy exists
    whistleblower_policy            INTEGER,  -- 1=written whistleblower policy exists
    document_retention_policy       INTEGER,  -- 1=written document retention policy exists

    -- Audit and compliance (Part VI Section C)
    financials_audited              INTEGER,  -- 1=financial statements audited by independent accountant
    audit_committee                 INTEGER,  -- 1=audit committee of governing body oversees audit
    federal_grant_audit_required    INTEGER,  -- 1=federal Single Audit Act required

    -- Revenue context (Part VII)
    government_grants_amt           INTEGER,  -- GovernmentGrantsAmt (federal/state grants in Part VIII)

    data_source                     TEXT    DEFAULT 'irsx',
    loaded_at                       TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_gov_ein   ON form990_governance (ein);
CREATE INDEX IF NOT EXISTS idx_gov_year  ON form990_governance (fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_gov_coi   ON form990_governance (conflict_of_interest_policy);
