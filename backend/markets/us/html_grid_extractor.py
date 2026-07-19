"""SEC iXBRL / HTML 10-K 表格 → StatementGrid（复用 PDF grid 行标签匹配）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from backend.markets.shared.inline_xbrl_grid import (
    MarketContext,
    html_table_to_dataframe,
    score_html_table_text,
)
from backend.markets.us.statement_grid_extractor import (
    StatementGrid,
    _dataframe_to_statement_grid,
    _expand_packed_statement_grid,
    _normalize_label,
    _preferred_currency_from_text,
    build_fiscal_calendar,
)
from backend.markets.us.statement_text import merge_statement_pages

_PARENT_SCHEDULE_TABLE_RE = re.compile(
    r"intercompany|notes?\s+receivable\s+from\s+subsidiaries|notes?\s+payable\s+to\s+subsidiaries|"
    r"parent\s+company\s+(?:only\s+)?(?:balance|financial)|"
    r"condensed\s+financial\s+information\s+of\s+(?:the\s+)?parent",
    re.IGNORECASE,
)
_INCOME_SUMMARY_TABLE_RE = re.compile(
    r"retail unit counts|retail square feet|stores at period end|"
    r"financial highlights|selected consolidated|members and stores",
    re.IGNORECASE,
)


def _score_html_table_text(
    text: str,
    statement_type: str,
    market: MarketContext = MarketContext.US_GAAP,
) -> float:
    lower = text.lower()
    extra = 0.0
    if statement_type == "balance":
        if re.search(r"consolidated\s+(?:balance\s+sheet|statement\s+of\s+financial\s+position)", lower[:400]):
            extra += 800.0
        if re.search(r"\bcompany\s+balance\s+sheet\b", lower[:400]):
            extra -= 4_000.0
        if _PARENT_SCHEDULE_TABLE_RE.search(lower):
            extra -= 4_000.0
    if statement_type == "income" and _INCOME_SUMMARY_TABLE_RE.search(lower):
        extra -= 4_000.0
    if statement_type == "income" and re.search(
        r"consolidated\s+statement\s+of\s+comprehensive\s+income|profit\s+or\s+loss",
        lower[:500],
    ):
        extra += 400.0
    return score_html_table_text(
        text,
        statement_type,
        market,
        extra_score=extra,
    )


def _amount_digits(text: str) -> str:
    return re.sub(r"[^\d]", "", str(text))


_TOTAL_ASSETS_LABEL_RE = re.compile(
    r"^total(?:\s+de\s+l.?actif|\s+actif|\s+assets)$",
    re.IGNORECASE,
)


def _grid_totals_appear_in_merged_text(
    grid: StatementGrid,
    merged_text: str,
    statement_type: str,
) -> bool:
    """合并报表定位页中的合计金额须出现在候选表格内（排除母公司/分部附表）。"""
    merged_digits = _amount_digits(merged_text)
    if statement_type == "balance":
        for label, values in grid.rows:
            norm = _normalize_label(label)
            if not _TOTAL_ASSETS_LABEL_RE.search(norm):
                continue
            anchors = [_amount_digits(v) for v in values if len(_amount_digits(v)) >= 5]
            if not anchors:
                return True
            return any(anchor in merged_digits for anchor in anchors)
        return True

    if statement_type == "cashflow":
        for label, values in grid.rows:
            norm = _normalize_label(label)
            if not re.search(
                r"^cash flows (?:from|used for|\(used for\) from|provided by|\(used in\) )",
                norm,
            ) and not re.search(
                r"flux de tr[eé]sorerie|activit[eé]s op[eé]rationnelles|op[eé]rations d.exploitation",
                norm,
            ):
                continue
            if not re.search(r"(?:operating|investing|financing) activities", norm) and not re.search(
                r"exploitation|investissement|financement",
                norm,
            ):
                continue
            anchors = [_amount_digits(v) for v in values if len(_amount_digits(v)) >= 4]
            if not anchors:
                continue
            return any(anchor in merged_digits for anchor in anchors)
        return True

    return True


def _html_grid_content_bonus(
    grid: StatementGrid,
    statement_type: str,
    market: MarketContext = MarketContext.US_GAAP,
) -> float:
    """根据 grid 行结构加分/减分，避免误选摘要表或附表。"""
    bonus = 0.0
    labels = [_normalize_label(label) for label, _ in grid.rows]
    if statement_type == "income":
        if any(
            re.search(r"net income attributable to (?!non[- ]?controlling)", label)
            for label in labels
        ):
            bonus += 800.0
        if any(
            re.search(r"income before income taxes|provision for income taxes", label)
            for label in labels
        ):
            bonus += 300.0
        if any(_INCOME_SUMMARY_TABLE_RE.search(label) for label in labels):
            bonus -= 2_000.0
        if market in {MarketContext.IFRS, MarketContext.ESEF}:
            if any(
                re.search(
                    r"net (?:non-interest )?revenue|revenue from contracts|total revenue|"
                    r"ventes|chiffre d.?affaires",
                    label,
                )
                for label in labels
            ):
                bonus += 2_500.0
            if any(
                re.search(
                    r"net income for the year|net income attributable|r[eé]sultat net",
                    label,
                )
                for label in labels
            ):
                bonus += 1_500.0
            if any(re.search(r"^finance income$|^net finance income$", label) for label in labels) and not any(
                re.search(r"revenue", label) for label in labels
            ):
                bonus -= 3_000.0
    if statement_type == "balance" and market in {MarketContext.IFRS, MarketContext.ESEF}:
        if any(_TOTAL_ASSETS_LABEL_RE.search(label) for label in labels):
            bonus += 2_500.0
        if any(
            re.search(r"total equity|total liabilities|capitaux propres|total des passifs", label)
            for label in labels
        ):
            bonus += 400.0
        if not any(_TOTAL_ASSETS_LABEL_RE.search(label) for label in labels) and any(
            re.search(r"total equity attributable|share premium|retained earnings", label)
            for label in labels
        ):
            bonus -= 2_500.0
    return bonus


def _html_grid_selection_score(
    grid: StatementGrid,
    tbl_text: str,
    statement_type: str,
    market: MarketContext = MarketContext.US_GAAP,
) -> float:
    return (
        len(grid.period_ends) * 100.0
        + len(grid.rows)
        + _score_html_table_text(tbl_text, statement_type, market)
        + _html_grid_content_bonus(grid, statement_type, market)
    )


def _table_overlaps_statement_text(table: Tag, merged_text: str) -> bool:
    """表格内容须与定位到的报表页文本有实质重叠。"""
    tbl_text = table.get_text(" ", strip=True)
    if len(tbl_text) < 80:
        return False
    probe = re.sub(r"\s+", " ", tbl_text[:400]).strip().lower()
    merged = re.sub(r"\s+", " ", merged_text[:8000]).strip().lower()
    if probe[:60] in merged:
        return True
    tokens = [t for t in re.split(r"\W+", probe) if len(t) > 4][:12]
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in merged)
    return hits >= min(4, len(tokens) // 2 + 1)


def build_grid_from_html_table(
    table: Tag,
    merged_text: str,
    statement_type: str,
    fiscal_calendar: Optional[Dict[int, str]] = None,
    preferred_currency: Optional[str] = None,
) -> Optional[StatementGrid]:
    df = html_table_to_dataframe(table)
    if df is None or df.empty:
        return None
    df = _expand_packed_statement_grid(df, merged_text)
    pref = preferred_currency or _preferred_currency_from_text(merged_text)
    return _dataframe_to_statement_grid(
        df,
        merged_text,
        statement_type,
        fiscal_calendar=fiscal_calendar,
        preferred_currency=pref,
    )


def _merge_statement_grids(grids: List[StatementGrid]) -> Optional[StatementGrid]:
    """ESEF/IFRS 年报常将同一报表拆成多个 HTML table，合并行标签。"""
    if not grids:
        return None
    if len(grids) == 1:
        return grids[0]
    periods = grids[0].period_ends
    merged_rows: Dict[str, Tuple[str, List[str]]] = {}
    for grid in grids:
        period_index = {period: idx for idx, period in enumerate(grid.period_ends)}
        for label, values in grid.rows:
            key = _normalize_label(label)
            aligned = [
                values[period_index[period]] if period in period_index and period_index[period] < len(values) else ""
                for period in periods
            ]
            filled = sum(1 for value in aligned if str(value).strip())
            prev = merged_rows.get(key)
            if prev is None or filled > sum(1 for value in prev[1] if str(value).strip()):
                merged_rows[key] = (label, aligned if any(aligned) else values)
    return StatementGrid(
        statement_type=grids[0].statement_type,
        period_ends=periods,
        rows=list(merged_rows.values()),
    )


def extract_html_statement_grids(
    html_path: str,
    statement_pages: Dict[str, int],
    pages_text: List[str],
    preferred_currency: Optional[str] = None,
    market: str | MarketContext = MarketContext.US_GAAP,
) -> Dict[str, StatementGrid]:
    """从 SEC HTML / ESEF XHTML 文档中为 income/balance/cashflow 各选最佳表格。"""
    from backend.markets.us.statement_grid_extractor import _statement_page_span

    market_ctx = MarketContext(market) if isinstance(market, str) else market
    html = Path(html_path).read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    fiscal_calendar = build_fiscal_calendar(pages_text, statement_pages)
    grids: Dict[str, StatementGrid] = {}

    for stype, page_num in statement_pages.items():
        start, end = _statement_page_span(pages_text, page_num, stype)
        if end > start + 1:
            merged_text = merge_statement_pages(pages_text, start, stype)
        else:
            merged_text = pages_text[page_num] if page_num < len(pages_text) else ""

        best_grid: Optional[StatementGrid] = None
        best_score = -1.0
        candidate_grids: List[Tuple[float, StatementGrid]] = []
        for table in soup.find_all("table"):
            tbl_text = table.get_text(" ", strip=True)
            if not _table_overlaps_statement_text(table, merged_text):
                continue
            grid = build_grid_from_html_table(
                table,
                merged_text,
                stype,
                fiscal_calendar=fiscal_calendar,
                preferred_currency=preferred_currency,
            )
            if not grid or len(grid.period_ends) < 2:
                continue
            table_score = _score_html_table_text(tbl_text, stype, market_ctx)
            if table_score < 1_000:
                if (
                    market_ctx in {MarketContext.IFRS, MarketContext.ESEF}
                    and len(grid.rows) >= 4
                ):
                    table_score = 1_000.0
                else:
                    continue
            if not _grid_totals_appear_in_merged_text(grid, merged_text, stype):
                continue
            score = _html_grid_selection_score(grid, tbl_text, stype, market_ctx)
            candidate_grids.append((score, grid))
            if score > best_score:
                best_score = score
                best_grid = grid
        if market_ctx in {MarketContext.IFRS, MarketContext.ESEF} and candidate_grids:
            candidate_grids.sort(key=lambda item: item[0], reverse=True)
            if stype == "income":
                merge_pool = [grid for _, grid in candidate_grids[:4]]
            else:
                merge_pool = [grid for _, grid in candidate_grids[:6]]
            best_grid = _merge_statement_grids(merge_pool) or best_grid
        if best_grid:
            grids[stype] = best_grid
    return grids
