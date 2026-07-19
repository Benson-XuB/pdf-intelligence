#!/usr/bin/env python3
"""批量校验入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.batch_service import BatchVerificationService

DEFAULT_JOBS = [
    ("US", "AAPL"),
    ("US", "MSFT"),
    ("US", "GOOGL"),
    ("US", "AMZN"),
    ("US", "META"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch verified financials")
    parser.add_argument("--periods", type=int, default=3)
    parser.add_argument(
        "--jobs",
        nargs="+",
        default=[f"{m}:{t}" for m, t in DEFAULT_JOBS],
        help="格式 MARKET:TICKER，如 US:AAPL HK:0700",
    )
    args = parser.parse_args()

    jobs = []
    for raw in args.jobs:
        market, ticker = raw.split(":", 1)
        jobs.append((market, ticker))

    report = BatchVerificationService().run(jobs=jobs, periods=args.periods)
    payload = {
        "success_count": report.success_count,
        "production_ready_count": report.production_ready_count,
        "avg_trust_score": report.avg_trust_score,
        "portfolio_excel_path": report.portfolio_excel_path,
        "items": [
            {
                "market": i.market,
                "ticker": i.ticker,
                "success": i.success,
                "trust_score": i.trust_score,
                "verification_rate": i.verification_rate,
                "production_ready": i.production_ready,
                "errors": i.errors,
            }
            for i in report.items
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
