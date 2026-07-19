from typing import List, Optional

import pandas as pd

from backend.evaluation.accuracy import compare_grids, dataframe_to_grid
from backend.pipeline.confidence import ConfidenceReport
from backend.pipeline.models import DoclingResult, ExtractedTable, FinalTable, PlumberResult
from backend.pipeline.plumber_engine import _df_hash


def _table_quality(df: pd.DataFrame) -> float:
    if df is None or df.empty:
        return 0.0
    non_empty = df.astype(str).apply(lambda col: col.str.strip().ne("")).sum().sum()
    return non_empty / max(df.size, 1)


def _table_score(df: pd.DataFrame) -> float:
    """综合评分：填充率 × 表格规模，过滤残缺小表格。"""
    if df is None or df.empty:
        return 0.0
    rows, cols = df.shape
    fill = _table_quality(df)
    if cols < 2 or rows < 2:
        return 0.0
    size_weight = (cols * rows) ** 0.5
    return fill * size_weight


def merge_results(
    docling_result: DoclingResult,
    plumber_result: PlumberResult,
    qwen_results: dict[int, pd.DataFrame],
    confidence_reports: dict[int, ConfidenceReport],
    docling_by_page: Optional[dict[int, list]] = None,
    plumber_by_page: Optional[dict[int, list]] = None,
) -> List[FinalTable]:
    final_tables: List[FinalTable] = []

    # 如果调用方已预建 dict，直接使用
    if docling_by_page is None:
        docling_by_page = {}
        for t in docling_result.tables:
            docling_by_page.setdefault(t.page_num, []).append(t)
    if plumber_by_page is None:
        plumber_by_page = {}
        for t in plumber_result.tables:
            plumber_by_page.setdefault(t.page_num, []).append(t)

    pages = set(docling_by_page.keys()) | set(plumber_by_page.keys()) | set(confidence_reports.keys())

    for page_num in sorted(pages):
        report = confidence_reports.get(page_num)

        if report and report.needs_qwen and page_num in qwen_results:
            df = qwen_results[page_num]
            if df is not None and not df.empty:
                final_tables.append(
                    FinalTable(
                        source="qwen",
                        page_num=page_num,
                        table_index=0,
                        dataframe=df,
                        confidence=report.score,
                    )
                )
                continue

        page_docling = docling_by_page.get(page_num, [])
        page_plumber = plumber_by_page.get(page_num, [])

        best_source = _pick_best_source(page_docling, page_plumber, report)
        if best_source == "docling" and page_docling:
            best = max(page_docling, key=lambda t: _table_score(t.dataframe))
            final_tables.append(
                FinalTable(
                    source="docling",
                    page_num=page_num,
                    table_index=best.table_index,
                    dataframe=best.dataframe,
                    confidence=report.score if report else 0.9,
                )
            )
        elif best_source == "pdfplumber" and page_plumber:
            best = _pick_best_plumber_table(page_plumber)
            if best is not None:
                final_tables.append(
                    FinalTable(
                        source="pdfplumber",
                        page_num=page_num,
                        table_index=best.table_index,
                        dataframe=best.dataframe,
                        confidence=report.score if report else 0.8,
                    )
                )

    return final_tables


def _pick_best_source(
    docling_tables: List[ExtractedTable],
    plumber_tables: list,
    report: Optional[ConfidenceReport],
) -> str:
    docling_score = max((_table_score(t.dataframe) for t in docling_tables), default=0.0)
    plumber_score = max((_table_score(t.dataframe) for t in plumber_tables), default=0.0)

    if not docling_tables and plumber_tables:
        return "pdfplumber"
    if docling_tables and not plumber_tables:
        return "docling"

    if report and report.breakdown.get("cross_engine", 1.0) >= 0.85:
        if docling_score >= plumber_score:
            return "docling"
        return "pdfplumber"

    if plumber_score > docling_score + 0.5:
        return "pdfplumber"
    if docling_score > plumber_score + 0.5:
        return "docling"
    return "pdfplumber" if plumber_score >= docling_score else "docling"


def _pick_best_plumber_table(tables: list):
    if not tables:
        return None
    ranked = sorted(tables, key=lambda t: _table_score(t.dataframe), reverse=True)
    seen: set[str] = set()
    for t in ranked:
        if _table_score(t.dataframe) < 2.0:
            continue
        key = _df_hash(t.dataframe)
        if key in seen:
            continue
        seen.add(key)
        return t
    return ranked[0]
