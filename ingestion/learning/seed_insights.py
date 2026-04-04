"""
ingestion/learning/seed_insights.py
-------------------------------------
Validated trajectory insights seeded for the learning layer.

These are ready to load into jenni_institutional_insights when the learning layer
table is created. Do NOT create the table here — that is the learning layer build.

Each dict matches the expected jenni_institutional_insights schema:
    unitid            INTEGER
    institution_name  TEXT
    insight_text      TEXT
    evidence_tier     INTEGER   (1 = direct quantitative evidence)
    confidence        TEXT      ('high' | 'medium' | 'low')
    source_tables     TEXT      (comma-separated)
    fiscal_year_end   INTEGER   (most recent data year used)

Evidence tier 1: direct quantitative finding from pre-computed trajectory data.
Confidence 'medium' when the finding rests on a rolling window only (< full history).
"""

SEED_INSIGHTS: list[dict] = [
    {
        "unitid": 164924,
        "institution_name": "Boston College",
        "insight_text": (
            "Boston College tuition revenue follows a near-perfect exponential growth curve "
            "from 2008 to 2022 (R\u00b2=0.99, 14 observations), indicating sustained premium "
            "pricing execution consistent with their ACC athletics investment and selective "
            "admissions posture."
        ),
        "evidence_tier": 1,
        "confidence": "high",
        "source_tables": "institution_trajectories,institution_quant",
        "fiscal_year_end": 2023,
    },
    {
        "unitid": 166683,
        "institution_name": "Massachusetts Institute of Technology",
        "insight_text": (
            "MIT tuition revenue growth is decelerating along a logistic S-curve (R\u00b2=0.96), "
            "consistent with a deliberate enrollment constraint strategy and endowment-funded "
            "financial aid model rather than revenue maximization."
        ),
        "evidence_tier": 1,
        "confidence": "high",
        "source_tables": "institution_trajectories,institution_quant",
        "fiscal_year_end": 2023,
    },
    {
        "unitid": 167358,
        "institution_name": "Northeastern University",
        "insight_text": (
            "Northeastern's enrollment trajectory shows a structural break in 2012 followed "
            "by exponential growth (rolling 10yr R\u00b2=0.79), consistent with the launch of "
            "their global campus expansion strategy. Pre-2012 and post-2012 are financially "
            "distinct institutional periods."
        ),
        "evidence_tier": 1,
        "confidence": "medium",
        "source_tables": "institution_trajectories,ipeds_ef",
        "fiscal_year_end": 2022,
    },
]
