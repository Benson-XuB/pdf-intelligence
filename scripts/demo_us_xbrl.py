#!/usr/bin/env python3
"""美股 Global Schema v1 + SEC XBRL demo：拉取官方数据并导出 Excel。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.export.global_excel import GlobalExcelExporter
from backend.markets.us.xbrl_adapter import UsSecXbrlAdapter

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]


def _field_value_to_dict(item) -> dict:
    data = asdict(item)
    data["scale"] = item.scale.value
    return data


def run_demo(tickers: list[str], output_dir: Path) -> None:
    adapter = UsSecXbrlAdapter()
    exporter = GlobalExcelExporter()
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for ticker in tickers:
        print(f"拉取 {ticker} SEC XBRL ...")
        financials = adapter.fetch(ticker)
        xlsx_path = output_dir / f"{ticker.lower()}_global_schema.xlsx"
        json_path = output_dir / f"{ticker.lower()}_global_schema.json"
        exporter.export(financials, str(xlsx_path))

        payload = {
            "ticker": financials.ticker,
            "company_name": financials.company_name,
            "market": financials.market,
            "cik": financials.cik,
            "standard": financials.standard,
            "periods": financials.periods,
            "errors": financials.errors,
            "values": [_field_value_to_dict(v) for v in financials.values],
        }
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        filled = sum(1 for v in financials.values if v.value is not None)
        print(
            f"  {financials.company_name}: {filled} 个数值, "
            f"期间 {', '.join(financials.periods)}, Excel -> {xlsx_path.name}"
        )
        if financials.errors:
            print(f"  缺失字段: {', '.join(financials.errors)}")
        summary.append(
            {
                "ticker": ticker,
                "company": financials.company_name,
                "periods": financials.periods,
                "value_count": filled,
                "missing_fields": len(financials.errors),
                "excel": str(xlsx_path),
            }
        )

    (output_dir / "us_xbrl_demo_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n完成。输出目录: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="US SEC XBRL Global Schema demo")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help="美股 ticker 列表",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "data/outputs/global_schema_us"),
        help="输出目录",
    )
    args = parser.parse_args()
    run_demo(args.tickers, Path(args.output_dir))


if __name__ == "__main__":
    main()
