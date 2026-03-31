#!/usr/bin/env python3
"""
scripts/log_backup.py
─────────────────────────────────────────────────────────────────────────────
Log an S3 backup event to jenni_query_log with query_type='system_backup'.
Called by scripts/s3_backup.sh after each sync attempt.
"""
import argparse
import os
import sys

# Make jenni package importable regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jenni.log import log_query


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--status", required=True, choices=["ok", "failed"])
    p.add_argument("--latency", type=int, default=0)
    p.add_argument("--dest", default="")
    p.add_argument("--error", default=None)
    args = p.parse_args()

    context = {
        "query":      f"S3 backup → {args.dest}",
        "query_type": "system_backup",
        "entities":   [],
        "accordion":  {"zone": "system"},
        "data_quality": {
            "completeness_pct": 100.0 if args.status == "ok" else None,
        },
    }

    qid = log_query(
        context=context,
        model_used="system",
        tokens_in=0,
        tokens_out=0,
        latency_ms=args.latency,
        error=args.error,
    )
    print(f"Logged: {qid}")


if __name__ == "__main__":
    main()
