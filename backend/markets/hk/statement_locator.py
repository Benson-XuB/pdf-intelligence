"""港股 / IFRS 年报三大报表定位（扩展 US locator，非 ticker 特例）。"""

from __future__ import annotations

import re
from typing import Dict, List

from backend.markets.us.statement_locator import (
    ARS_PATTERNS,
    locate_statements_from_pages,
    normalize_page_text,
    _collect_candidates,
    _head_excluded,
    _index_search_ranges,
    _pick_best,
    _validate_statement_page,
)

# IFRS / 港股双语标题（并入 ARS 搜索）
HK_IFRS_PATTERNS: Dict[str, List[str]] = {
    "income": [
        r"statements?\s+of\s+profit\s+or\s+loss",
        r"consolidated\s+statements?\s+of\s+profit\s+or\s+loss",
        r"consolidated\s+statements?\s+of\s+comprehensive\s+income",
        r"consolidated\s+statements?\s+of\s+comprehensive\s+loss",
        r"consolidated\s+income\s+statements?",
        r"consolidated statement of profit or loss and other comprehensive income",
        r"statement of profit or loss and other comprehensive income",
        r"statement\s+of\s+comprehensive\s+income",
        r"statement\s+of\s+comprehensive\s+loss",
        r"综合(?:收益|损益)(?:表|/(?:亏损))?",
        r"损益表",
        r"利润表",
        r"合并(?:综合)?(?:收益|损益)表",
    ],
    "balance": [
        r"statements?\s+of\s+financial\s+position",
        r"consolidated\s+statements?\s+of\s+financial\s+position",
        r"综合(?:财务)?状况表",
        r"资产负债表",
        r"资产(?:负债|及负债)表",
    ],
    "cashflow": [
        r"statements?\s+of\s+cash\s+flows?",
        r"consolidated\s+statements?\s+of\s+cash\s+flows?",
        r"consolidated\s+cash\s+flow\s+statements?",
        r"合[併并]現金流量表",
        r"综合现金流量表",
        r"现金流量表",
        r"合并现金流量表",
        r"holdings\s+statement\s+of\s+cash\s+flows?",
    ],
}

HK_SUMMARY_PAGE_RE = re.compile(
    r"selected consolidated|financial highlights|five[- ]year|"
    r"\bpart i\b|\bpart ii\b|index to the consolidated financial|"
    r"business review|management discussion|\bfinancial summary\b|"
    r"summary consolidated|"
    r"condensed consolidated statement(?!\s+of\s+cash\s+flows?)",
    re.I,
)


def _hk_validate_statement_page(page_text: str, stype: str) -> bool:
    prefix = normalize_page_text(page_text).lower()[:900]
    if HK_SUMMARY_PAGE_RE.search(prefix[:500]):
        return False
    return _validate_statement_page(page_text, stype)


def _merge_pattern_maps(*maps: Dict[str, List[str]]) -> Dict[str, List[str]]:
    merged: Dict[str, List[str]] = {}
    for m in maps:
        for stype, patterns in m.items():
            merged.setdefault(stype, [])
            seen = set(merged[stype])
            for pat in patterns:
                if pat not in seen:
                    merged[stype].append(pat)
                    seen.add(pat)
    return merged


def locate_hk_statements_from_pages(pages: List[str]) -> Dict[str, int]:
    """定位港股年报 income / balance / cashflow 页码。"""
    if not pages:
        return {}

    found = locate_statements_from_pages(pages)
    for stype in list(found.keys()):
        if not _hk_validate_statement_page(pages[found[stype]], stype):
            del found[stype]

    missing = [k for k in ("income", "balance", "cashflow") if k not in found]
    if not missing:
        return found

    patterns = _merge_pattern_maps(ARS_PATTERNS, HK_IFRS_PATTERNS)
    for page_range in _index_search_ranges(pages):
        candidates = _collect_candidates(
            pages,
            patterns,
            page_range=page_range,
            min_score=4,
            allow_weak_titles=True,
        )
        for stype in missing:
            hits = candidates.get(stype, [])
            valid_hits = [
                (page, score)
                for page, score in hits
                if _hk_validate_statement_page(pages[page], stype)
            ]
            if not valid_hits:
                continue
            best_page = max(valid_hits, key=lambda x: x[1])[0]
            if stype not in found:
                found[stype] = best_page
        missing = [k for k in ("income", "balance", "cashflow") if k not in found]
        if not missing:
            break

    if missing:
        found.update(_locate_hk_fallback(pages, missing))
    return found


def _locate_hk_fallback(pages: List[str], missing: List[str]) -> Dict[str, int]:
    """按 IFRS 中文/英文标题 + 数字密度兜底。"""
    candidates: Dict[str, List[tuple[int, int]]] = {k: [] for k in missing}
    for page_num, raw in enumerate(pages):
        head = normalize_page_text(raw).lower()[:1200]
        if _head_excluded(head):
            continue
        if HK_SUMMARY_PAGE_RE.search(head[:500]):
            continue
        num_score = len(re.findall(r"\b\d{1,3}(?:,\d{3})+\b", raw))
        for stype in missing:
            for pat in HK_IFRS_PATTERNS.get(stype, []):
                if re.search(pat, head, re.I) and _hk_validate_statement_page(raw, stype):
                    candidates[stype].append((page_num, num_score))
                    break

    found: Dict[str, int] = {}
    for stype, hits in candidates.items():
        if hits:
            found[stype] = max(hits, key=lambda x: x[1])[0]
    return found
