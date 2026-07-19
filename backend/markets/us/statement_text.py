"""财报页文本规范化（ARS / 点线表格通用）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from backend.markets.us.statement_locator import normalize_page_text

NEXT_STATEMENT_MARKERS = {
    "income": [
        r"consolidated balance sheets?",
        r"\bbalance sheets?\b",
        r"statements?\s+of\s+financial\s+position",
        r"consolidated\s+statements?\s+of\s+financial\s+position",
        r"综合(?:财务)?状况表",
        r"资产负债表",
        r"december 31,\s+\d{4}.{0,120}intangible assets",
        r"total non-current assets",
        r"consolidated statements of cash flows?",
        r"statements of cash flows?",
        r"changes in (?:shareholders?.?\s+equity|stockholders?.?\s+equity)",
        r"statement of changes in equity",
    ],
    "balance": [
        r"consolidated statements of cash flows?",
        r"\bcash flows?\s+statements?\b",
        r"\bcash flows?\s+from\s+operating",
        r"consolidated\s+statements?\s+of\s+operations",
        r"consolidated\s+statements?\s+of\s+comprehensive\s+income",
        r"statements?\s+of\s+operations",
    ],
    "cashflow": [r"notes to consolidated", r"see accompanying notes"],
}


_REVENUE_EXPENSE_LABEL_RE = re.compile(
    r"sales and marketing|cost of (?:sales|revenue)s?|general and administrative|"
    r"technology and development|research and development|marketing, general",
    re.I,
)


def _is_revenue_expense_line(label_part: str) -> bool:
    return bool(_REVENUE_EXPENSE_LABEL_RE.search(label_part))


def _is_segment_sales_line(label_part: str) -> bool:
    """Products/Services 分项 Sales:，不是 Total net sales。"""
    return bool(re.match(r"^sales\s*:", label_part.strip(), re.I))


def flatten_statement_text(text: str) -> str:
    return normalize_page_text(text)


def merge_statement_pages(pages: List[str], start_page: int, statement_type: str) -> str:
    """SEC HTML/iXBRL 常把一张报表拆成多页，合并后续页文本。"""
    parts = [pages[start_page]]
    max_extra = 6 if statement_type == "cashflow" else 4
    for offset in range(1, max_extra + 1):
        idx = start_page + offset
        if idx >= len(pages):
            break
        head = pages[idx][:400].lower()
        if statement_type in NEXT_STATEMENT_MARKERS:
            if any(re.search(pat, head) for pat in NEXT_STATEMENT_MARKERS[statement_type]):
                break
        parts.append(pages[idx])
        if statement_type == "cashflow" and cashflow_statement_complete("\n".join(parts)):
            break
    return "\n".join(parts)


def load_statement_text(document_path: str, statement_type: str, page: int) -> str:
    """读取单页 PDF 或合并多页 HTML 报表文本。"""
    import fitz

    doc = fitz.open(document_path)
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    suffix = Path(document_path).suffix.lower()
    if suffix in {".htm", ".html"}:
        return merge_statement_pages(pages, page, statement_type)
    if suffix == ".pdf":
        from backend.markets.us.statement_grid_extractor import _statement_page_span

        start, end = _statement_page_span(pages, page, statement_type)
        return "\n".join(pages[start:end])
    if statement_type == "cashflow":
        merged = merge_statement_pages(pages, page, statement_type)
        if cashflow_statement_complete(merged):
            return merged
    return pages[page]


def statement_unit_divisor(page_text: str) -> float:
    """报表页眉单位：统一换算为百万（millions）。"""
    head = page_text[:2500].lower()
    if re.search(
        r"\(in\s+millions\)|\bin\s+millions\b|amounts\s+in\s+millions",
        head,
    ):
        return 1.0
    if re.search(
        r"(?:\(\s*)?(?:all\s+amounts\s+in\s+|in\s+)thousands|amounts\s+in\s+thousands",
        head,
    ):
        if re.search(
            r"shares?.{0,40}(?:are\s+)?(?:reflected\s+in\s+|in\s+|denominated\s+in\s+)thousands|"
            r"except\s+(?:number\s+of\s+)?shares?.{0,30}thousands",
            head,
        ):
            return 1.0
        return 1000.0
    return 1.0


_CASHFLOW_COMPONENT_LINE_RE = re.compile(
    r"^(?:dividends|additions to property|repurchase|proceeds from|purchase of property|"
    r"purchases of property|payments to acquire|net change in short-term|issuance of|retirement of)",
    re.I,
)

_CASHFLOW_SECTION_HEADER_RE = re.compile(
    r"^cash flows from (?:operating|investing|financing)(?: activities)?\s*$",
    re.I,
)


def cashflow_line_pattern(activity: str) -> str:
    """匹配现金流量表合计行（兼容 SEC HTML / 港股 IFRS 多种表述）。"""
    activity_alt = {
        "operating": r"operating(?: activities)?|operations",
        "investing": r"investing(?: activities)?",
        "financing": r"financing(?: activities)?",
    }.get(activity, rf"{activity}(?: activities)?")
    hk_net = {
        "operating": (
            r"net cash flows? generated from/?\(used in\) operating activities|"
            r"net cash inflow/?\(outflow\) from operating activities|"
        ),
        "investing": (
            r"net cash flows? generated from/?\(used in\) investing activities|"
            r"net cash inflow/?\(outflow\) from investing activities|"
            r"net cash provided by\s*/?\s*\(used in\) investing activities|"
        ),
        "financing": (
            r"net cash flows? (?:used in|generated from)/?\(used in\) financing activities|"
            r"net cash \(used in\)/provided by financing activities|"
            r"net cash inflow/?\(outflow\) from financing activities|"
        ),
    }.get(activity, "")
    investing_slash = (
        r"cash generated by\s*/?\s*\(used in\)\s+investing activities|"
        if activity == "investing"
        else ""
    )
    return (
        rf"(?:"
        rf"{hk_net}"
        rf"{investing_slash}"
        rf"net cash(?: flows)?(?: \([^)]+\))?(?:\/(?:from|used by)|(?: provided by| from| used in| used by| used for| generated from))"
        rf"(?: \([^)]+\))?\s+{activity_alt}|"
        rf"net cash (?:from|used in)\s+{activity_alt}|"
        rf"net cash provided by\s*(?:\([^)]+\)\s*)?{activity_alt}|"
        rf"net cash used by\s+{activity_alt}|"
        rf"net cash used for\s+{activity_alt}|"
        rf"net cash (?:\(used by\)/from|from|used in) {activity_alt}|"
        rf"cash flows?\s+(?:from|used for|provided by)\s+{activity_alt}|"
        rf"cash (?:generated by|used in)\s+{activity_alt}"
        rf")"
    )


def is_cashflow_component_line(label: str) -> bool:
    return bool(_CASHFLOW_COMPONENT_LINE_RE.match(label.strip()))


def is_cashflow_section_header(label: str) -> bool:
    text = label.strip()
    if _CASHFLOW_SECTION_HEADER_RE.match(text):
        return True
    if re.match(
        r"^cash flows from (?:operating|investing|financing)(?: activities)?\b",
        text,
        re.I,
    ) and not re.search(r"^net cash", text, re.I):
        return True
    # 段标题带冒号，后面紧跟明细行（Visa cfo 等）
    if re.search(
        r"(?:^net cash provided by(?: \([^)]+\))?\s+)?(?:operating|investing|financing)\s+activities\s*:\s*$",
        text,
        re.I,
    ):
        return True
    return False


def score_capex_line(label: str) -> float:
    """优先资本开支明细行，而非 investing activities 合计（AMD 等间接法 CF）。"""
    text = label.strip().lower()
    if re.search(r"discontinued operations", text):
        return -1.0
    if re.search(r"net cash.{0,32}(?:used in|from)\s+investing", text):
        return -1.0
    if re.search(r"investing activities\s*$", text):
        return -1.0
    score = 0.0
    if re.search(
        r"purchase[s]? of property|payments? to acquire property|capital expenditure|"
        r"additions to property|acquisition of fixed assets|购建固定",
        text,
    ):
        score += 50_000
    return score


def score_cashflow_line(label: str, match_start: int, n_amounts: int) -> float:
    label_clean = label.strip()
    if is_cashflow_section_header(label_clean) or is_cashflow_component_line(label_clean):
        return -1.0
    text = label_clean.lower()
    if re.search(r"\bcontinuing operations\b|\bdiscontinued operations\b", text):
        return -1.0
    score = n_amounts * 1000 - match_start
    if re.search(r"^net cash", label_clean, re.I):
        score += 20_000
    if re.search(r"generated from|inflow/?\(outflow\)", label_clean, re.I):
        score += 5_000
    return score


def score_net_income_line(label: str) -> float:
    """优先合计净利润行，而非 continuing / NCI 分项（对齐 XBRL NetIncomeLoss）。"""
    text = label.strip().lower()
    if re.search(r"comprehensive|before tax|per share", text):
        return -1.0
    if re.search(r"non[- ]?controlling", text):
        return -1.0
    if re.search(r"discontinued", text):
        return -1.0
    if re.search(r"\bnet income(?:/(?:expense))? from\b", text):
        return -1.0
    score = 0.0
    if re.search(r"profit for the year", text):
        score += 58_000
    if re.search(r"attributable to .+ common shareholders", text):
        score += 60_000
    elif re.search(
        r"net (?:income|earnings)(?: \(loss\))? attributable to(?!.*\bcommon stock\b)", text
    ):
        score += 60_000
    elif re.search(r"attributable to common stock", text):
        score += 30_000
    if re.fullmatch(r"net income(?: \(loss\))?", text.strip(), re.I):
        score += 55_000
    if re.fullmatch(r"net earnings?", text):
        score += 50_000
    if re.search(r"from continuing|from discontinued", text):
        score += 1_000
    return score


EPS_BASIC_TEXT_PATTERN = (
    r"total\s+net\s+(?:income|earnings)\s+per\s+share\s*-?\s*basic|"
    r"basic\s+(?:earnings|net income)\s+per\s+(?:ordinary\s+)?share|"
    r"basic\s+and\s+diluted\s+(?:earnings|net\s+(?:income|loss))\s+per|"
    r"basic\s+and\s+diluted\s+earnings\s+per\s+share|"
    r"shareholders?\s+basic\s+and\s+diluted|"
    r"(?:net\s+(?:income|loss|earnings)|earnings\s*\(\s*loss\s*\))\s+per\s+share|"
    r"(?:net\s+(?:income|loss|earnings)\s+per\s+(?:share|ordinary\s+share|ads))(?:,?\s+basic|\s+basic)|"
    r"per\s+share,?\s+basic|"
    r"基本每股盈利|每股基本盈利|"
    r"earnings\s+per\s+(?:ordinary\s+)?share|每股盈利"
)


def truncate_eps_basic_chunk(chunk: str) -> str:
    """截断到 diluted EPS 行之前，保留 "basic and diluted" 合并披露行。"""
    lower = chunk.lower()
    for match in re.finditer(r"\bdiluted\b", chunk, re.I):
        start = match.start()
        prefix = lower[max(0, start - 12) : start]
        if prefix.endswith("basic and ") or prefix.endswith(", "):
            continue
        if start > 0 and chunk[start - 1] in "–-—":
            return chunk[: start - 1]
        return chunk[:start]
    return chunk


def _strip_eps_footnote_prefix(text: str) -> str:
    text = text.strip()
    text = re.sub(
        r"^\([^)]*(?:rmb|yuan|us\$|hkd|share|million)[^)]*\)\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"^[\s–\-—:]+", "", text)
    text = re.sub(r"^(\d{1,3}[\(\)a-z]*)(?!\.\d)\s*", "", text, flags=re.I)
    return re.sub(r"^(?:us\$?|rmb|hkd|hk\$)\s*", "", text, flags=re.I)


def eps_basic_label_part(chunk: str) -> str:
    chunk = truncate_eps_basic_chunk(chunk)
    lower = chunk.lower()
    combined = re.search(
        r"total\s+net\s+(?:income|earnings)\s+per\s+share\s*(?:-|:)?\s*basic|"
        r"basic\s+and\s+diluted\s+(?:earnings|net\s+(?:income|loss))\s+per(?:\s+share)?|"
        r"basic\s+and\s+diluted\s+earnings\s+per\s+share|"
        r"basic\s+(?:earnings|net\s+(?:income|loss))\s+per(?:\s+(?:ordinary\s+)?share)?|"
        r"(?:net\s+(?:income|loss|earnings)|earnings\s*\(\s*loss\s*\))\s+per\s+share"
        r"(?:\s+attributable[^:—\-]{0,240})?(?:[:\—\-]\s*basic|,\s*basic)|"
        r"net\s+(?:income|loss|earnings)\s+per\s+(?:share|ordinary\s+share|ads),?\s*basic|"
        r"earnings\s+per\s+(?:ordinary\s+)?share[^\d]{0,160}?basic|"
        r"shareholders?\s+basic\s+and\s+diluted|"
        r"per\s+share,?\s+basic",
        lower,
    )
    if combined:
        return chunk[: combined.end()].strip()
    basic_match = re.search(r"\bbasic\b", lower)
    if basic_match:
        return chunk[: basic_match.end()].strip()
    return label_prefix_before_amounts(chunk)


def _eps_amounts_look_like_share_count(amounts: List[float]) -> bool:
    return bool(amounts) and all(abs(v) > 500 for v in amounts)


def parse_eps_basic_amounts(chunk: str, *, max_cols: int = 3) -> List[float]:
    """从 EPS 行提取 basic 列（跳过附注编号，截断 diluted 段）。"""
    text = truncate_eps_basic_chunk(chunk)
    lower = text.lower()

    def _take_amounts_after(pos: int) -> List[float]:
        tail = _strip_eps_footnote_prefix(text[pos:])
        amounts = parse_statement_amounts(tail, per_share=True)
        if amounts and not _eps_amounts_look_like_share_count(amounts):
            return amounts[:max_cols]
        return []

    for pat in (
        r"total\s+net\s+(?:income|earnings)\s+per\s+share\s*(?:-|:)?\s*basic",
        r"basic\s+and\s+diluted\s+(?:earnings|net\s+(?:income|loss))\s+per(?:\s+share)?",
        r"shareholders?\s+basic\s+and\s+diluted",
        r"basic\s+and\s+diluted\s+earnings\s+per\s+share",
        r"(?:net\s+(?:income|loss|earnings)|earnings\s*\(\s*loss\s*\))\s+per\s+share"
        r"(?:\s+attributable[^:—\-]{0,240})?(?:[:\—\-]\s*basic|,\s*basic)",
        r"per\s+share,?\s+basic",
    ):
        match = re.search(pat, lower)
        if match:
            amounts = _take_amounts_after(match.end())
            if amounts:
                return amounts

    combined = re.search(
        r"basic\s+and\s+diluted\s+(?:earnings|net\s+(?:income|loss))\s+per(?:\s+share)?|"
        r"shareholders?\s+basic\s+and\s+diluted|"
        r"basic\s+and\s+diluted\s+earnings\s+per\s+share",
        lower,
    )
    if combined:
        amounts = _take_amounts_after(combined.end())
        if amounts:
            return amounts

    best_score = -1.0
    best_amounts: List[float] = []
    for basic_match in re.finditer(r"\bbasic\b", lower):
        label = eps_basic_label_part(text[: basic_match.end()])
        if score_eps_basic_line(label) < 0:
            continue
        amounts = _take_amounts_after(basic_match.end())
        if not amounts:
            continue
        rank = score_eps_basic_line(label)
        if rank > best_score:
            best_score = rank
            best_amounts = amounts
    if best_amounts:
        return best_amounts

    amounts = parse_statement_amounts(text, per_share=True)[:max_cols]
    if _eps_amounts_look_like_share_count(amounts):
        return []
    return amounts


def score_eps_basic_line(label: str) -> float:
    """优先 total basic EPS，而非 continuing-only（对齐 XBRL EarningsPerShareBasic）。"""
    text = truncate_eps_basic_chunk(label).strip().lower()
    if re.search(r"shares outstanding|average shares|million shares|weighted.average", text):
        return -1.0
    if re.search(r"net\s+(?:income|loss|earnings)\s+per\s+(?:share|ordinary\s+share|ads)\s+basic\s+and\s+diluted", text):
        if not re.search(r"shareholders?\s+basic\s+and\s+diluted", text):
            return -1.0
    score = 0.0
    if re.search(r"total net earnings per share.*basic|total.*basic.*net earnings per share", text):
        score += 50_000
    if re.search(r"net\s+income\s+per\s+share", text) and re.search(r"\bbasic\b", text):
        score += 49_000
    if re.search(r"earnings\s*\(\s*loss\s*\)\s+per\s+share", text) and re.search(r"\bbasic\b", text):
        score += 49_000
    if re.search(r"basic\s+(?:earnings|net income)\s+per\s+(?:ordinary\s+)?share", text):
        score += 50_000
    if re.search(r"basic\s+and\s+diluted\s+(?:earnings|net\s+(?:income|loss))\s+per", text):
        score += 48_000
    if re.search(r"per\s+share,?\s+basic", text):
        score += 47_000
    if re.search(r"earnings\s+per\s+(?:ordinary\s+)?share", text) and re.search(r"\bbasic\b", text):
        score += 45_000
    if re.search(r"net\s+(?:income|loss|earnings)\s+per\s+(?:share|ordinary\s+share)", text) and re.search(
        r"\bbasic\b", text
    ):
        score += 44_000
    if re.search(r"shareholders?\s+basic\s+and\s+diluted", text):
        score += 46_000
    if "total" in text and "basic" in text:
        score += 12_000
    if re.search(r"basic net income per share", text):
        score += 10_000
    if re.search(r"continuing.*basic|basic.*continuing", text):
        score += 1_000
    if score == 0.0 and re.search(r"\bbasic\b", text) and "per share" in text:
        score += 8_000
    return score


def cashflow_statement_complete(text: str) -> bool:
    """HTML/PDF 现金流量表是否已包含三段合计行。"""
    lower = text.lower()
    sections = (
        (
            r"net cash.{0,48}operating|"
            r"net cash from operations|"
            r"cash generated by operating activities"
        ),
        (
            r"net cash.{0,48}investing|"
            r"cash generated by\s*/?\s*\(used in\)\s+investing activities"
        ),
        (
            r"net cash.{0,48}financing|"
            r"cash used in financing activities"
        ),
    )
    return all(re.search(section, lower) for section in sections)


def label_prefix_before_amounts(chunk: str) -> str:
    """行标签部分（第一个金额之前的文本）。"""
    match = re.search(
        r"[\$\(]\s*[\d\(]|\(\s*[\d,]|\d{1,3}(?:,\d{3})+",
        chunk,
    )
    return chunk[: match.start()] if match else chunk[:50]


def truncate_balance_line_chunk(chunk: str) -> str:
    """截断到 Liabilities 段标题之前，避免误切 Total liabilities 行标签本身。"""
    m = re.search(r"(?<![Tt]otal\s)\s+Liabilities\b(?!\s+and\b)", chunk, re.I)
    if m and m.start() > 20:
        return chunk[: m.start()]
    return chunk


def _is_year_like_amount(val: float, raw: str) -> bool:
    return 1990 <= abs(val) <= 2035 and "," not in raw and "." not in raw


def _accept_statement_amount(val: float, raw: str, *, bare_column: bool, has_dollar: bool, is_parenthesized: bool = False) -> bool:
    if _is_year_like_amount(val, raw):
        return False
    if is_parenthesized or has_dollar or "," in raw:
        return abs(val) >= 100 and abs(val) <= 999_999_999_999
    if bare_column:
        return 50 <= abs(val) < 1000
    return abs(val) >= 1000 and abs(val) <= 999_999_999_999


def parse_statement_amounts(
    text: str,
    per_share: bool = False,
    unit_divisor: float = 1.0,
) -> list[float]:
    """从规范化文本中提取金额列（默认输出百万单位）。"""
    flat = flatten_statement_text(text)
    amounts: list[float] = []
    if per_share:
        for m in re.finditer(
            r"\$\s*([\d]+\.[\d]+)|\(\s*([\d]+\.[\d]+)\s*\)|(?<![\d.])(\d+\.\d+)(?![\d])",
            flat,
        ):
            raw = m.group(1) or m.group(2) or m.group(3)
            val = float(raw)
            if m.group(2):
                val = -val
            amounts.append(val)
        return amounts

    amount_re = re.compile(
        r"\$\s*([\d,]+)|\(\s*([\d,]+)\s*\)|(?<![\d.])(\d{1,3}(?:,\d{3})+)(?![\d])|"
        r"(?<![\d.])(\d{4,7})(?![\d])|(?<![\d.])(\d{2,3})(?![\d])"
    )
    for m in amount_re.finditer(flat):
        bare_column = m.group(5) is not None
        has_dollar = m.group(1) is not None
        is_parenthesized = m.group(2) is not None
        raw = m.group(1) or m.group(2) or m.group(3) or m.group(4) or m.group(5)
        if not raw:
            continue
        val = float(raw.replace(",", ""))
        if m.group(2):
            val = -val
        if _accept_statement_amount(
            val,
            raw,
            bare_column=bare_column,
            has_dollar=has_dollar,
            is_parenthesized=is_parenthesized,
        ):
            amounts.append(val / unit_divisor)
    return amounts
