#!/usr/bin/env python3
"""生产级美股财报：SEC XBRL + PDF 文本层校验 + 专业 Excel 输出。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.markets.us.financials_service import UsFinancialsService
from backend.validation.reconciliation import MatchStatus

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]


def _serialize_result(result) -> dict:
    return {
        "ticker": result.ticker,
        "company_name": result.company_name,
        "trust_score": result.trust_score,
        "verification_rate": result.verification_rate,
        "production_ready": result.is_production_ready,
        "excel_path": result.excel_path,
        "pdf_source": result.filing.local_path if result.filing else None,
        "matched": result.reconciliation.matched_count,
        "mismatch": result.reconciliation.mismatch_count,
        "errors": result.errors,
        "mismatches": [
            {
                "field_id": item.field_id,
                "period_end": item.period_end,
                "xbrl": item.xbrl_value,
                "pdf": item.pdf_value,
                "delta": item.delta,
            }
            for item in result.reconciliation.items
            if item.status == MatchStatus.MISMATCH
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="US verified financials product runner")
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--periods", type=int, default=3)
    parser.add_argument("--pdf", default=None, help="可选：指定 10-K PDF/HTML 路径")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "data/outputs/verified_us"),
    )
    args = parser.parse_args()

    service = UsFinancialsService()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = []

    for ticker in args.tickers:
        print(f"\n=== {ticker} ===")
        result = service.build_verified_financials(
            ticker=ticker,
            periods=args.periods,
            document_path=args.pdf,
            output_dir=str(output_dir),
        )
        payload = _serialize_result(result)
        summary.append(payload)
        print(f"公司: {result.company_name}")
        print(f"信任分: {result.trust_score:.1%} | 校验通过率: {result.verification_rate:.1%}")
        print(f"匹配: {result.reconciliation.matched_count} | 不一致: {result.reconciliation.mismatch_count}")
        print(f"生产可用: {'是' if result.is_production_ready else '否'}")
        print(f"Excel: {result.excel_path}")
        if payload["mismatches"]:
            print("不一致项:")
            for row in payload["mismatches"]:
                print(f"  - {row['field_id']} {row['period_end']}: XBRL={row['xbrl']} PDF={row['pdf']} Δ={row['delta']}")

    report_path = output_dir / "verified_us_summary.json"
    report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n汇总报告: {report_path}")


if __name__ == "__main__":
    main()
