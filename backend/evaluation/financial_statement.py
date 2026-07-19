"""10-K 三大报表：页面定位、标准答案解析、逐项准确率对比。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz
import pandas as pd

from backend.markets.us.statement_locator import locate_statements_from_pages
from backend.markets.us.statement_text import (
    cashflow_line_pattern,
    EPS_BASIC_TEXT_PATTERN,
    flatten_statement_text,
    label_prefix_before_amounts,
    load_statement_text,
    merge_statement_pages,
    parse_statement_amounts,
    parse_eps_basic_amounts,
    eps_basic_label_part,
    score_cashflow_line,
    score_capex_line,
    score_eps_basic_line,
    score_net_income_line,
    statement_unit_divisor,
    truncate_balance_line_chunk,
    _is_revenue_expense_line,
    _is_segment_sales_line,
)

STATEMENT_PATTERNS = {
    "income": [
        r"consolidated\s+statements?\s+of\s+operations",
        r"consolidated\s+statements?\s+of\s+earnings",
        r"consolidated\s+statements?\s+of\s+income",
        r"\bincome\s+statements?\b",
    ],
    "balance": [
        r"consolidated\s+balance\s+sheets?",
        r"consolidated\s+statements?\s+of\s+financial\s+position",
        r"\bbalance\s+sheets?\b",
    ],
    "cashflow": [
        r"consolidated\s+statements?\s+of\s+cash\s+flows?",
        r"\bcash\s+flows?\s+statements?\b",
    ],
}

# 各报表核心行项（模糊匹配）
LINE_ITEMS = {
    "income": [
        ("total_net_sales", r"(?:net\s+)?(?:total\s+(?:net\s+)?(?:sales|revenue)s?|total\s+income)|\b(?:sales(?:\s+to\s+customers)?|revenues?)\b"),
        ("gross_margin", r"gross\s+(?:margin|profit)"),
        ("operating_income", r"(?:operating\s+income|income\s+from\s+operations|earnings\s+from\s+operations)"),
        ("net_income", r"net\s+(?:income|earnings)(?!\s+(?:from|per\b))"),
        ("eps_basic", EPS_BASIC_TEXT_PATTERN),
    ],
    "balance": [
        ("total_assets", r"total\s+assets(?!\s+and)"),
        ("total_liabilities", r"total\s+liabilities(?!\s+and\s+(?:shareholders|stockholders|equity))"),
        ("total_equity", r"total\s+shareholders?.?\s+equity(?!\s+and)|total\s+stockholders?.?\s+equity"),
        ("cash", r"cash and cash equivalents"),
    ],
    "cashflow": [
        ("operating", cashflow_line_pattern("operating")),
        ("investing", cashflow_line_pattern("investing")),
        ("financing", cashflow_line_pattern("financing")),
        (
            "capex",
            r"payments to acquire property,? plant and equipment|purchases of property,? plant and equipment|"
            r"purchase of property,? plant and equipment|capital expenditures|payments for property and equipment|"
            r"purchases of property and equipment",
        ),
    ],
}

# 资产负债表为时点数据，通常 2 列
BALANCE_SHEET_COLS = 2
INCOME_CASHFLOW_COLS = 3


@dataclass
class LineItemTruth:
    key: str
    label: str
    values: List[Optional[float]]  # 最近 3 个财年


@dataclass
class StatementTruth:
    statement_type: str
    page: int
    items: List[LineItemTruth] = field(default_factory=list)


@dataclass
class LineItemMatch:
    key: str
    label: str
    expected: List[Optional[float]]
    actual: List[Optional[float]]
    matched: bool
    column_hits: int
    column_total: int


@dataclass
class StatementScore:
    company: str
    statement_type: str
    page: int
    accuracy: float
    items: List[LineItemMatch]
    source: str = ""


def _parse_amounts(text: str, unit_divisor: float = 1.0) -> List[float]:
    return parse_statement_amounts(text, unit_divisor=unit_divisor)


def locate_statements(pdf_path: str) -> Dict[str, int]:
    """定位三大报表页（标准 10-K + ARS 年报 PDF）。"""
    doc = fitz.open(pdf_path)
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    return locate_statements_from_pages(pages)


def _to_float(val: object) -> Optional[float]:
    if val is None:
        return None
    text = str(val).strip().replace(",", "").replace("$", "")
    if not text or text in ("-", "—", "None", "nan"):
        return None
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _max_cols_for_statement(statement_type: str) -> int:
    return BALANCE_SHEET_COLS if statement_type == "balance" else INCOME_CASHFLOW_COLS


def extract_ground_truth(pdf_path: str, statement_type: str, page: int) -> StatementTruth:
    full_text = load_statement_text(pdf_path, statement_type, page)
    flat = flatten_statement_text(full_text)
    unit_divisor = statement_unit_divisor(full_text)
    items: List[LineItemTruth] = []
    max_cols = _max_cols_for_statement(statement_type)
    chunk_len = 280 if statement_type == "cashflow" else (90 if statement_type == "balance" else 180)

    for key, pat in LINE_ITEMS[statement_type]:
        best_amounts: List[float] = []
        best_label = ""
        best_rank = -1.0
        for m in re.finditer(pat, flat.lower()):
            before = flat[max(0, m.start() - 30) : m.start()].lower()
            chunk = flat[m.start() : m.start() + chunk_len]
            if statement_type == "balance":
                chunk = truncate_balance_line_chunk(chunk)
            if key == "operating_income" and "non-operating" in before:
                continue
            if key == "operating_income" and re.search(r"operating income\s*\(expense\)", chunk[:50], re.I):
                continue
            if key == "operating_income" and re.search(r"operating income\s*margin", chunk[:50], re.I):
                continue
            if key == "net_income" and "per share" in label_prefix_before_amounts(chunk).lower():
                continue
            if key == "net_income" and re.search(r"before income taxes|comprehensive income", chunk, re.I):
                continue
            if key == "eps_basic":
                if re.search(r"shares outstanding|average shares", label_prefix_before_amounts(chunk), re.I):
                    continue
                if re.search(r"computing net (?:income|loss) per (?:share|ads)", chunk, re.I):
                    continue
                label_part = eps_basic_label_part(chunk)
                if score_eps_basic_line(label_part) < 0:
                    continue
                if re.search(r"earnings per share", label_part, re.I) and not re.search(
                    r"\bbasic\b", label_part, re.I
                ):
                    continue
                if re.search(r"net income per share", label_part, re.I) and not re.search(
                    r"\bbasic\b", label_part, re.I
                ):
                    continue
                amounts = parse_eps_basic_amounts(chunk, max_cols=max_cols)
            else:
                amounts = _parse_amounts(chunk, unit_divisor=unit_divisor)[:max_cols]
            if not amounts:
                continue
            label_part = eps_basic_label_part(chunk) if key == "eps_basic" else label_prefix_before_amounts(chunk)
            if key == "net_income":
                ni_rank = score_net_income_line(label_part)
                if ni_rank < 0:
                    continue
            if key == "total_net_sales" and re.fullmatch(r"revenues?", m.group(0).strip()):
                if not re.search(r"total\s+(?:net\s+)?(?:revenue|sales)", chunk[:70], re.I):
                    tail = chunk[len(m.group(0)) :][:45].strip().lower()
                    if re.match(r"[a-z][a-z\s\-/]+(?:fees|income|expense|transactions|commissions)", tail):
                        continue
                    if re.match(r"(?:automotive|energy|services)\b", tail):
                        continue
                    if not re.search(r"\$\s*[\d,]+|\d{1,3}(?:,\d{3})+", chunk[:45]):
                        continue
            if key == "total_net_sales" and re.match(
                r"revenues?\s+(?:automotive|energy|services)\b", chunk[:55], re.I
            ):
                continue
            if key == "total_net_sales" and _is_revenue_expense_line(label_prefix_before_amounts(chunk)):
                continue
            if key == "total_net_sales" and _is_segment_sales_line(label_prefix_before_amounts(chunk)):
                continue
            if key == "total_net_sales":
                label_part = label_prefix_before_amounts(chunk).strip().lower()
                if label_part in ("sales", "sale", "revenue", "revenues"):
                    continue
                if label_part.startswith("sales ") and not label_part.startswith("sales to"):
                    continue
            if key == "net_income" and re.search(r"discontinued", chunk[:80], re.I):
                continue
            if key == "total_liabilities":
                if re.search(
                    r"total\s+liabilities\s+and\s+(?:stockholders|shareholders|equity)", chunk, re.I
                ):
                    continue
            if key == "capex":
                amounts = [abs(v) for v in amounts]
                label_part = label_prefix_before_amounts(chunk)
                rank = score_capex_line(label_part) + len(amounts) * 1000 - m.start()
                if rank < 0:
                    continue
            elif key in ("operating", "investing", "financing"):
                head = chunk[:70].lower()
                if "depreciation" in head or "amortization" in head:
                    continue
                if re.search(r"operating activities\s*:", chunk[:80], re.I):
                    continue
                rank = score_cashflow_line(label_prefix_before_amounts(chunk), m.start(), len(amounts))
                if rank < 0:
                    continue
            else:
                rank = len(amounts) * 1000 - m.start()
                if key == "total_net_sales" and re.search(
                    r"total\s+(?:net\s+)?(?:revenue|sales)", chunk[:60], re.I
                ):
                    rank += 5000
                if key == "net_income":
                    rank += score_net_income_line(label_prefix_before_amounts(chunk))
                if key == "eps_basic":
                    rank += score_eps_basic_line(label_prefix_before_amounts(chunk))
            if rank > best_rank:
                best_rank = rank
                best_amounts = amounts
                best_label = m.group(0)
        if best_amounts:
            items.append(
                LineItemTruth(key=key, label=best_label, values=best_amounts)
            )

    return StatementTruth(statement_type=statement_type, page=page, items=items)


def _row_label(row: pd.Series) -> str:
    for v in row:
        text = str(v).strip().lower()
        if text and text not in ("none", "nan"):
            return text
    return ""


def _row_numbers(row: pd.Series) -> List[Optional[float]]:
    nums: List[Optional[float]] = []
    for v in row:
        n = _to_float(v)
        if n is not None:
            nums.append(n)
    return nums


def match_statement(
    truth: StatementTruth,
    dataframe: pd.DataFrame,
    source: str = "",
) -> StatementScore:
    from backend.pipeline.financial_table_refiner import refine_financial_dataframe

    if not dataframe.empty:
        dataframe = refine_financial_dataframe(dataframe)

    matches: List[LineItemMatch] = []
    patterns = dict(LINE_ITEMS[truth.statement_type])

    for item in truth.items:
        best_actual: List[Optional[float]] = []
        best_hits = 0
        pat = patterns[item.key]
        expected = [v for v in item.values if v is not None]

        for row in dataframe.itertuples(index=False):
            series = pd.Series(row)
            label = " ".join(
                str(v).strip().lower()
                for v in series
                if str(v).strip() and str(v).strip().lower() not in ("none", "nan")
            )
            if not re.search(pat, label):
                continue
            actual_nums = _row_numbers(series)
            hits = 0
            for exp, act in zip(expected, actual_nums):
                if act is not None and abs(exp - act) < 1.0:
                    hits += 1
            if hits > best_hits:
                best_hits = hits
                best_actual = actual_nums[: len(expected)]

        total_cols = len(expected)
        matched = best_hits == total_cols and total_cols > 0
        matches.append(
            LineItemMatch(
                key=item.key,
                label=item.label,
                expected=item.values,
                actual=best_actual,
                matched=matched,
                column_hits=best_hits,
                column_total=total_cols,
            )
        )

    total_hits = sum(m.column_hits for m in matches)
    total_cols = sum(m.column_total for m in matches)
    accuracy = total_hits / total_cols if total_cols else 0.0

    return StatementScore(
        company="",
        statement_type=truth.statement_type,
        page=truth.page,
        accuracy=round(accuracy, 4),
        items=matches,
        source=source,
    )


def extract_statement_pages_pdf(src_path: str, pages: Dict[str, int], out_path: str) -> str:
    """把三大报表页抽成单独 PDF，加速 benchmark。"""
    doc = fitz.open(src_path)
    out = fitz.open()
    for stype in ("income", "balance", "cashflow"):
        if stype in pages:
            p = pages[stype]
            out.insert_pdf(doc, from_page=p, to_page=p)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path)
    out.close()
    doc.close()
    return out_path
