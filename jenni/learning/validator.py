"""
jenni/learning/validator.py
----------------------------
Five-check validation pipeline for candidate insights.
Fail-fast: returns on first rejection with reason logged.

Validation hierarchy:
  Tier 1 — direct federal data (990, IPEDS, EADA, Scorecard, trajectories)
  Tier 2 — cross-validated inference (2+ independent sources)
  Tier 3 — search-verified (web confirmation of a Tier 2 claim)
  Tier 4 — unverified assertion  → REJECTED, never stored
  Tier 5 — speculation           → REJECTED, never stored
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    approved: bool
    confidence: str | None = None   # 'high', 'medium', 'low'
    evidence_tier: int | None = None
    rejection_reason: str | None = None


class JENNIInsightValidator:

    DATA_DOMAIN_KEYWORDS = {
        'enrollment', 'revenue', 'expense', 'endowment',
        'tuition', 'yield', 'admit', 'graduation',
        'compensation', 'athletics', 'net price',
        'debt', 'assets', 'liabilities', 'spending rate',
        'peer', 'percentile', 'trend', 'carnegie',
        'operating margin', 'tuition dependency',
        'trajectory', 'exponential', 'logistic', 'plateau',
        'structural break', 'regime',
    }

    PERSONAL_INFO_SIGNALS = {
        'as cfo', 'as president', 'i work at',
        'my institution', 'my school', 'told me',
        'i heard', 'rumor', 'gossip',
    }

    TIER1_SOURCES = {
        'form990_filings', 'institution_quant',
        'ipeds_ef', 'ipeds_finance', 'ipeds_adm',
        'form990_schedule_d', 'form990_part_ix',
        'form990_compensation', 'eada_instlevel',
        'institution_trajectories', 'scorecard_institution',
    }

    def validate(self, proposed: dict, context: dict) -> ValidationResult:
        # Check 1 — institutional anchor required
        if not proposed.get('unitid'):
            return ValidationResult(
                approved=False,
                rejection_reason='No institutional anchor — '
                                 'insight must reference a specific institution',
            )

        # Check 2 — data domain check
        text = proposed.get('insight_text', '').lower()
        if not any(kw in text for kw in self.DATA_DOMAIN_KEYWORDS):
            return ValidationResult(
                approved=False,
                rejection_reason='Outside JENNI data domain — '
                                 'no financial/enrollment/institutional keywords',
            )

        # Check 3 — personal information filter
        if any(sig in text for sig in self.PERSONAL_INFO_SIGNALS):
            return ValidationResult(
                approved=False,
                rejection_reason='Contains personal information '
                                 'or unverifiable human assertion',
            )

        # Check 4 — evidence tier assessment
        source_tables = proposed.get('source_tables', '')
        tier = self._assess_tier(source_tables, context)
        if tier >= 4:
            return ValidationResult(
                approved=False,
                rejection_reason=f'Evidence tier {tier} — '
                                 f'below minimum threshold for storage',
            )

        # Check 5 — Tier 1 contradiction check
        contradiction = self._check_tier1_contradiction(proposed, context)
        if contradiction:
            return ValidationResult(
                approved=False,
                rejection_reason=f'Contradicts federal data: {contradiction}',
            )

        confidence = self._tier_to_confidence(tier)
        return ValidationResult(
            approved=True,
            confidence=confidence,
            evidence_tier=tier,
        )

    def _assess_tier(self, source_tables: str, context: dict) -> int:
        sources = {s.strip() for s in source_tables.split(',') if s.strip()}
        if sources & self.TIER1_SOURCES:
            return 1
        if len(sources) >= 2:
            return 2
        if context.get('web_verified'):
            return 3
        return 4

    def _check_tier1_contradiction(
        self, proposed: dict, context: dict
    ) -> str | None:
        # Placeholder for cross-checking claims against institution_quant values.
        # Phase 2: compare numeric claims in insight_text against quant data.
        return None

    def _tier_to_confidence(self, tier: int) -> str:
        return {1: 'high', 2: 'high', 3: 'medium'}.get(tier, 'low')
