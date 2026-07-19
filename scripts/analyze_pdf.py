#!/usr/bin/env python3
"""分析 PDF 各页置信度，定位低准确率区域。"""

import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from backend.config import settings
from backend.pipeline.classifier import classify_page
from backend.pipeline.confidence import score_page
from backend.pipeline.docling_engine import DoclingEngine
from backend.pipeline.plumber_engine import PlumberEngine


def _page_preview(pdf_path: str, page_num: int, max_chars: int = 120) -> str:
    doc = fitz.open(pdf_path)
    text = doc[page_num].get_text().strip().replace("\n", " ")
    doc.close()
    return text[:max_chars] + ("..." if len(text) > max_chars else "")


def analyze(pdf_path: str, output_json: Optional[str] = None) -> dict:
    pdf_path = str(pdf_path)
    t0 = time.time()

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    print(f"Analyzing: {pdf_path} ({total_pages} pages)")
    print("Step 1/2: pdfplumber extraction...")
    plumber = PlumberEngine()
    plumber_result = plumber.extract(pdf_path)
    print(f"  -> {len(plumber_result.tables)} tables")

    docling_result = None
    if settings.enable_docling:
        print("Step 2/2: Docling extraction (may take several minutes)...")
        docling_result = DoclingEngine().extract(pdf_path)
        print(f"  -> {len(docling_result.tables)} tables")
    else:
        print("Step 2/2: Docling disabled, skipping")

    pages = set(range(total_pages))
    if docling_result:
        for t in docling_result.tables:
            pages.add(t.page_num)
    for t in plumber_result.tables:
        pages.add(t.page_num)

    page_reports = []
    reason_counts: dict[str, int] = defaultdict(int)
    low_pages = []
    threshold = settings.confidence_threshold

    for page_num in sorted(pages):
        profile = classify_page(pdf_path, page_num)
        d_tables = [t for t in (docling_result.tables if docling_result else []) if t.page_num == page_num]
        p_tables = [t for t in plumber_result.tables if t.page_num == page_num]
        report = score_page(d_tables, p_tables, profile)

        for r in report.reasons:
            reason_counts[r] += 1

        entry = {
            "page": page_num + 1,
            "score": report.score,
            "needs_qwen": report.needs_qwen,
            "reasons": report.reasons,
            "breakdown": report.breakdown,
            "page_type": profile.page_type.value,
            "has_tables": profile.has_tables,
            "docling_tables": len(d_tables),
            "plumber_tables": len(p_tables),
            "preview": _page_preview(pdf_path, page_num),
        }
        page_reports.append(entry)
        if report.score < threshold or report.needs_qwen:
            low_pages.append(entry)

    scores = [p["score"] for p in page_reports]
    avg_score = sum(scores) / len(scores) if scores else 0.0
    low_count = len(low_pages)
    qwen_needed = sum(1 for p in page_reports if p["needs_qwen"])

    # 按问题类型分组
    by_reason: dict[str, list] = defaultdict(list)
    for p in low_pages:
        if not p["reasons"]:
            by_reason["综合置信度低"].append(p)
        for r in p["reasons"]:
            by_reason[r].append(p)

    result = {
        "pdf": Path(pdf_path).name,
        "total_pages": total_pages,
        "threshold": threshold,
        "avg_confidence": round(avg_score, 3),
        "low_confidence_pages": low_count,
        "qwen_needed_pages": qwen_needed,
        "docling_tables": len(docling_result.tables) if docling_result else 0,
        "plumber_tables": len(plumber_result.tables),
        "elapsed_seconds": round(time.time() - t0, 1),
        "reason_summary": dict(sorted(reason_counts.items(), key=lambda x: -x[1])),
        "pages_by_reason": {
            k: [{"page": p["page"], "score": p["score"], "preview": p["preview"]} for p in v[:10]]
            for k, v in sorted(by_reason.items(), key=lambda x: -len(x[1]))
        },
        "worst_pages": sorted(page_reports, key=lambda x: x["score"])[:15],
        "all_pages": page_reports,
    }

    if output_json:
        Path(output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(output_json).write_text(json.dumps(result, ensure_ascii=False, indent=2))

    return result


def print_summary(result: dict) -> None:
    print("\n" + "=" * 70)
    print(f"PDF: {result['pdf']}")
    print(f"Pages: {result['total_pages']}  |  Avg confidence: {result['avg_confidence']:.1%}")
    print(f"Low-confidence pages (<{result['threshold']:.0%}): {result['low_confidence_pages']}")
    print(f"Pages needing Qwen fallback: {result['qwen_needed_pages']}")
    print(f"Docling tables: {result['docling_tables']}  |  pdfplumber tables: {result['plumber_tables']}")
    print(f"Elapsed: {result['elapsed_seconds']}s")
    print("=" * 70)

    print("\n## Problem distribution")
    for reason, count in result["reason_summary"].items():
        print(f"  [{count:3d}] {reason}")

    print("\n## Worst 15 pages")
    print(f"{'Page':>5} {'Score':>7} {'Type':>12} {'D/P tbl':>8} {'Reasons'}")
    print("-" * 70)
    for p in result["worst_pages"]:
        dp = f"{p['docling_tables']}/{p['plumber_tables']}"
        reasons = "; ".join(p["reasons"]) or "low overall"
        print(f"{p['page']:>5} {p['score']:>6.1%} {p['page_type']:>12} {dp:>8} {reasons}")

    print("\n## Breakdown averages (worst pages)")
    dims = ["table_structure", "cross_engine", "numeric", "ocr", "layout"]
    worst = result["worst_pages"]
    if worst:
        for dim in dims:
            avg = sum(p["breakdown"][dim] for p in worst) / len(worst)
            print(f"  {dim:<18} {avg:.1%}")


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else "data/samples/apple_2024_annual_report_10k.pdf"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/outputs/apple_2024_analysis.json"
    result = analyze(pdf, out)
    print_summary(result)
    print(f"\nFull report: {out}")
