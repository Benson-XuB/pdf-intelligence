"""European ESEF / IFRS inline XHTML statement locator."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from backend.markets.hk.statement_locator import HK_IFRS_PATTERNS, HK_SUMMARY_PAGE_RE, _merge_pattern_maps
from backend.markets.us.statement_locator import (
    ARS_PATTERNS,
    CASHFLOW_TITLE_PATTERNS,
    HEAD_SCAN_CHARS,
    INCOME_TITLE_PATTERNS,
    _composite_score,
    _head_excluded,
    _index_search_ranges,
    _page_prefix,
    _patterns_without_weak,
    _statement_title_near_head,
    financial_table_score,
    locate_statements_from_pages,
    normalize_page_text,
)

ESEF_FRENCH_PATTERNS: Dict[str, List[str]] = {
    "income": [
        r"compte de r[eé]sultat(?:s)? consolid[eé]",
        r"état du r[eé]sultat global consolid[eé]",
        r"compte de r[eé]sultat consolid[eé] de l.?exercice",
        r"compte de r[eé]sultats consolid[eé]",
    ],
    "balance": [
        r"bilan consolid[eé]",
        r"état de la situation financi[eè]re consolid[eé]",
        r"bilan consolid[eé]\s+actif",
    ],
    "cashflow": [
        r"tableau des flux de tr[eé]sorerie(?:\s+consolid[eé])?",
        r"tableau de variation de la tr[eé]sorerie(?:\s+consolid[eé])?",
    ],
}

ESEF_IFRS_PATTERNS: Dict[str, List[str]] = {
    "income": [
        r"consolidated\s+statement\s+of\s+comprehensive\s+income",
        r"consolidated\s+statement\s+of\s+profit\s+or\s+loss",
        r"statement\s+of\s+comprehensive\s+income",
        r"statement\s+of\s+profit\s+or\s+loss(?:\s+and\s+other\s+comprehensive\s+income)?",
    ],
    "balance": [
        r"consolidated\s+statement\s+of\s+financial\s+position",
        r"consolidated\s+balance\s+sheet",
        r"statement\s+of\s+financial\s+position",
    ],
    "cashflow": [
        r"consolidated\s+statement\s+of\s+cash\s+flows?",
    ],
}

ESEF_COMPANY_STATEMENT_RE = re.compile(
    r"\bcompany\s+(?:balance\s+sheet|statement\s+of|cash\s+flow)|"
    r"parent\s+company\s+(?:only\s+)?(?:balance|financial|statement)|"
    r"comptes? de la soci[eé]t[eé]|bilan social|compte de r[eé]sultat de la soci[eé]t[eé]",
    re.I,
)

ESEF_FRENCH_TOC_PAGE_RE = re.compile(
    r"bilan consolid[eé].{0,80}compte de r[eé]sultat|"
    r"compte de r[eé]sultat.{0,80}bilan consolid[eé]|"
    r"tableau des flux.{0,80}bilan consolid[eé]",
    re.I,
)

ESEF_TOC_PAGE_RE = re.compile(
    r"consolidated financial statements\s+consolidated statement of comprehensive income\s+\d+\s+consolidated balance sheet",
    re.I,
)

ESEF_BOILERPLATE_ONLY_RE = re.compile(
    r"^the year in review\b.*\bfinancial statements\b.*\bannual report\s+\d{4}\b",
    re.I | re.DOTALL,
)

_ESEF_AMOUNT_OR_FISCAL_RE = re.compile(
    r"(?:\(in|expressed\s+in|all amounts are in)\s+(?:eur|usd|gbp)?\s*(?:millions|thousands)|"
    r"all amounts in thousands|"
    r"en millions d.?euros|"
    r"(?:for the )?(?:fiscal )?years? ended|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december|"
    r"janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)"
    r"\s+\d{1,2},?\s+\d{4}|"
    r"\b\d{1,3}(?:,\d{3})+\b|"
    r"\b\d{1,3}(?: \d{3})+\b",
    re.I,
)

_ESEF_SPACE_AMOUNT_RE = re.compile(r"\b\d{1,3}(?: \d{3})+\b")


def _esef_financial_table_score(text: str) -> int:
    """French ESEF reports often use space-separated thousands (e.g. 84 683)."""
    normalized = normalize_page_text(text)
    return financial_table_score(normalized) + len(_ESEF_SPACE_AMOUNT_RE.findall(normalized)) * 2

_ESEF_TITLE_SCAN_CHARS = 750


def _esef_page_prefix(page_text: str, chars: int = 1200) -> str:
    return _page_prefix(page_text, chars)


def _esef_amount_or_fiscal(text: str) -> bool:
    return bool(_ESEF_AMOUNT_OR_FISCAL_RE.search(text))


def _esef_statement_title_near_head(prefix: str, patterns: List[str]) -> Optional[re.Match]:
    scan = prefix[: _ESEF_TITLE_SCAN_CHARS + 120]
    best: Optional[re.Match] = None
    for pat in patterns:
        m = re.search(pat, scan, re.I)
        if not m:
            continue
        if best is None or m.start() < best.start():
            best = m
    return best


def _esef_validate_statement_page(page_text: str, stype: str) -> bool:
    """ESEF annual-report layout: long nav headers, IFRS titles, company schedules."""
    prefix = _esef_page_prefix(page_text, 1200)
    if ESEF_COMPANY_STATEMENT_RE.search(prefix[:700]):
        return False
    if HK_SUMMARY_PAGE_RE.search(prefix[:500]):
        return False
    if ESEF_TOC_PAGE_RE.search(prefix[:900]):
        return False
    if ESEF_FRENCH_TOC_PAGE_RE.search(prefix[:900]) and not _esef_amount_or_fiscal(prefix[500:1100]):
        return False
    if ESEF_BOILERPLATE_ONLY_RE.search(prefix[:500]) and not _esef_amount_or_fiscal(prefix[400:900]):
        return False
    if re.search(
        r"regulatory capital|own funds|crr/crd|cet1|basic indicator approach|pillar 3",
        prefix[:800],
        re.I,
    ):
        return False

    if stype == "income":
        patterns = list(
            dict.fromkeys(
                ESEF_FRENCH_PATTERNS["income"] + ESEF_IFRS_PATTERNS["income"] + INCOME_TITLE_PATTERNS
            )
        )
        title = _esef_statement_title_near_head(prefix, patterns)
        if title:
            tail = prefix[title.start() : title.start() + 420]
            return bool(
                _esef_amount_or_fiscal(tail)
                and re.search(
                    r"\b(?:revenue|net revenue|interest income|profit or loss|comprehensive income|"
                    r"cost of goods|operating profit|chiffre d.?affaires|produits|revenus|"
                    r"ventes|r[eé]sultat op[eé]rationnel)\b",
                    tail,
                    re.I,
                )
            )
        return bool(
            re.search(
                r"\b(?:net revenue|revenue from|interest income|income before income taxes|"
                r"chiffre d.?affaires|produits|\bventes\b|r[eé]sultat op[eé]rationnel)\b",
                prefix[:700],
                re.I,
            )
            and len(
                _ESEF_SPACE_AMOUNT_RE.findall(normalize_page_text(page_text)[:2500])
                + re.findall(r"\b\d{1,3}(?:,\d{3})+\b", normalize_page_text(page_text)[:2500])
            ) >= 4
            and "operating activities" not in prefix[:450]
            and "company balance sheet" not in prefix[:450]
            and "flux de trésorerie" not in prefix[:450]
            and not re.search(
                r"répartition des ventes|informations trimestrielles|investissements d.?exploitation|"
                r"commentaires sur",
                prefix[:900],
                re.I,
            )
        )

    if stype == "balance":
        if re.search(r"\bcompany\s+balance\s+sheet\b", prefix[:550], re.I):
            return False
        patterns = list(
            dict.fromkeys(
                ESEF_FRENCH_PATTERNS["balance"]
                + ESEF_IFRS_PATTERNS["balance"]
                + HK_IFRS_PATTERNS.get("balance", [])
            )
        )
        title = _esef_statement_title_near_head(prefix, patterns)
        if title:
            tail = prefix[title.start() : title.start() + 420]
            return bool(
                _esef_amount_or_fiscal(tail)
                and re.search(
                    r"\b(?:total assets|intangible assets|cash and cash equivalents|december 31|"
                    r"total actif|immobilisations|décembre)\b",
                    tail,
                    re.I,
                )
            )
        return bool(
            re.search(
                r"\b(?:total assets|total non-current assets|current assets|total actif|"
                r"actif|immobilisations|total de l.?actif)\b",
                prefix[:900],
                re.I,
            )
            and re.search(
                r"\b(?:intangible assets|cash and cash equivalents|december 31|"
                r"immobilisations|tr[eé]sorerie|décembre)\b",
                prefix[:900],
                re.I,
            )
            and "company balance sheet" not in prefix[:550]
            and "bilan social" not in prefix[:550]
        )

    if stype == "cashflow":
        patterns = list(
            dict.fromkeys(ESEF_FRENCH_PATTERNS["cashflow"] + CASHFLOW_TITLE_PATTERNS)
        )
        title = _esef_statement_title_near_head(prefix, patterns)
        if title:
            tail = prefix[title.start() : title.start() + 500]
            activity_hit = bool(
                re.search(r"operating activities", tail, re.I)
                or re.search(r"net cash from operations", tail, re.I)
                or re.search(
                    r"flux.{0,20}activit[eé]s op[eé]rationnelles|activit[eé]s op[eé]rationnelles",
                    tail,
                    re.I,
                )
                or (
                    re.search(r"(?:profit|income) before (?:income )?tax(?:es)?", tail, re.I)
                    and re.search(r"adjustments", tail, re.I)
                )
            )
            return bool(activity_hit and _esef_amount_or_fiscal(tail))
        cf_body = _esef_page_prefix(page_text, 4000)
        if re.search(r"tableau de variation de la tr[eé]sorerie", prefix[:900], re.I):
            return bool(
                re.search(
                    r"op[eé]rations d.?exploitation|capacit[eé] d.?autofinancement|"
                    r"flux.{0,20}activit[eé]s op[eé]rationnelles",
                    cf_body,
                    re.I,
                )
                and _esef_amount_or_fiscal(cf_body[:1200])
            )
        return bool(
            re.search(
                r"op[eé]rations d.?exploitation|capacit[eé] d.?autofinancement|"
                r"operating activities|cash flows? from operating",
                cf_body[:2500],
                re.I,
            )
            and _esef_amount_or_fiscal(cf_body[:1200])
            and "capitaux propres consolid" not in prefix[:700]
            and not re.search(r"commentaires sur", prefix[:500], re.I)
        )

    return False


def _esef_rank_page(page: int, stype: str, pages: List[str]) -> Tuple[int, int, int, int]:
    """Prefer consolidated statements over company schedules and TOC pages."""
    company_like = 0
    toc_like = 0
    continuation = 0
    if page < len(pages):
        prefix = _esef_page_prefix(pages[page], 900)
        if ESEF_COMPANY_STATEMENT_RE.search(prefix[:600]):
            company_like = 1
        if ESEF_TOC_PAGE_RE.search(prefix[:900]):
            toc_like = 1
        if not re.search(
            r"consolidated\s+(?:statement|balance\s+sheet|statements?)|consolid[eé]",
            prefix[:_ESEF_TITLE_SCAN_CHARS],
            re.I,
        ):
            if stype in ("income", "balance") and re.search(
                r"\b(?:revenue|total assets|intangible assets)\b", prefix[:700], re.I
            ):
                continuation = 0
            else:
                continuation = 1
    return (company_like, toc_like, continuation, page)


def _esef_pick_best(
    candidates: Dict[str, List[Tuple[int, int]]],
    pages: List[str],
) -> Dict[str, int]:
    found: Dict[str, int] = {}
    for stype, hits in candidates.items():
        if not hits:
            continue
        max_score = max(score for _, score in hits)
        threshold = max_score * 0.92
        top = [(page, score) for page, score in hits if score >= threshold]
        valid = [
            (page, score)
            for page, score in top
            if _esef_validate_statement_page(pages[page], stype)
        ]
        if not valid:
            continue
        found[stype] = min(valid, key=lambda h: _esef_rank_page(h[0], stype, pages))[0]
    return found


def _esef_title_match(head: str, patterns: List[str]) -> Optional[Tuple[int, int]]:
    """ESEF 法文/目录页标题续行较宽松，避免误拒真实报表页。"""
    best: Optional[Tuple[int, int]] = None
    for pat in patterns:
        m = re.search(pat, head[:HEAD_SCAN_CHARS], re.I)
        if not m:
            continue
        tail = head[m.end() : m.end() + 48]
        if re.match(
            r"\s*(?:in the|in which|are presented|included in|see notes|within the|of \$|of \d+\s+million|until\b)\b",
            tail,
        ):
            continue
        strength = 3 if re.search(r"consolid|consolid[eé]", pat, re.I) else 2
        pos = m.start()
        if best is None or strength > best[1] or (strength == best[1] and pos < best[0]):
            best = (pos, strength)
    return best


def _esef_collect_candidates(
    pages: List[str],
    patterns_map: Dict[str, List[str]],
    page_range: Optional[Tuple[int, int]] = None,
    min_score: int = 4,
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
        table_score = _esef_financial_table_score(raw)
        if table_score < min_score:
            continue
        for stype, patterns in active_patterns.items():
            title = _esef_title_match(head, patterns)
            if not title:
                continue
            if not _esef_validate_statement_page(raw, stype):
                continue
            pos, strength = title
            candidates[stype].append(
                (page_num, _composite_score(table_score, pos, strength))
            )
    return candidates


def _esef_untitled_block_score(page_text: str, stype: str) -> int:
    if not _esef_validate_statement_page(page_text, stype):
        return 0
    prefix = _esef_page_prefix(page_text, 900)
    cf_body = _esef_page_prefix(page_text, 4000) if stype == "cashflow" else prefix
    table = _esef_financial_table_score(page_text)
    bonus = 0
    if stype == "income" and re.search(
        r"\brevenue\b|chiffre d.?affaires|produits|\bventes\b", prefix[:400], re.I
    ):
        bonus += 80
    if stype == "income" and re.search(
        r"total\s+(?:net\s+)?(?:revenues?|sales)|chiffre d.?affaires", prefix[:900], re.I
    ):
        bonus += 120
    if stype == "balance" and re.search(r"total assets|total actif|total de l.?actif", prefix, re.I):
        bonus += 80
    if stype == "balance" and re.search(r"current assets|actif courant", prefix[:500], re.I):
        bonus += 60
    if stype == "cashflow" and re.search(
        r"op[eé]rations d.?exploitation|tableau de variation de la tr[eé]sorerie", prefix[:700], re.I
    ):
        bonus += 100
    if stype == "cashflow" and re.search(
        r"(?:profit|income) before (?:income )?tax(?:es)?", prefix[:500], re.I
    ) and re.search(r"net cash from operating activities|cash flows? from operating", cf_body, re.I):
        bonus += 150
    return table + bonus


def _locate_esef_untitled_blocks(
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
                head = _esef_page_prefix(pages[page_num], 600)
                if _head_excluded(head):
                    continue
                score = _esef_untitled_block_score(pages[page_num], stype)
                if score > best_score:
                    best_score = score
                    best_page = page_num
        if best_page >= 0 and best_score >= 40:
            found[stype] = best_page
    return found


def locate_esef_statements_from_pages(pages: List[str]) -> Dict[str, int]:
    """Locate ESEF income / balance / cashflow pages in inline XHTML annual reports."""
    if not pages:
        return {}

    found = locate_statements_from_pages(pages)
    for stype in list(found.keys()):
        if not _esef_validate_statement_page(pages[found[stype]], stype):
            del found[stype]

    missing = [k for k in ("income", "balance", "cashflow") if k not in found]
    if not missing:
        return found

    patterns = _merge_pattern_maps(ARS_PATTERNS, HK_IFRS_PATTERNS, ESEF_IFRS_PATTERNS, ESEF_FRENCH_PATTERNS)
    for page_range in _index_search_ranges(pages):
        candidates = _esef_collect_candidates(
            pages,
            patterns,
            page_range=page_range,
            min_score=4,
            allow_weak_titles=True,
        )
        picked = _esef_pick_best(candidates, pages)
        for stype in missing:
            if stype in picked and stype not in found:
                found[stype] = picked[stype]
        missing = [k for k in ("income", "balance", "cashflow") if k not in found]
        if not missing:
            break

    missing = [k for k in ("income", "balance", "cashflow") if k not in found]
    if missing:
        found.update(
            _locate_esef_untitled_blocks(pages, _index_search_ranges(pages), missing)
        )
    return found
