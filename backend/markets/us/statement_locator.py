"""三大报表页面定位：标准 10-K + ARS 年报 PDF（结构级，非按公司规则）。"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from backend.markets.us.statement_grid_extractor import _dedupe_stuttered_text

STANDARD_PATTERNS: Dict[str, List[str]] = {
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

# ARS / 年报 PDF 常见标题（无 "consolidated" 或标题在页内更深位置）
ARS_PATTERNS: Dict[str, List[str]] = {
    "income": [
        r"consolidated\s+statements?\s+of\s+operations",
        r"consolidated\s+statements?\s+of\s+profit\s+or\s+loss",
        r"consolidated\s+statement\s+of\s+profit\s+or\s+loss(?:\s+and\s+other\s+comprehensive\s+income)?",
        r"statement\s+of\s+profit\s+or\s+loss(?:\s+and\s+other\s+comprehensive\s+income)?",
        r"consolidated\s+statements?\s+of\s+comprehensive\s+income",
        r"consolidated\s+statements?\s+of\s+comprehensive\s+loss",
        r"consolidated\s+income\s+statements?",
        r"statements?\s+of\s+operations",
        r"statements?\s+of\s+earnings",
        r"statements?\s+of\s+income",
        r"statements?\s+of\s+comprehensive\s+income",
        r"statements?\s+of\s+comprehensive\s+loss",
    ],
    "balance": [
        r"consolidated\s+balance\s+sheets?",
        r"consolidated\s+statements?\s+of\s+financial\s+position",
        r"\bbalance\s+sheets?\b",
        r"statements?\s+of\s+financial\s+position",
    ],
    "cashflow": [
        r"consolidated\s+statements?\s+of\s+cash\s+flows?",
        r"statements?\s+of\s+cash\s+flows?",
        r"consolidated\s+cash\s+flow\s+statements?",
        r"\bcash\s+flows?\s+statements?\b",
    ],
}

INDEX_ZONE_MARKERS = [
    r"index to consolidated financial statements",
    r"index to financial statements",
    r"item 8\.\s*financial statements",
    r"financial statements and supplementary data",
    r"consolidated financial statements",
    r"audited financial statements",
]

AUDIT_REPORT_MARKERS = [
    r"we have audited the accompanying consolidated",
]

# 排除误匹配（审计意见、MD&A 引用）
# 仅检查页眉区，避免报表页脚 “see notes to …” 误排除
EXCLUDE_TITLE_ZONE_CHARS = 700
EXCLUDE_HEAD_PATTERNS = [
    r"report of independent registered public accounting firm",
    r"we have audited the accompanying consolidated",
    r"management'?s discussion and analysis",
    r"^notes to consolidated financial statements",
    r"proposal\s+(?:one|two|three|\d+)",
    r"shareholder proposal",
    r"changes in (?:shareholders?|stockholders?).? equity",
    r"statements of changes in",
    r"plan assets at fair value",
    r"pension and other postretirement",
]

# 仅用于页眉区判断：纯目录索引 vs 带 TOC 打印页眉的正文报表
_TOC_INDEX_MARKERS = re.compile(
    r"consolidated\s+\w+\s+\d{1,3}\s+consolidated|"
    r"financial statements\s+\d{1,3}\s+report of independent",
    re.I,
)
_MD_ANALYSIS_MARKERS = re.compile(
    r"following table presents|percentage relationship|"
    r"results of operations the following|the following table (?:presents|summarizes)",
    re.I,
)
_FISCAL_YEAR_HEAD = re.compile(
    r"(?:for the )?(?:fiscal )?years? ended|as of \w+ \d{1,2}, \d{4}|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2},?\s+\d{4}",
    re.I,
)
_STATEMENT_AMOUNT_MARKERS = re.compile(
    r"(?:\(in|expressed\s+in)\s+(?:millions|thousands)|"
    r"\(rmb\s+millions?\)|rmb[’']?000|人民幣千元|"
    r"all amounts in thousands|\$\s*[\d,]{3,}",
    re.I,
)

INCOME_TITLE_PATTERNS = [
    r"consolidated\s+statements?\s+of\s+operations",
    r"consolidated\s+statements?\s+of\s+earnings",
    r"consolidated\s+statements?\s+of\s+income",
    r"consolidated\s+income\s+statements?",
    r"\bincome\s+statements?\b",
    r"statements?\s+of\s+income\b",
    r"consolidated\s+statements?\s+of\s+profit\s+or\s+loss",
    r"consolidated\s+statement\s+of\s+profit\s+or\s+loss(?:\s+and\s+other\s+comprehensive\s+income)?",
    r"statement\s+of\s+profit\s+or\s+loss(?:\s+and\s+other\s+comprehensive\s+income)?",
    r"consolidated\s+statements?\s+of\s+comprehensive\s+income",
    r"consolidated\s+statements?\s+of\s+comprehensive\s+loss",
    r"comprehensive\s+income\s+statements?",
    r"statements?\s+of\s+comprehensive\s+income",
    r"statements?\s+of\s+comprehensive\s+loss",
]
BALANCE_TITLE_PATTERNS = [
    r"consolidated\s+balance\s+sheets?",
    r"consolidated\s+statements?\s+of\s+financial\s+position",
    r"\bbalance\s+sheets?\b",
    r"statements?\s+of\s+financial\s+position",
]
CASHFLOW_TITLE_PATTERNS = [
    r"consolidated\s+statements?\s+of\s+cash\s+flows?",
    r"statements?\s+of\s+cash\s+flows?",
    r"consolidated\s+cash\s+flow\s+statements?",
    r"cash\s+flows?\s+statements?",
]

# 弱标题仅用于 ARS Phase 2（避免 MD&A/脚注误匹配 balance sheet 等）
WEAK_PATTERNS: Dict[str, List[str]] = {
    "income": [r"\bincome\s+statements?\b"],
    "balance": [r"\bbalance\s+sheets?\b"],
    "cashflow": [r"\bcash\s+flows?\s+from\s+operating"],
}

STANDARD_MIN_SCORE = 8
ARS_MIN_SCORE = 4
HEAD_SCAN_CHARS = 2500
TITLE_ZONE_CHARS = 500


def normalize_page_text(text: str) -> str:
    """统一 ARS PDF 文本：stutter、点线、空白。"""
    cleaned = _dedupe_stuttered_text(text.replace("\xa0", " "))
    cleaned = re.sub(r"\.{3,}", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def financial_table_score(text: str) -> int:
    """表格数字密度（兼容无逗号、$ 前缀、点线分隔）。"""
    comma_nums = len(re.findall(r"\b\d{1,3}(?:,\d{3})+\b", text))
    dollar_nums = len(re.findall(r"\$\s*[\d,]+", text))
    paren_nums = len(re.findall(r"\(\s*[\d,]+\s*\)", text))
    plain_nums = len(re.findall(r"(?<![\d.])(\d{4,7})(?![\d])", text))
    return comma_nums * 2 + dollar_nums + paren_nums + min(plain_nums, 12)


def _head_excluded(head: str) -> bool:
    title_zone = head[:EXCLUDE_TITLE_ZONE_CHARS]
    if _is_toc_index_page(title_zone):
        return True
    return any(re.search(pat, title_zone) for pat in EXCLUDE_HEAD_PATTERNS)


def _is_toc_index_page(title_zone: str) -> bool:
    """纯目录页（列出页码），非带 TOC 页眉的正文报表。"""
    if not re.search(r"table of contents", title_zone[:400], re.I):
        return False
    if _STATEMENT_AMOUNT_MARKERS.search(title_zone[:700]):
        return False
    if _FISCAL_YEAR_HEAD.search(title_zone[:600]):
        return False
    if _TOC_INDEX_MARKERS.search(title_zone[:700]):
        return True
    if re.search(
        r"consolidated\s+(?:statements?\s+of\s+)?(?:operations|earnings|income|balance\s+sheets?|cash\s+flows?)",
        title_zone[:500],
        re.I,
    ):
        return False
    return True


def _strip_page_header_noise(text: str) -> str:
    """去掉 ARS PDF 页眉中的页码、公司名、annual report 水印。"""
    cleaned = text.strip()
    cleaned = re.sub(r"^\d+\s+", "", cleaned)
    cleaned = re.sub(r"^annual report\s+\d{4}\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(
        r"^[\w.,\s&'/-]+\b(?:inc\.?|ltd\.?|limited|group|holdings|corp\.?|co\.?)\b\.?\s+\d*\s*",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"^[\w.,\s]+\binc\.?\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^\d+\s+", "", cleaned)
    return cleaned.strip()


def _is_annual_report_page_header(before: str) -> bool:
    """港股/IFRS 年报常见页眉（公司名 + Annual Report + 页码）。"""
    text = before.strip().lower()
    if not text or len(text) <= 20:
        return True
    return bool(
        re.fullmatch(
            r"(?:\d+\s+)?(?:annual report\s+\d{4}\s+)?(?:\d+\s+)?"
            r"[\w\s&.,'()/-]+(?:limited|ltd\.?|inc\.?|group|holdings|corp\.?|co\.?)?"
            r"(?:\s+financial statements)?\s*\d*",
            text,
            re.I,
        )
    )


def _is_report_section_page(prefix: str) -> bool:
    """董事报告/管治报告/目录概览等非报表页。"""
    return bool(
        re.search(
            r"report of directors|directors.? report|corporate governance report|"
            r"major customers and suppliers|financial and operating review|"
            r"\boverview\b.{0,40}\bfinancial statements\b",
            prefix[:500],
            re.I,
        )
    )


def _is_md_analysis_page(prefix: str) -> bool:
    return bool(
        _MD_ANALYSIS_MARKERS.search(prefix[:550])
        or re.search(
            r"reportable business segments|segment.{0,24}results|"
            r"consolidated balance sheets.{0,30}analysis|balance sheets analysis|"
            r"balance sheet classification",
            prefix[:600],
            re.I,
        )
    )


def _statement_title_near_head(prefix: str, patterns: List[str], max_pos: int = 220) -> Optional[re.Match]:
    """标题须出现在页眉区（允许 SEC HTML 的 table of contents 打印页眉）。"""
    scan = re.sub(r"^table of contents\s+", "", prefix[: max_pos + 120], flags=re.I)
    best: Optional[re.Match] = None
    for pat in patterns:
        m = re.search(pat, scan[: max_pos + 80], re.I)
        if not m or not _valid_statement_title(scan, m):
            continue
        if m.start() > max_pos:
            continue
        if best is None or m.start() < best.start():
            best = m
    return best


def _patterns_without_weak(patterns_map: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for stype, patterns in patterns_map.items():
        weak = set(WEAK_PATTERNS.get(stype, []))
        filtered = [p for p in patterns if p not in weak]
        if filtered:
            out[stype] = filtered
    return out


def _valid_statement_title(head: str, match: re.Match) -> bool:
    """排除脚注中对报表名的引用（如 “statements of operations in the period …”）。"""
    tail = head[match.end() : match.end() + 48]
    if re.match(
        r"\s*(?:in the|in which|are presented|included in|see notes|within the|of \$|of \d+\s+million|until\b)\b",
        tail,
    ):
        return False
    if match.start() > TITLE_ZONE_CHARS and not re.match(
        r"\s*(?:\n|for the (?:fiscal )?years|for the year|as of|\(|—|-|\(in millions|\(dollars)",
        tail,
        re.I,
    ):
        return False
    return True


def _title_match(head: str, patterns: List[str]) -> Optional[Tuple[int, int]]:
    """返回 (match_pos, strength)；strength 越高表示标题越明确。"""
    best: Optional[Tuple[int, int]] = None
    for pat in patterns:
        m = re.search(pat, head[:HEAD_SCAN_CHARS])
        if not m or not _valid_statement_title(head, m):
            continue
        if re.search(r"balance sheet classification", head[m.start() : m.end() + 24], re.I):
            continue
        strength = 3 if "consolidated" in pat else (2 if r"\b" not in pat[:3] else 1)
        pos = m.start()
        if best is None or strength > best[1] or (strength == best[1] and pos < best[0]):
            best = (pos, strength)
    return best


def _composite_score(table_score: int, title_pos: int, title_strength: int) -> int:
    title_bonus = max(0, TITLE_ZONE_CHARS - title_pos) // 2
    return table_score + title_bonus + title_strength * 50


def _collect_candidates(
    pages: List[str],
    patterns_map: Dict[str, List[str]],
    page_range: Optional[Tuple[int, int]] = None,
    min_score: int = STANDARD_MIN_SCORE,
    allow_weak_titles: bool = False,
) -> Dict[str, List[Tuple[int, int]]]:
    start, end = page_range if page_range else (0, len(pages))
    active_patterns = patterns_map if allow_weak_titles else _patterns_without_weak(patterns_map)
    candidates: Dict[str, List[Tuple[int, int]]] = {k: [] for k in active_patterns}

    for page_num in range(start, min(end, len(pages))):
        raw = pages[page_num]
        normalized = normalize_page_text(raw)
        head = normalized.lower()[:HEAD_SCAN_CHARS]
        if _head_excluded(head):
            continue
        table_score = financial_table_score(normalized)
        if table_score < min_score:
            continue
        for stype, patterns in active_patterns.items():
            title = _title_match(head, patterns)
            if not title:
                continue
            if not _validate_statement_page(raw, stype):
                continue
            pos, strength = title
            candidates[stype].append(
                (page_num, _composite_score(table_score, pos, strength))
            )
    return candidates


def _pick_best(
    candidates: Dict[str, List[Tuple[int, int]]],
    pages: Optional[List[str]] = None,
) -> Dict[str, int]:
    found: Dict[str, int] = {}
    for stype, hits in candidates.items():
        if not hits:
            continue
        max_score = max(score for _, score in hits)
        threshold = max_score * 0.92
        top = [(page, score) for page, score in hits if score >= threshold]

        def _rank(page: int) -> Tuple[int, int, int, int]:
            notes_like = 0
            continuation = 0
            oci_only = 0
            if pages and page < len(pages):
                head = normalize_page_text(pages[page])[:500].lower()
                body = normalize_page_text(pages[page])[:3000].lower()
                if re.search(r"notes to (?:the )?consolidated financial statements", head):
                    notes_like = 1
                if _STATEMENT_TITLE_HEAD_RE.search(head):
                    continuation = 0
                elif stype == "income":
                    continuation = 1
                elif stype == "balance":
                    continuation = 1
                if stype == "income" and re.search(r"comprehensive\s+income", head):
                    if not re.search(
                        r"\b(?:revenues?|net sales|cost of revenue|gross profit|total operating income)\b",
                        body,
                    ):
                        oci_only = 1
            return (notes_like, continuation, oci_only, page)

        found[stype] = min(top, key=lambda h: _rank(h[0]))[0]
    return found


def _index_search_ranges(pages: List[str]) -> List[Tuple[int, int]]:
    ranges: List[Tuple[int, int]] = []
    normalized = [normalize_page_text(p).lower() for p in pages]
    index_pages = [
        i
        for i, text in enumerate(normalized)
        if any(re.search(marker, text[:3000]) for marker in INDEX_ZONE_MARKERS)
    ]
    if index_pages:
        anchor = min(index_pages)
        ranges.append((max(0, anchor - 2), min(len(pages), anchor + 130)))
    for i, text in enumerate(normalized):
        if any(re.search(marker, text[:3500]) for marker in AUDIT_REPORT_MARKERS):
            ranges.append((i, min(len(pages), i + 15)))
    if len(pages) >= 30:
        tail_start = (len(pages) * 2) // 3
        ranges.append((tail_start, len(pages)))
    return ranges


def _page_prefix(page_text: str, chars: int = 800) -> str:
    return normalize_page_text(page_text).lower()[:chars]


_STATEMENT_TITLE_HEAD_RE = re.compile(
    r"consolidated (?:statements? of (?:comprehensive income|profit|operations)|income statements?)"
    r"|consolidated statement of financial position|consolidated balance sheet",
    re.I,
)

_SUMMARY_STATEMENT_RE = re.compile(
    r"selected consolidated|financial highlights|five[- ]year|"
    r"index to the consolidated financial|\bfinancial summary\b|"
    r"summary consolidated|"
    r"condensed consolidated statement(?!\s+of\s+cash\s+flows?)",
    re.I,
)


_SEGMENT_TABLE_RE = re.compile(
    r"major vies|eliminations|parent company only|revenue from third parties",
    re.I,
)
_NOTES_PRIMARY_RE = re.compile(
    r"^notes to consolidated financial statements",
    re.I,
)


def _is_notes_financial_statement_page(prefix: str) -> bool:
    """附注区 condensed / 母公司报表，非主表。"""
    notes_pos = re.search(
        r"notes to (?:the )?consolidated financial statements",
        prefix[:450],
        re.I,
    )
    stmt_pos = re.search(
        r"consolidated statement of (?:comprehensive income|profit|financial position|cash flows)",
        prefix[:450],
        re.I,
    )
    if notes_pos and (stmt_pos is None or notes_pos.start() < stmt_pos.start()):
        return True
    if re.search(r"notes to consolidated financial statements", prefix[:500], re.I):
        return True
    if re.search(r"notes to the consolidated financial statements", prefix[:500], re.I):
        if re.search(
            r"financial position (?:and .{0,80} )?of the company|"
            r"statement of financial position of the company",
            prefix[:900],
            re.I,
        ):
            return True
        if re.search(
            r"segment reporting|\b\d{1,3}\.\s+[a-z]|summary of significant",
            prefix[:600],
            re.I,
        ):
            return True
    if re.search(r"\bcondensed\s+statements?\s+of\s+comprehensive", prefix[:600], re.I):
        return True
    if re.search(
        r"\bcondensed consolidated statement(?!\s+of\s+cash\s+flows?)",
        prefix[:600],
        re.I,
    ):
        return True
    if re.search(r"statement of financial position of the company", prefix[:600], re.I):
        return True
    return False


def _validate_statement_page(page_text: str, stype: str) -> bool:
    """已定位页是否像真实报表（非脚注/MD&A/目录引用）。"""
    prefix = _page_prefix(page_text, 900)
    cf_body = _page_prefix(page_text, 4000) if stype == "cashflow" else prefix
    if _is_notes_financial_statement_page(prefix):
        return False
    if re.search(r"^note\s+\d+", prefix[:120]):
        return False
    if re.search(r"^notes to consolidated financial statements", prefix[:250], re.I):
        return False
    if re.search(r"reconciliation of consolidated", prefix[:350], re.I):
        return False
    if _is_md_analysis_page(prefix):
        return False
    if _is_report_section_page(prefix):
        return False
    if re.search(r"^\d{1,3}\.\s+[a-z]", prefix[:200]):
        return False
    if _SUMMARY_STATEMENT_RE.search(prefix[:500]):
        return False
    if _SEGMENT_TABLE_RE.search(prefix[:700]):
        return False
    if stype == "income":
        title = _statement_title_near_head(prefix, INCOME_TITLE_PATTERNS)
        if title:
            title_text = prefix[title.start() : title.start() + 120]
            if re.search(r"comprehensive (?:income|loss)", prefix[:120], re.I) and not re.search(
                r"operations|earnings", prefix[:120], re.I
            ):
                if not re.search(
                    r"statements?\s+of\s+comprehensive\s+(?:income|loss)|"
                    r"statement of profit or loss and other comprehensive income",
                    title_text,
                    re.I,
                ):
                    return False
            tail = prefix[title.start() : title.start() + 320]
            return bool(
                _STATEMENT_AMOUNT_MARKERS.search(tail)
                or _FISCAL_YEAR_HEAD.search(tail)
                or re.search(
                    r"\b(?:revenue|net sales|interest income|net interest income|net loss|total revenues?)s?\b",
                    tail,
                    re.I,
                )
            )
        return bool(
            _FISCAL_YEAR_HEAD.search(prefix[:280])
            and re.search(r"\b(?:revenue|net sales)s?\b", prefix[:600], re.I)
            and re.search(
                r"consolidated (?:statements?|income statements?)|"
                r"statement of (?:profit|comprehensive|operations)|"
                r"\bincome\s+statements?\b",
                prefix[:500],
                re.I,
            )
            and "operating activities" not in prefix[:400]
            and "other comprehensive income" not in prefix[:350]
            and "preferred stock balance" not in prefix[:350]
        )
    if stype == "balance":
        if re.search(r"notes to (?:the )?consolidated financial statements", prefix[:450], re.I):
            if not re.search(
                r"consolidated (?:balance sheets?|statement of financial position)",
                prefix[:500],
                re.I,
            ):
                return False
        if _NOTES_PRIMARY_RE.search(prefix[:200]) and not re.search(
            r"consolidated balance sheets?|statement of financial position",
            prefix[:400],
            re.I,
        ):
            return False
        if re.search(r"selected balance sheet|selected metrics|financial highlights|three-year summary", prefix[:400]):
            return False
        if re.search(r"balance sheet classification", prefix[:300], re.I):
            return False
        title = _statement_title_near_head(prefix, BALANCE_TITLE_PATTERNS, max_pos=160)
        if title:
            before = _strip_page_header_noise(prefix[: title.start()])
            if before and re.search(
                r"\b(?:impact of|following table|reflected on|analysis of|discussed in|percentage relationship)\b",
                before,
            ):
                return False
            if before and not _is_annual_report_page_header(before):
                if not re.search(r"^table of contents\b", before):
                    return False
            tail = prefix[title.start() : title.start() + 400]
            return bool(
                _STATEMENT_AMOUNT_MARKERS.search(tail)
                or _FISCAL_YEAR_HEAD.search(tail)
                or re.search(r"\b(?:assets|liabilities|equity)\b", tail, re.I)
            )
        return bool(
            (
                _FISCAL_YEAR_HEAD.search(prefix[:220])
                or re.search(r"december 31,|september 30,|january 31,|february \d{1,2},", prefix[:140], re.I)
            )
            and re.search(r"\bassets\b", prefix[:280])
            and re.search(
                r"cash and due from|deposits with banks|cash and cash equivalents|total assets|current assets",
                prefix[:700],
            )
            and "plan assets at fair value" not in prefix[:400]
        )
    if stype == "cashflow":
        if re.search(r"half[- ]year report|six months ended|interim financial", prefix[:350], re.I):
            return False
        if re.search(r"company cash flow statement", prefix[:350], re.I):
            return False
        if re.search(r"holdings statement of cash flows", prefix[:350], re.I):
            return False
        title = _statement_title_near_head(prefix, CASHFLOW_TITLE_PATTERNS, max_pos=220)
        if title:
            if "parent company" in prefix[:450]:
                return False
            tail = prefix[title.start() : title.start() + 400]
            activity_hit = bool(
                re.search(r"operating activities", tail, re.I)
                or re.search(r"net cash from operations", tail, re.I)
                or re.search(r"\boperations\b", tail, re.I)
                or (
                    re.search(r"profit before tax", tail, re.I)
                    and re.search(r"adjustments", tail, re.I)
                )
            )
            return bool(
                activity_hit
                and (
                    _STATEMENT_AMOUNT_MARKERS.search(tail)
                    or _FISCAL_YEAR_HEAD.search(tail)
                )
            )
        return bool(
            (
                _FISCAL_YEAR_HEAD.search(prefix[:280])
                or (
                    re.search(r"profit before tax", prefix[:500], re.I)
                    and len(re.findall(r"\b\d{1,3}(?:,\d{3})+\b", prefix[:700])) >= 6
                )
            )
            and (
                re.search(r"operating activities", prefix[:500], re.I)
                or re.search(r"net cash from operations", prefix[:500], re.I)
                or (
                    re.search(r"profit before tax", prefix[:500], re.I)
                    and re.search(r"adjustments", prefix[:500], re.I)
                    and re.search(r"net cash from operating", cf_body, re.I)
                )
                or (
                    re.search(r"\boperations\b", prefix[:500], re.I)
                    and re.search(r"net income", prefix[:600], re.I)
                )
            )
            and "parent company" not in prefix[:450]
            and "changes in equity" not in prefix[:350]
        )
    return False


def _untitled_block_score(page_text: str, stype: str) -> int:
    prefix = _page_prefix(page_text, 900)
    cf_body = _page_prefix(page_text, 4000) if stype == "cashflow" else prefix
    if not _validate_statement_page(page_text, stype):
        return 0
    table = financial_table_score(normalize_page_text(page_text))
    bonus = 0
    if stype == "income" and re.search(r"\brevenue\b", prefix[:400]):
        bonus += 80
    if stype == "income" and re.search(r"total\s+(?:net\s+)?(?:revenues?|sales)", prefix[:900], re.I):
        bonus += 120
    if stype == "balance" and re.search(r"total assets", prefix):
        bonus += 80
    if stype == "balance" and re.search(r"current assets", prefix[:500], re.I):
        bonus += 60
    if stype == "cashflow" and re.search(
        r"adjustments to reconcile net income|net cash from operating activities",
        cf_body,
        re.I,
    ):
        bonus += 80
    if stype == "cashflow" and re.search(
        r"profit before tax", prefix[:500], re.I
    ) and re.search(r"net cash from operating activities", cf_body, re.I):
        bonus += 150
    return table + bonus


def _locate_untitled_blocks(
    pages: List[str],
    page_ranges: List[Tuple[int, int]],
    missing: List[str],
) -> Dict[str, int]:
    found: Dict[str, int] = {}
    for stype in missing:
        best_page = -1
        best_score = 0
        for start, end in page_ranges:
            for page_num in range(start, min(end, len(pages))):
                if _head_excluded(_page_prefix(pages[page_num], EXCLUDE_TITLE_ZONE_CHARS)):
                    continue
                score = _untitled_block_score(pages[page_num], stype)
                if score > best_score:
                    best_score = score
                    best_page = page_num
        if best_page >= 0 and best_score >= 40:
            found[stype] = best_page
    return found


def locate_statements_from_pages(pages: List[str]) -> Dict[str, int]:
    """定位 income / balance / cashflow 页码。"""
    if not pages:
        return {}

    # Phase 1: 标准 10-K 标题 + 高密度数字
    standard = _collect_candidates(
        pages,
        STANDARD_PATTERNS,
        min_score=STANDARD_MIN_SCORE,
    )
    found = _pick_best(standard, pages)
    if len(found) >= 3:
        return found

    # Phase 2: ARS — 在 index 区或文档尾部用扩展标题 + 较低数字阈值
    missing = [k for k in ("income", "balance", "cashflow") if k not in found]
    if not missing:
        return found

    for page_range in _index_search_ranges(pages):
        ars = _collect_candidates(
            pages,
            ARS_PATTERNS,
            page_range=page_range,
            min_score=ARS_MIN_SCORE,
            allow_weak_titles=True,
        )
        for stype in missing:
            if stype in ars and ars[stype]:
                picked = _pick_best({stype: ars[stype]}, pages)
                if stype in picked and stype not in found:
                    found[stype] = picked[stype]
        missing = [k for k in ("income", "balance", "cashflow") if k not in found]
        if not missing:
            break

    # 校验 Phase 1/2 结果，剔除脚注/母公司报表误匹配
    for stype in list(found.keys()):
        if not _validate_statement_page(pages[found[stype]], stype):
            del found[stype]

    missing = [k for k in ("income", "balance", "cashflow") if k not in found]
    if missing:
        untitled = _locate_untitled_blocks(pages, _index_search_ranges(pages), missing)
        found.update(untitled)

    return found
