#!/usr/bin/env python3
"""港股 verified benchmark（需先在 financial_hk/ 放置 PDF）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.markets.hk.financials_service import HkFinancialsService
from tests.benchmark.financial_hk.corpus import (
    CORPUS_HK,
    available_entries,
    missing_entries,
)

REPORT_PATH = ROOT / "tests/benchmark/financial_hk/verified_accuracy_report.json"


def run_benchmark(periods: int = 3) -> dict:
    available = available_entries()
    missing = missing_entries()
    companies = []

    for entry in available:
        service = HkFinancialsService()
        result = service.build_verified_financials(
            ticker=entry["id"],
            periods=periods,
            document_path=entry["pdf"],
            export_excel=False,
        )
        companies.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "pdf": entry["pdf"],
                "cross_list_us": entry.get("cross_list_us") or result.cross_list_ticker,
                "verification_rate": result.verification_rate,
                "trust_score": result.trust_score,
                "pdf_coverage_rate": result.pdf_coverage_rate,
                "production_ready": result.is_production_ready,
                "recon_mismatch": result.reconciliation.mismatch_count,
                "errors": result.errors,
            }
        )

    overall_verify = (
        sum(c["verification_rate"] for c in companies) / len(companies) if companies else 0.0
    )
    overall_trust = sum(c["trust_score"] for c in companies) / len(companies) if companies else 0.0
    overall_pdf_coverage = (
        sum(c["pdf_coverage_rate"] for c in companies) / len(companies) if companies else 0.0
    )

    return {
        "pipeline": "verified_financials (HK PDF × US XBRL cross-list)",
        "template_count": len(CORPUS_HK),
        "tested_count": len(companies),
        "missing_templates": [e["pdf"] for e in missing],
        "overall_verification_rate": round(overall_verify, 4),
        "overall_trust_score": round(overall_trust, 4),
        "overall_pdf_coverage_rate": round(overall_pdf_coverage, 4),
        "companies": companies,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="港股 verified benchmark")
    parser.add_argument("--list", action="store_true", help="仅列出语料状态")
    parser.add_argument("--periods", type=int, default=3)
    args = parser.parse_args()

    if args.list:
        print(f"已就绪: {len(available_entries())}/{len(CORPUS_HK)}")
        for e in CORPUS_HK:
            mark = "✅" if Path(e["pdf"]).exists() else "—"
            print(f"{mark} {e['id']} {e['name']} -> {e['pdf']}")
        return 0

    report = run_benchmark(periods=args.periods)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n报告: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
