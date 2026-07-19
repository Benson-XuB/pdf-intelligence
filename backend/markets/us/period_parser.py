from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

MONTH_MAP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

MONTH_NAME = (
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)

PERIOD_DATE_RE = re.compile(
    rf"{MONTH_NAME}\s+(\d{{1,2}}),?\s+(20\d{{2}})",
    re.IGNORECASE,
)

PERIOD_DATE_FLEX_RE = re.compile(
    rf"{MONTH_NAME}\s+(\d{{1,2}}),?\s*(?:\n\s*)?(20\d{{2}})",
    re.IGNORECASE,
)

# 港股 / IFRS 常见列头
CN_PERIOD_ENDED_RE = re.compile(
    r"截至\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
)
CN_DATE_RE = re.compile(
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
)
EN_DAY_MONTH_YEAR_RE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StatementPeriod:
    period_end: str
    label: str
    year: int


def _month_num(month_name: str) -> int:
    key = month_name.lower()
    if key in MONTH_MAP:
        return MONTH_MAP[key]
    short = key[:3]
    if short in MONTH_MAP:
        return MONTH_MAP[short]
    raise KeyError(f"Unknown month: {month_name}")


def _to_iso(month_name: str, day: int, year: int) -> str:
    month = _month_num(month_name)
    last_day = calendar.monthrange(year, month)[1]
    safe_day = min(day, last_day)
    return datetime(year, month, safe_day).strftime("%Y-%m-%d")


def _dedupe_years(years: List[str]) -> List[str]:
    seen: List[str] = []
    for year in years:
        if year not in seen:
            seen.append(year)
    return seen


def _periods_from_dates(matches: List[re.Match]) -> List[StatementPeriod]:
    seen: List[StatementPeriod] = []
    seen_ends: set[str] = set()
    for match in matches:
        month, day, year = match.group(1), int(match.group(2)), int(match.group(3))
        period_end = _to_iso(month, day, year)
        if period_end in seen_ends:
            continue
        seen_ends.add(period_end)
        seen.append(
            StatementPeriod(
                period_end=period_end,
                label=match.group(0).strip(),
                year=year,
            )
        )
    return seen


def _periods_from_cn_matches(matches: List[re.Match]) -> List[StatementPeriod]:
    seen: List[StatementPeriod] = []
    seen_ends: set[str] = set()
    for match in matches:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        period_end = _to_iso_from_nums(year, month, day)
        if period_end in seen_ends:
            continue
        seen_ends.add(period_end)
        seen.append(
            StatementPeriod(
                period_end=period_end,
                label=match.group(0).strip(),
                year=year,
            )
        )
    return seen


def _to_iso_from_nums(year: int, month: int, day: int) -> str:
    last_day = calendar.monthrange(year, month)[1]
    safe_day = min(day, last_day)
    return datetime(year, month, safe_day).strftime("%Y-%m-%d")


def _periods_from_en_dmy(matches: List[re.Match]) -> List[StatementPeriod]:
    seen: List[StatementPeriod] = []
    seen_ends: set[str] = set()
    for match in matches:
        day = int(match.group(1))
        month_name = match.group(2)
        year = int(match.group(3))
        period_end = _to_iso(month_name, day, year)
        if period_end in seen_ends:
            continue
        seen_ends.add(period_end)
        seen.append(
            StatementPeriod(
                period_end=period_end,
                label=match.group(0).strip(),
                year=year,
            )
        )
    return seen


def _parse_year_column_block(head: str, max_periods: int) -> List[StatementPeriod]:
    anchor = re.search(
        rf"Year Ended[\s\S]{{0,80}}{MONTH_NAME}\s+(\d{{1,2}}),?",
        head,
        re.IGNORECASE,
    )
    if not anchor:
        anchor = re.search(rf"{MONTH_NAME}\s+(\d{{1,2}}),", head, re.IGNORECASE)
    if not anchor:
        return []

    month_name = anchor.group(1)
    day = int(anchor.group(2))
    tail = head[anchor.end() : anchor.end() + 400]
    years = _dedupe_years(re.findall(r"\b(20\d{2})\b", tail))
    if len(years) < 2:
        return []

    return [
        StatementPeriod(
            period_end=_to_iso(month_name, day, int(year)),
            label=f"{month_name} {day}, {year}",
            year=int(year),
        )
        for year in years[:max_periods]
    ]


def is_opening_balance_period(period_end: str) -> bool:
    """资产负债表中的 Jan 1–3 通常是期初/比较列，不是财年结束日。"""
    try:
        month = int(period_end[5:7])
        day = int(period_end[8:10])
    except (ValueError, IndexError):
        return False
    return month == 1 and day <= 3


def resolve_balance_periods(
    balance_periods: List[StatementPeriod],
    income_periods: List[StatementPeriod],
    max_periods: int,
) -> List[StatementPeriod]:
    """资产负债表页眉常缺少年份列；期初日期列用利润表列头对齐。"""
    if income_periods:
        has_opening = any(is_opening_balance_period(p.period_end) for p in balance_periods)
        if has_opening or len(balance_periods) < 2:
            return income_periods[:max_periods]

    cleaned = [p for p in balance_periods if not is_opening_balance_period(p.period_end)]
    if len(cleaned) >= 2:
        return cleaned[:max_periods]
    if income_periods:
        return income_periods[:max_periods]
    return balance_periods[:max_periods]


COMMON_FISCAL_MONTH_DAYS = frozenset({(12, 31), (3, 31), (6, 30), (9, 30)})


def filter_reporting_periods(periods: List[StatementPeriod]) -> List[StatementPeriod]:
    """去掉公告日期、期初列等非财年列（如 HSBC 封面上的 February 19, 2025）。"""
    if len(periods) < 2:
        return periods
    non_opening = [p for p in periods if not is_opening_balance_period(p.period_end)]
    common = [
        p
        for p in non_opening
        if (int(p.period_end[5:7]), int(p.period_end[8:10])) in COMMON_FISCAL_MONTH_DAYS
    ]
    if len(common) >= 2:
        return common
    if len(non_opening) >= 2:
        return non_opening
    return []


def parse_statement_periods(page_text: str, max_periods: int = 5) -> List[StatementPeriod]:
    """从报表页眉解析按列顺序排列的期间（与 PDF 列顺序一致）。"""
    head = page_text[:3000]
    column_periods = _parse_year_column_block(head, max_periods)
    column_filtered = filter_reporting_periods(column_periods) if column_periods else []

    for parser in (PERIOD_DATE_RE, PERIOD_DATE_FLEX_RE):
        matches = list(parser.finditer(head))
        periods = _periods_from_dates(matches)
        filtered = filter_reporting_periods(periods)
        if len(filtered) >= 2:
            if column_filtered and max(p.year for p in column_filtered) > max(
                p.year for p in filtered
            ):
                return column_filtered[:max_periods]
            return filtered[:max_periods]

    cn_matches = list(CN_PERIOD_ENDED_RE.finditer(head)) or list(CN_DATE_RE.finditer(head))
    cn_periods = _periods_from_cn_matches(cn_matches)
    filtered = filter_reporting_periods(cn_periods)
    if len(filtered) >= 2:
        if column_filtered and max(p.year for p in column_filtered) > max(
            p.year for p in filtered
        ):
            return column_filtered[:max_periods]
        return filtered[:max_periods]

    en_dmy = list(EN_DAY_MONTH_YEAR_RE.finditer(head))
    en_periods = _periods_from_en_dmy(en_dmy)
    filtered = filter_reporting_periods(en_periods)
    if len(filtered) >= 2:
        if column_filtered and max(p.year for p in column_filtered) > max(
            p.year for p in filtered
        ):
            return column_filtered[:max_periods]
        return filtered[:max_periods]

    if column_filtered:
        return column_filtered[:max_periods]

    years = _dedupe_years(re.findall(r"\b(20\d{2})\b", head[:1000]))
    if years:
        return [
            StatementPeriod(period_end=f"{year}-12-31", label=year, year=int(year))
            for year in years[:max_periods]
        ]
    return []


def align_periods_to_xbrl(
    pdf_periods: List[StatementPeriod],
    xbrl_period_ends: List[str],
) -> Dict[str, int]:
    """把 XBRL period_end 映射到 PDF 列索引。"""
    mapping: Dict[str, int] = {}
    pdf_by_end = {p.period_end: idx for idx, p in enumerate(pdf_periods)}
    pdf_years = {p.year: idx for idx, p in enumerate(pdf_periods)}

    for period_end in xbrl_period_ends:
        if period_end in pdf_by_end:
            mapping[period_end] = pdf_by_end[period_end]
            continue
        year = int(period_end[:4])
        if year in pdf_years:
            mapping[period_end] = pdf_years[year]
    return mapping


def is_fiscal_period_end(period_end: str) -> bool:
    try:
        month = int(period_end[5:7])
        day = int(period_end[8:10])
    except (ValueError, IndexError):
        return False
    return (month, day) in COMMON_FISCAL_MONTH_DAYS


def canonicalize_period_ends(periods: List[str], max_periods: int = 3) -> List[str]:
    """合并同一年内的公告日/期初列，保留财年结束日。"""
    if not periods:
        return []

    by_year: Dict[str, List[str]] = {}
    for period in periods:
        by_year.setdefault(period[:4], []).append(period)

    canonical: List[str] = []
    for year in sorted(by_year.keys(), reverse=True):
        candidates = by_year[year]
        fiscal = [p for p in candidates if is_fiscal_period_end(p)]
        if fiscal:
            canonical.append(sorted(fiscal, reverse=True)[0])
            continue
        non_opening = [p for p in candidates if not is_opening_balance_period(p)]
        if non_opening:
            canonical.append(sorted(non_opening, reverse=True)[0])
        else:
            canonical.append(f"{year}-12-31")

    return canonical[:max_periods]


def canonical_period_for_year(period_end: str, canonical_periods: List[str]) -> Optional[str]:
    year = period_end[:4]
    for period in canonical_periods:
        if period.startswith(year):
            return period
    return None


def normalize_pdf_financials_periods(
    periods: List[str],
    values: List["FieldValue"],
    max_periods: int = 3,
) -> tuple[List[str], List["FieldValue"]]:
    """把公告日/期初列归并到财年结束日，避免 PDF-only verify 被假期间拉低。"""
    from backend.global_schema.models import FieldValue

    raw = list(periods or []) + [v.period_end for v in values if v.value is not None]
    canonical = canonicalize_period_ends(raw, max_periods)
    if not canonical:
        return periods, values

    remapped: Dict[tuple[str, str], FieldValue] = {}
    for item in values:
        if item.value is None:
            continue
        target = canonical_period_for_year(item.period_end, canonical)
        if not target:
            continue
        key = (item.field_id, target)
        candidate = FieldValue(
            field_id=item.field_id,
            period_end=target,
            fiscal_year=int(target[:4]),
            value=item.value,
            currency=item.currency,
            scale=item.scale,
            standard=item.standard,
            source=item.source,
            source_tag=item.source_tag,
            source_form=item.source_form,
            filed_date=item.filed_date,
            pdf_verified=item.pdf_verified,
        )
        existing = remapped.get(key)
        if existing is None:
            remapped[key] = candidate
        elif is_fiscal_period_end(item.period_end) and not is_fiscal_period_end(existing.period_end):
            remapped[key] = candidate
    return canonical, list(remapped.values())
