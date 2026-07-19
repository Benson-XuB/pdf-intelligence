#!/usr/bin/env python3
"""无 Docling 时，用 pdfplumber 多策略交叉对比定位低准确率页面。"""

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz
import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.pipeline.text_grid_extractor import extract_text_grid_from_page
from backend.pipeline.table_refiner import refine_dataframe

STRATEGIES = {
    "lines": {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "intersection_tolerance": 8,
    },
    "text": {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "snap_tolerance": 5,
        "join_tolerance": 5,
    },
    "lines_strict": {
        "vertical_strategy": "lines_strict",
        "horizontal_strategy": "lines_strict",
    },
}


def _normalize(val: str) -> str:
    return re.sub(r"[\s,$¥]", "", str(val).strip().lower())


def _df_to_cells(df: pd.DataFrame) -> List[str]:
    return [_normalize(v) for v in df.astype(str).values.flatten() if _normalize(v)]


def _agreement(cells_a: List[str], cells_b: List[str]) -> float:
    if not cells_a and not cells_b:
        return 1.0
    if not cells_a or not cells_b:
        return 0.0
    set_a, set_b = set(cells_a), set(cells_b)
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


def _table_quality(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"rows": 0, "cols": 0, "fill_rate": 0.0, "numeric_cells": 0}
    flat = df.astype(str).values.flatten()
    non_empty = sum(1 for v in flat if str(v).strip())
    numeric = sum(1 for v in flat if re.search(r"\d", str(v)))
    return {
        "rows": len(df),
        "cols": len(df.columns),
        "fill_rate": round(non_empty / max(df.size, 1), 3),
        "numeric_cells": numeric,
    }


def _extract_best_table(page, strategy_name: str) -> Optional[pd.DataFrame]:
    if strategy_name == "text_grid":
        df = extract_text_grid_from_page(page)
        return refine_dataframe(df) if df is not None else None

    settings = STRATEGIES[strategy_name]
    try:
        raw = page.extract_tables(table_settings=settings) or []
    except Exception:
        return None
    best = None
    best_score = 0
    for table in raw:
        if not table or len(table) < 2:
            continue
        header = [str(c) if c else "" for c in table[0]]
        rows = [[str(c) if c else "" for c in row] for row in table[1:]]
        df = pd.DataFrame(rows, columns=header)
        df = refine_dataframe(df)
        q = _table_quality(df)
        score = q["fill_rate"] * q["rows"] * q["cols"]
        if score > best_score:
            best_score = score
            best = df
    return best


def _page_preview(pdf_path: str, page_num: int, max_chars: int = 150) -> str:
    doc = fitz.open(pdf_path)
    text = doc[page_num].get_text().strip().replace("\n", " ")
    doc.close()
    return text[:max_chars] + ("..." if len(text) > max_chars else "")


def _detect_section(preview: str) -> str:
    p = preview.lower()
    if "consolidated statements of operations" in p or "income" in p[:80]:
        return "利润表"
    if "balance sheet" in p or "assets" in p[:60]:
        return "资产负债表"
    if "cash flow" in p:
        return "现金流量表"
    if "note" in p[:40] or "notes to" in p:
        return "财务报表附注"
    if "table of contents" in p:
        return "目录"
    if "risk factor" in p:
        return "风险因素"
    if "stock" in p[:60] or "share" in p[:60]:
        return "股本/持股"
    if re.search(r"form 10-k|annual report", p):
        return "封面/声明"
    return "正文/其他"


def analyze_plumber(pdf_path: str, output_json: Optional[str] = None) -> dict:
    pdf_path = str(pdf_path)
    t0 = time.time()
    strategy_names = list(STRATEGIES.keys()) + ["text_grid"]

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    page_reports = []
    section_stats: Dict[str, List[float]] = defaultdict(list)
    issue_counts: Dict[str, int] = defaultdict(int)

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            tables: Dict[str, Optional[pd.DataFrame]] = {}
            qualities: Dict[str, dict] = {}
            for name in strategy_names:
                df = _extract_best_table(page, name)
                tables[name] = df
                qualities[name] = _table_quality(df) if df is not None else {"rows": 0, "cols": 0, "fill_rate": 0.0, "numeric_cells": 0}

            cells = {k: _df_to_cells(v) for k, v in tables.items() if v is not None}
            agreements = {}
            pairs = [("lines", "text"), ("lines", "text_grid"), ("text", "text_grid"), ("lines_strict", "text")]
            for a, b in pairs:
                if a in cells and b in cells:
                    agreements[f"{a}_vs_{b}"] = round(_agreement(cells[a], cells[b]), 3)

            avg_agreement = sum(agreements.values()) / len(agreements) if agreements else 1.0
            best_strategy = max(qualities.keys(), key=lambda k: qualities[k]["rows"] * qualities[k]["cols"] * qualities[k]["fill_rate"])
            preview = _page_preview(pdf_path, page_num)
            section = _detect_section(preview)

            issues = []
            if avg_agreement < 0.5:
                issues.append("多策略严重不一致")
                issue_counts["多策略严重不一致"] += 1
            elif avg_agreement < 0.7:
                issues.append("多策略部分不一致")
                issue_counts["多策略部分不一致"] += 1

            if all(qualities[s]["rows"] == 0 for s in strategy_names):
                if len(page.chars) > 100:
                    issues.append("有文字但未提取到表格")
                    issue_counts["有文字但未提取到表格"] += 1

            best_q = qualities[best_strategy]
            if best_q["rows"] > 0 and best_q["fill_rate"] < 0.6:
                issues.append("表格空洞率高")
                issue_counts["表格空洞率高"] += 1

            if best_q["numeric_cells"] > 5 and avg_agreement < 0.65:
                issues.append("财务数字页策略分歧")
                issue_counts["财务数字页策略分歧"] += 1

            # 综合风险分：越低越差
            risk_score = round(
                0.4 * avg_agreement
                + 0.3 * best_q["fill_rate"]
                + 0.2 * min(best_q["rows"] * best_q["cols"] / 50, 1.0)
                + 0.1 * (1.0 if best_q["numeric_cells"] > 0 else 0.5),
                3,
            )

            entry = {
                "page": page_num + 1,
                "section": section,
                "risk_score": risk_score,
                "avg_agreement": round(avg_agreement, 3),
                "agreements": agreements,
                "best_strategy": best_strategy,
                "qualities": qualities,
                "issues": issues,
                "preview": preview,
            }
            page_reports.append(entry)
            section_stats[section].append(risk_score)

    risky = [p for p in page_reports if p["risk_score"] < 0.65 or p["issues"]]
    risky.sort(key=lambda x: x["risk_score"])

    section_summary = {
        sec: {
            "pages": len(scores),
            "avg_risk": round(sum(scores) / len(scores), 3),
            "low_risk_pages": sum(1 for s in scores if s < 0.65),
        }
        for sec, scores in sorted(section_stats.items(), key=lambda x: sum(x[1]) / len(x[1]))
    }

    result = {
        "pdf": Path(pdf_path).name,
        "total_pages": total_pages,
        "method": "pdfplumber_multi_strategy (Docling unavailable)",
        "avg_risk_score": round(sum(p["risk_score"] for p in page_reports) / len(page_reports), 3),
        "risky_pages": len(risky),
        "issue_summary": dict(sorted(issue_counts.items(), key=lambda x: -x[1])),
        "section_summary": section_summary,
        "worst_pages": risky[:20],
        "all_pages": page_reports,
        "elapsed_seconds": round(time.time() - t0, 1),
    }

    if output_json:
        Path(output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(output_json).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def print_summary(r: dict) -> None:
    print("\n" + "=" * 75)
    print(f"PDF: {r['pdf']}  |  Method: {r['method']}")
    print(f"Pages: {r['total_pages']}  |  Avg risk score: {r['avg_risk_score']:.1%}  |  Risky pages: {r['risky_pages']}")
    print(f"Elapsed: {r['elapsed_seconds']}s")
    print("=" * 75)

    print("\n## Section risk (lower = worse)")
    for sec, info in r["section_summary"].items():
        print(f"  {sec:<12} pages={info['pages']:3d}  avg_risk={info['avg_risk']:.1%}  low_risk={info['low_risk_pages']}")

    print("\n## Issue distribution")
    for issue, cnt in r["issue_summary"].items():
        print(f"  [{cnt:3d}] {issue}")

    print("\n## Worst 20 pages")
    print(f"{'Pg':>4} {'Risk':>6} {'Agree':>6} {'Section':<10} {'Best':<12} Issues")
    print("-" * 75)
    for p in r["worst_pages"]:
        issues = "; ".join(p["issues"]) or "borderline"
        print(
            f"{p['page']:>4} {p['risk_score']:>5.1%} {p['avg_agreement']:>5.1%} "
            f"{p['section']:<10} {p['best_strategy']:<12} {issues}"
        )


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else "data/samples/apple_2024_annual_report_10k.pdf"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/outputs/apple_2024_deep_analysis.json"
    result = analyze_plumber(pdf, out)
    print_summary(result)
    print(f"\nFull report: {out}")
