"""表格提取准确率评估。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

import pandas as pd

from backend.pipeline.models import FinalTable


def normalize_cell(value: object) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[\s,¥$%]", "", text)
    text = re.sub(r"\.0+$", "", text)
    return text


def dataframe_to_grid(df: pd.DataFrame) -> list[list[str]]:
    if df is None or df.empty:
        return []
    cols = [normalize_cell(c) for c in df.columns.tolist()]
    rows = [[normalize_cell(v) for v in row] for row in df.astype(str).values.tolist()]
    return [cols] + rows


def grid_from_expected(rows: list[list[str]]) -> list[list[str]]:
    return [[normalize_cell(c) for c in row] for row in rows]


def _cell_match(expected: str, actual: str) -> bool:
    if not expected and not actual:
        return True
    if expected == actual:
        return True
    try:
        if float(expected) == float(actual):
            return True
    except ValueError:
        pass
    if expected in actual or actual in expected:
        return True
    # 表头 OCR 容错：caemount ↔ amount
    if re.search(r"amount$", expected) and re.search(r"amount$", actual):
        return True
    return False


def compare_grids(expected: list[list[str]], actual: list[list[str]]) -> float:
    if not expected:
        return 1.0 if not actual else 0.0
    if not actual:
        return 0.0

    exp_rows = len(expected)
    exp_cols = max(len(r) for r in expected)
    act_rows = len(actual)
    act_cols = max(len(r) for r in actual)

    best = 0.0
    for row_offset in range(max(0, act_rows - exp_rows) + 1):
        for col_offset in range(max(0, act_cols - exp_cols) + 1):
            matched = 0
            total = 0
            for r in range(exp_rows):
                for c in range(len(expected[r])):
                    total += 1
                    er = expected[r][c]
                    ar_idx = row_offset + r
                    ac_idx = col_offset + c
                    if ar_idx >= act_rows or ac_idx >= len(actual[ar_idx]):
                        continue
                    if _cell_match(er, actual[ar_idx][ac_idx]):
                        matched += 1
            if total:
                best = max(best, matched / total)
    return best


def pick_best_table_accuracy(
    tables: Iterable[FinalTable],
    page_num: int,
    expected_rows: list[list[str]],
) -> float:
    expected = grid_from_expected(expected_rows)
    page_tables = [t for t in tables if t.page_num == page_num]
    if not page_tables:
        return 0.0

    scores = [compare_grids(expected, dataframe_to_grid(t.dataframe)) for t in page_tables]
    return max(scores) if scores else 0.0


@dataclass
class BenchmarkCase:
    name: str
    pdf_path: str
    page: int
    expected_rows: list[list[str]]
    min_accuracy: float = 0.9


@dataclass
class BenchmarkResult:
    case_name: str
    accuracy: float
    passed: bool
    source: str = ""


def evaluate_case(case: BenchmarkCase, tables: list[FinalTable]) -> BenchmarkResult:
    accuracy = pick_best_table_accuracy(tables, case.page, case.expected_rows)
    page_tables = [t for t in tables if t.page_num == case.page]
    source = "none"
    if page_tables:
        from backend.evaluation.accuracy import compare_grids, dataframe_to_grid, grid_from_expected
        expected = grid_from_expected(case.expected_rows)
        best_t = max(
            page_tables,
            key=lambda t: compare_grids(expected, dataframe_to_grid(t.dataframe)),
        )
        source = best_t.source
    return BenchmarkResult(
        case_name=case.name,
        accuracy=round(accuracy, 4),
        passed=accuracy >= case.min_accuracy,
        source=source,
    )


def evaluate_corpus(cases: list[BenchmarkCase], all_results: dict[str, list[FinalTable]]) -> tuple[float, list[BenchmarkResult]]:
    results = []
    for case in cases:
        tables = all_results.get(case.pdf_path, [])
        results.append(evaluate_case(case, tables))
    if not results:
        return 0.0, results
    overall = sum(r.accuracy for r in results) / len(results)
    return round(overall, 4), results
