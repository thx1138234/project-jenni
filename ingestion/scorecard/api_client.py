#!/usr/bin/env python3
"""
ingestion/scorecard/api_client.py
----------------------------------
College Scorecard API client.

Loads SCORECARD_API_KEY from .env via python-dotenv.
Queries the College Scorecard API (api.data.gov) for institution-level data
by UNITID (the IPEDS id field).

Usage:
    python3 ingestion/scorecard/api_client.py --unitid 164580
    python3 ingestion/scorecard/api_client.py --unitid 164580 166027 166683

Environment:
    SCORECARD_API_KEY — required; set in .env (never commit .env)
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env from project root (two levels up from this file)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.data.gov/ed/collegescorecard/v1/schools.json"

# Fields to fetch per institution.
# Grouped by category for readability; extend as the schema grows.
DEFAULT_FIELDS = ",".join([
    # Identity
    "id",
    "school.name",
    "school.city",
    "school.state",
    "school.ownership",
    "school.zip",
    "school.ope_id",
    # Carnegie skipped — already in institution_master from IPEDS HD
    # Enrollment
    "latest.student.size",
    "latest.student.enrollment.undergrad_12_month",
    "latest.student.enrollment.grad_12_month",
    # Cost — avg net price split by control type (public vs private)
    "latest.cost.tuition.in_state",
    "latest.cost.tuition.out_of_state",
    "latest.cost.avg_net_price.public",
    "latest.cost.avg_net_price.private",
    # Net price by income band — public institutions
    # Field names confirmed from data dictionary; 'consumer' alias omits upper two bands
    "latest.cost.net_price.public.by_income_level.0-30000",
    "latest.cost.net_price.public.by_income_level.30001-48000",
    "latest.cost.net_price.public.by_income_level.48001-75000",
    "latest.cost.net_price.public.by_income_level.75001-110000",
    "latest.cost.net_price.public.by_income_level.110001-plus",
    # Net price by income band — private NP and for-profit institutions
    "latest.cost.net_price.private.by_income_level.0-30000",
    "latest.cost.net_price.private.by_income_level.30001-48000",
    "latest.cost.net_price.private.by_income_level.48001-75000",
    "latest.cost.net_price.private.by_income_level.75001-110000",
    "latest.cost.net_price.private.by_income_level.110001-plus",
    # Aid
    "latest.aid.pell_grant_rate",
    "latest.aid.federal_loan_rate",
    "latest.aid.median_debt.completers.overall",
    # Withdrawals debt omitted — consistently NULL across all institutions
    # Outcomes
    "latest.completion.completion_rate_4yr_150nt",
    "latest.completion.completion_rate_less_than_4yr_150nt",
    "latest.earnings.6_yrs_after_entry.median",
    "latest.earnings.10_yrs_after_entry.median",
    "latest.repayment.3_yr_repayment.overall",
])


class ScorecardClient:
    """
    Thin wrapper around the College Scorecard API.

    Rate limit: 1,000 requests/hour per IP. Each call to get_institution()
    is one request. Batch via get_institutions() to fetch multiple UNITIDs
    in a single request (up to ~100 per call).
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("SCORECARD_API_KEY")
        if not self.api_key:
            raise EnvironmentError(
                "SCORECARD_API_KEY not set. Add it to .env or pass api_key= directly."
            )
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, params: dict) -> dict:
        params["api_key"] = self.api_key
        resp = self.session.get(BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_institution(self, unitid: int, fields: str = DEFAULT_FIELDS) -> dict | None:
        """
        Fetch a single institution by UNITID.
        Returns the result dict, or None if not found.
        """
        data = self._get({"id": unitid, "fields": fields})
        results = data.get("results", [])
        return results[0] if results else None

    def get_institutions(
        self,
        unitids: list[int],
        fields: str = DEFAULT_FIELDS,
        page_size: int = 100,
        sleep_between: float = 0.1,
    ) -> list[dict]:
        """
        Fetch multiple institutions by UNITID list.
        Batches into pages of page_size to stay within URL length limits.
        Returns list of result dicts (institutions not found are silently omitted).
        """
        results = []
        for i in range(0, len(unitids), page_size):
            batch = unitids[i : i + page_size]
            id_filter = "&".join(f"id={uid}" for uid in batch)
            data = self._get({"fields": fields, "per_page": page_size, **{f"id": batch[0]}})
            # The API supports repeated id= params; build URL manually for batches > 1
            if len(batch) > 1:
                params = {"fields": fields, "per_page": page_size, "api_key": self.api_key}
                url = BASE_URL + "?" + "&".join(
                    [f"{k}={v}" for k, v in params.items()]
                    + [f"id={uid}" for uid in batch]
                )
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            results.extend(data.get("results", []))
            if i + page_size < len(unitids):
                time.sleep(sleep_between)
        return results


def _fmt(val):
    if val is None:
        return "NULL"
    if isinstance(val, float):
        return f"{val:.4f}"
    if isinstance(val, int) and val > 1000:
        return f"{val:,}"
    return str(val)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Query College Scorecard by UNITID")
    parser.add_argument("--unitid", type=int, nargs="+", required=True,
                        help="IPEDS UNITID(s) to fetch")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    client = ScorecardClient()

    for uid in args.unitid:
        result = client.get_institution(uid)
        if result is None:
            print(f"UNITID {uid}: not found in College Scorecard")
            continue
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\n{'='*60}")
            print(f"  {result.get('school.name', '?')}  (UNITID {uid})")
            print(f"  {result.get('school.city', '?')}, {result.get('school.state', '?')}")
            print(f"{'='*60}")
            for k, v in sorted(result.items()):
                if k not in ("school.name", "school.city", "school.state", "id"):
                    print(f"  {k:<50} {_fmt(v)}")


if __name__ == "__main__":
    main()
