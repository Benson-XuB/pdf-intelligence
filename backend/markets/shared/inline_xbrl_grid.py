"""Inline-XBRL HTML table parsing shared by US 10-K and European ESEF."""

from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List, Optional

import pandas as pd
from bs4 import Tag

from backend.markets.us.statement_grid_extractor import PERIOD_DATE_HEADER_RE


class MarketContext(str, Enum):
    US_GAAP = "US-GAAP"
    IFRS = "IFRS"
    ESEF = "ESEF"


_US_STATEMENT_TABLE_SIGNALS: Dict[str, List[str]] = {
    "income": [
        r"\brevenues?\b",
        r"total net sales",
        r"operating income",
        r"net income",
        r"gross profit",
    ],
    "balance": [
        r"total assets",
        r"total liabilities",
        r"stockholders. equity",
        r"shareholders. equity",
    ],
    "cashflow": [
        r"operating activities",
        r"investing activities",
        r"financing activities",
        r"net cash",
    ],
}

_IFRS_STATEMENT_TABLE_SIGNALS: Dict[str, List[str]] = {
    "income": [
        r"\brevenue\b",
        r"revenue from contracts",
        r"operating profit",
        r"profit or loss",
        r"gross profit",
        r"net income",
        r"\bventes\b",
        r"chiffre d.?affaires",
        r"r[eé]sultat net",
        r"r[eé]sultat op[eé]rationnel",
    ],
    "balance": [
        r"total assets",
        r"total de l.?actif",
        r"total actif",
        r"total liabilities",
        r"total des passifs",
        r"total equity",
        r"capitaux propres",
        r"equity attributable",
        r"shareholders. equity",
        r"stockholders. equity",
    ],
    "cashflow": [
        r"operating activities",
        r"investing activities",
        r"financing activities",
        r"net cash",
        r"cash flows from",
        r"flux de tr[eé]sorerie",
        r"op[eé]rations d.exploitation",
        r"activit[eé]s op[eé]rationnelles",
    ],
}

_AMOUNT_TOKEN_RE = re.compile(
    r"\d{1,3}(?:[,\u00a0\u202f\u2009 ]\d{3})+|\(\s*[\d,\u00a0\u202f\u2009 ]+\s*\)"
)


def statement_table_signals(market: MarketContext) -> Dict[str, List[str]]:
    if market == MarketContext.US_GAAP:
        return _US_STATEMENT_TABLE_SIGNALS
    return _IFRS_STATEMENT_TABLE_SIGNALS


def _extract_amount_tokens_from_row(cells: List[str]) -> List[str]:
    """Extract amount tokens from an HTML row (skip standalone $ cells)."""
    amounts: List[str] = []
    i = 0
    while i < len(cells):
        cell = cells[i].strip()
        if cell in {"$", "($", "($)"}:
            j = i + 1
            while j < len(cells) and not cells[j].strip():
                j += 1
            if j < len(cells) and re.search(r"\d", cells[j]):
                amounts.append(cells[j].strip())
                i = j + 1
                continue
        elif re.search(r"\d", cell):
            if _AMOUNT_TOKEN_RE.search(cell) and not re.fullmatch(
                r"[\d.]+%", cell
            ):
                amounts.append(cell)
        i += 1
    return amounts


def _extract_period_labels_from_cells(cells: List[str]) -> List[str]:
    labels: List[str] = []
    for cell in cells:
        text = cell.strip()
        if not text:
            continue
        if PERIOD_DATE_HEADER_RE.search(text):
            labels.append(text)
        elif re.fullmatch(r"20\d{2}", text):
            labels.append(text)
    return labels


def _is_period_header_only_row(cells: List[str]) -> bool:
    non_empty = [c.strip() for c in cells if c.strip()]
    if len(non_empty) < 2:
        return False
    period_labels = _extract_period_labels_from_cells(cells)
    if len(period_labels) < 2:
        return False
    non_period = [
        c
        for c in non_empty
        if not PERIOD_DATE_HEADER_RE.search(c) and not re.fullmatch(r"20\d{2}", c)
    ]
    return not non_period or all(re.fullmatch(r"year ended", c, re.I) for c in non_period)


def compact_html_statement_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Compress SEC/ESEF HTML layouts like '$ | amount | empty | $ | amount' into label + N cols."""
    if df is None or df.empty:
        return df

    period_labels: List[str] = []
    max_amount_cols = 0
    compact_rows: List[List[str]] = []
    for _, row in df.iterrows():
        cells = [str(v).strip() for v in row.values]
        if not any(cells):
            continue

        row_periods = _extract_period_labels_from_cells(cells)
        if len(row_periods) >= 2:
            if len(row_periods) > len(period_labels):
                period_labels = row_periods
            if _is_period_header_only_row(cells):
                continue

        label_parts: List[str] = []
        amount_start = 0
        for idx, cell in enumerate(cells):
            if not cell:
                continue
            if _AMOUNT_TOKEN_RE.search(cell) or cell in {"$", "($"}:
                amount_start = idx
                break
            if PERIOD_DATE_HEADER_RE.search(cell) or re.fullmatch(r"20\d{2}", cell):
                amount_start = len(cells)
                break
            label_parts.append(cell)
        label = " ".join(label_parts).strip()
        if not label and amount_start == 0:
            continue
        if amount_start >= len(cells):
            if label:
                compact_rows.append([label])
            continue
        amounts = _extract_amount_tokens_from_row(cells[amount_start:])
        if not amounts and label:
            compact_rows.append([label])
            continue
        if not label and amounts:
            label = ""
        row_out = [label] + amounts
        max_amount_cols = max(max_amount_cols, len(amounts))
        compact_rows.append(row_out)

    if max_amount_cols < 2:
        return df

    normalized: List[List[str]] = []
    for row in compact_rows:
        label = row[0] if row else ""
        amounts = row[1:] if len(row) > 1 else []
        normalized.append([label] + amounts + [""] * (max_amount_cols - len(amounts)))

    if len(period_labels) >= max_amount_cols:
        columns = ["label"] + period_labels[:max_amount_cols]
    else:
        columns = ["label"] + [f"col_{i}" for i in range(max_amount_cols)]
    return pd.DataFrame(normalized, columns=columns)


def html_table_to_dataframe(table: Tag) -> Optional[pd.DataFrame]:
    """Convert an HTML <table> to a grid-compatible DataFrame."""
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        if any(cells):
            rows.append(cells)
    if len(rows) < 4:
        return None
    max_cols = max(len(r) for r in rows)
    if max_cols < 3:
        return None
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]
    df = pd.DataFrame(normalized)
    return compact_html_statement_dataframe(df)


def score_html_table_text(
    text: str,
    statement_type: str,
    market: MarketContext = MarketContext.US_GAAP,
    *,
    extra_score: float = 0.0,
) -> float:
    """Score how likely an HTML table is a primary financial statement."""
    lower = text.lower()
    score = extra_score
    for pattern in statement_table_signals(market).get(statement_type, []):
        if re.search(pattern, lower):
            score += 1_000.0
    if re.search(r"100\.0\s*%|100\.0%", text):
        score -= 5_000.0
    if re.search(r"\bup \d+%|\bdown \d+%", lower):
        score -= 3_000.0
    elif re.search(r"\bpercent\s+change\b|\byear.over.year\b", lower[:600]):
        score -= 3_000.0
    if statement_type == "income" and re.search(r"per share", lower):
        score += 500.0
    return score
