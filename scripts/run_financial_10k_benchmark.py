#!/usr/bin/env python3
"""5 家 10-K 三大报表基准：逐项对比官方 PDF 文本数字，输出可读报告。"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.evaluation.financial_statement import (
    LINE_ITEMS,
    extract_ground_truth,
    extract_statement_pages_pdf,
    locate_statements,
    match_statement,
)
from backend.pipeline.orchestrator import PipelineOrchestrator

BENCHMARK_DIR = ROOT / "tests/benchmark/financial_10k"
REPORT_PATH = BENCHMARK_DIR / "last_report.json"

COMPANIES = [
    {
        "id": "AAPL",
        "name": "Apple",
        "pdf": "data/samples/apple_2024_annual_report_10k.pdf",
        "url": None,
    },
    {
        "id": "MSFT",
        "name": "Microsoft",
        "pdf": "tests/benchmark/financial_10k/msft_2024_10k.pdf",
        "url": "https://microsoft.gcs-web.com/static-files/1c864583-06f7-40cc-a94d-d11400c83cc8",
    },
    {
        "id": "GOOGL",
        "name": "Alphabet",
        "pdf": "tests/benchmark/financial_10k/googl_2024_10k.pdf",
        "url": "https://s206.q4cdn.com/479360582/files/doc_financials/2024/q4/goog-10-k-2024.pdf",
    },
    {
        "id": "AMZN",
        "name": "Amazon",
        "pdf": "tests/benchmark/financial_10k/amzn_2024_10k.pdf",
        "url": "https://s2.q4cdn.com/299287126/files/doc_financials/2025/ar/Amazon-2024-Annual-Report.pdf",
    },
    {
        "id": "META",
        "name": "Meta",
        "pdf": "tests/benchmark/financial_10k/meta_2024_10k.pdf",
        "url": "https://s21.q4cdn.com/399680738/files/doc_financials/2024/ar/Meta-12-31-2024-10K-ARS.pdf",
    },
]

THRESHOLD_GO = 0.90
THRESHOLD_STOP = 0.80

STMT_LABELS = {"income": "利润表", "balance": "资产负债表", "cashflow": "现金流量表"}


def ensure_pdfs() -> list[str]:
    import urllib.request

    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    missing = []
    headers = {"User-Agent": "Mozilla/5.0 (pdf-intelligence benchmark)"}
    for c in COMPANIES:
        path = ROOT / c["pdf"]
        if path.exists():
            continue
        if not c["url"]:
            missing.append(f"{c['id']}: {path} (需手动下载)")
            continue
        print(f"下载 {c['name']} 10-K ...")
        try:
            req = urllib.request.Request(c["url"], headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                path.write_bytes(resp.read())
            print(f"  -> {path}")
        except Exception as exc:
            missing.append(f"{c['id']}: {exc}")
    return missing


def run_benchmark() -> dict:
    missing = ensure_pdfs()
    if missing:
        print("缺少 PDF:")
        for m in missing:
            print(" -", m)
        if not (ROOT / COMPANIES[0]["pdf"]).exists():
            sys.exit(1)

    orchestrator = PipelineOrchestrator()
    all_scores = []
    company_results = []

    for c in COMPANIES:
        pdf_path = ROOT / c["pdf"]
        if not pdf_path.exists():
            print(f"跳过 {c['id']}（文件不存在）")
            continue

        pages = locate_statements(str(pdf_path))
        if len(pages) < 3:
            print(f"跳过 {c['id']}：只找到 {list(pages.keys())} 报表页")
            continue

        mini_path = BENCHMARK_DIR / f"{c['id']}_statements_only.pdf"
        extract_statement_pages_pdf(str(pdf_path), pages, str(mini_path))

        print(f"\n处理 {c['name']} ({c['id']}) — 仅 3 页报表 ...")
        t0 = time.time()
        result = orchestrator.process(str(mini_path))
        elapsed = time.time() - t0
        print(f"  耗时 {elapsed:.0f}s, 表格 {len(result.tables)}, Qwen {result.qwen_calls}")

        # mini PDF 页序: 0=income, 1=balance, 2=cashflow
        ordered_types = [t for t in ("income", "balance", "cashflow") if t in pages]
        company_scores = []

        for mini_page, stype in enumerate(ordered_types):
            orig_page = pages[stype]
            truth = extract_ground_truth(str(pdf_path), stype, orig_page)
            if not truth.items:
                print(f"  ⚠️ {STMT_LABELS[stype]} 未能从 PDF 文本解析标准答案")
                continue

            page_tables = [t for t in result.tables if t.page_num == mini_page]
            if not page_tables:
                score = match_statement(truth, __import__("pandas").DataFrame(), source="none")
            else:
                best = max(page_tables, key=lambda t: t.dataframe.size)
                score = match_statement(truth, best.dataframe, source=best.source)

            score.company = c["id"]
            company_scores.append(score)
            all_scores.append(score)

        if company_scores:
            avg = sum(s.accuracy for s in company_scores) / len(company_scores)
            company_results.append({"id": c["id"], "name": c["name"], "avg": avg, "scores": company_scores})

    overall = sum(s.accuracy for s in all_scores) / len(all_scores) if all_scores else 0.0
    return {
        "overall_accuracy": round(overall, 4),
        "threshold_go": THRESHOLD_GO,
        "threshold_stop": THRESHOLD_STOP,
        "verdict": _verdict(overall),
        "companies": _serialize(company_results),
        "details": [_serialize_score(s) for s in all_scores],
    }


def _verdict(overall: float) -> str:
    if overall >= THRESHOLD_GO:
        return "GO — 垂直产品值得继续做"
    if overall < THRESHOLD_STOP:
        return "STOP — 建议转向 GEO 或其他方向"
    return "HOLD — 在 80–90% 之间，需再优化核心行项"


def _serialize_score(s) -> dict:
    return {
        "company": s.company,
        "statement": s.statement_type,
        "statement_cn": STMT_LABELS.get(s.statement_type, s.statement_type),
        "page": s.page + 1,
        "accuracy": s.accuracy,
        "source": s.source,
        "items": [asdict(i) for i in s.items],
    }


def _serialize(company_results) -> list:
    out = []
    for cr in company_results:
        out.append({
            "id": cr["id"],
            "name": cr["name"],
            "avg_accuracy": round(cr["avg"], 4),
            "statements": [_serialize_score(s) for s in cr["scores"]],
        })
    return out


def print_report(report: dict) -> None:
    print("\n" + "=" * 72)
    print("10-K 三大报表基准测试 — 逐项数字准确率")
    print("=" * 72)
    print(f"整体准确率: {report['overall_accuracy']:.1%}")
    print(f"判定: {report['verdict']}")
    print(f"阈值: ≥{THRESHOLD_GO:.0%} 继续  |  <{THRESHOLD_STOP:.0%} 放弃")
    print("-" * 72)

    for co in report["companies"]:
        print(f"\n## {co['name']} ({co['id']}) — 平均 {co['avg_accuracy']:.1%}")
        for st in co["statements"]:
            mark = "✅" if st["accuracy"] >= THRESHOLD_GO else ("❌" if st["accuracy"] < THRESHOLD_STOP else "⚠️")
            print(f"  {mark} {st['statement_cn']:<8} p{st['page']:<3} {st['accuracy']:>6.1%}  [{st['source']}]")
            for item in st["items"]:
                exp = item["expected"]
                act = item["actual"]
                hit = f"{item['column_hits']}/{item['column_total']}"
                status = "OK" if item["matched"] else "MISS"
                print(f"      {status:<4} {item['key']:<18} 官方{exp}  提取{act}  ({hit})")

    print("\n" + "=" * 72)
    print(f"报告: {REPORT_PATH}")


def main() -> int:
    report = run_benchmark()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print_report(report)
    if report["overall_accuracy"] < THRESHOLD_STOP:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
