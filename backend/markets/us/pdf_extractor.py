from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz

from backend.global_schema.models import CompanyFinancials, FieldValue, ValueScale
from backend.global_schema.registry import GLOBAL_FIELDS_V1, field_by_id
from backend.markets.us.period_parser import StatementPeriod, parse_statement_periods, resolve_balance_periods
from backend.markets.us.statement_grid_extractor import StatementGrid
from backend.markets.us.statement_locator import locate_statements_from_pages
from backend.markets.us.statement_text import (
    cashflow_line_pattern,
    eps_basic_label_part,
    EPS_BASIC_TEXT_PATTERN,
    flatten_statement_text,
    label_prefix_before_amounts,
    load_statement_text,
    merge_statement_pages,
    parse_eps_basic_amounts,
    parse_statement_amounts,
    score_cashflow_line,
    score_capex_line,
    score_eps_basic_line,
    score_net_income_line,
    statement_unit_divisor,
    truncate_balance_line_chunk,
    truncate_eps_basic_chunk,
    _eps_amounts_look_like_share_count,
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

# Global Schema field_id → (statement, regex)
US_PDF_FIELD_PATTERNS: Dict[str, Tuple[str, str]] = {
    "revenue": ("income", r"(?:net\s+)?(?:total\s+(?:net\s+)?(?:sales|revenue)s?|total\s+income)|\b(?:sales(?:\s+to\s+customers)?|revenues?)\b"),
    "gross_profit": ("income", r"gross\s+(?:margin|profit)"),
    "operating_income": ("income", r"(?:operating\s+income|income\s+from\s+operations|earnings\s+from\s+operations)"),
    "net_income": ("income", r"net\s+(?:income|earnings)(?!\s+(?:from|per\b))"),
    "eps_basic": ("income", EPS_BASIC_TEXT_PATTERN),
    "total_assets": ("balance", r"total\s+assets(?!\s+(?:and|less))"),
    "total_liabilities": (
        "balance",
        r"total\s+liabilities(?!\s+and\s+(?:stockholders|shareholders|equity))",
    ),
    "total_equity": (
        "balance",
        r"total\s+shareholders?.?\s+equity(?!\s+and)|total\s+stockholders?.?\s+equity",
    ),
    "cash": ("balance", r"\bcash and cash equivalents\b"),
    "cfo": ("cashflow", cashflow_line_pattern("operating")),
    "cfi": ("cashflow", cashflow_line_pattern("investing")),
    "cff": ("cashflow", cashflow_line_pattern("financing")),
    "capex": (
        "cashflow",
        r"payments to acquire property,? plant and equipment|purchases of property,? plant and equipment|"
        r"purchase of property,? plant and equipment|capital expenditures|payments for property and equipment|"
        r"purchases of property and equipment|additions to property,? plant and equipment|"
        r"additions to property and equipment|"
        r"payments for acquisition of property,? plant and equipment|"
        r"acquisition of fixed assets|"
        r"payment for property,?\s*plant and equipment|"
        r"purchase and construction of fixed assets|"
        r"购建固定资产|购建固定|购置物业|资本开支",
    ),
}

MAX_COLS = {"income": 3, "balance": 2, "cashflow": 3}
CHUNK_LEN = {"income": 140, "balance": 100, "cashflow": 280}


@dataclass
class PdfExtractionResult:
    source_path: str
    source_type: str
    statement_pages: Dict[str, int] = field(default_factory=dict)
    statement_periods: Dict[str, List[StatementPeriod]] = field(default_factory=dict)
    values: List[FieldValue] = field(default_factory=list)
    periods: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    statement_grids: Dict[str, StatementGrid] = field(default_factory=dict)

    def to_company_financials(self, ticker: str, company_name: str, cik: str = "") -> CompanyFinancials:
        return CompanyFinancials(
            ticker=ticker.upper(),
            company_name=company_name,
            market="US",
            cik=cik,
            standard="US-GAAP",
            values=self.values,
            periods=self.periods,
            errors=self.errors,
        )


def _parse_amounts(text: str, per_share: bool = False, unit_divisor: float = 1.0) -> List[float]:
    return parse_statement_amounts(text, per_share=per_share, unit_divisor=unit_divisor)


def _load_document_text(path: str) -> Tuple[str, str]:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        doc = fitz.open(path)
        pages = [doc[i].get_text() for i in range(len(doc))]
        doc.close()
        return "pdf", "\n".join(pages)
    if suffix in {".htm", ".html"}:
        from bs4 import BeautifulSoup

        html = Path(path).read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        return "html", soup.get_text(separator="\n")
    raise ValueError(f"Unsupported document format: {suffix}")


_NEXT_STATEMENT_MARKERS = {
    "income": [r"consolidated balance sheets?", r"\bbalance sheets?\b"],
    "balance": [r"consolidated statements of cash flows?", r"\bcash flows?\b"],
    "cashflow": [r"notes to consolidated", r"see accompanying notes"],
}


def _statement_page_text(pages: List[str], start_page: int, statement_type: str) -> str:
    return merge_statement_pages(pages, start_page, statement_type)


def _flatten_statement_text(text: str) -> str:
    return flatten_statement_text(text)


def _extract_line_values(
    page_text: str,
    statement_type: str,
    pattern: str,
    field_id: str,
    per_share: bool = False,
    unit_divisor: float = 1.0,
) -> Tuple[str, List[float]]:
    flat = _flatten_statement_text(page_text)
    max_cols = MAX_COLS[statement_type]
    chunk_len = CHUNK_LEN[statement_type]
    best_amounts: List[float] = []
    best_label = ""
    best_score = float("-inf")

    for match in re.finditer(pattern, flat.lower()):
        before = flat[max(0, match.start() - 30) : match.start()].lower()
        chunk = flat[match.start() : match.start() + chunk_len]
        if statement_type == "balance":
            chunk = truncate_balance_line_chunk(chunk)
        if field_id == "operating_income":
            if re.search(r"non-operating", before):
                continue
            if re.search(r"operating income\s*\(expense\)", chunk[:50], re.I):
                continue
            if re.search(r"operating income\s*margin", chunk[:50], re.I):
                continue
        if field_id == "total_liabilities" and re.search(
            r"total\s+liabilities\s+and\s+(?:stockholders|shareholders|equity)", chunk, re.I
        ):
            continue
        if field_id == "net_income" and re.search(r"before income taxes|comprehensive income", chunk, re.I):
            continue
        if field_id == "net_income":
            label_part = label_prefix_before_amounts(chunk)
            if score_net_income_line(label_part) < 0:
                continue
        if field_id == "eps_basic":
            chunk = truncate_eps_basic_chunk(chunk)
            label_part = eps_basic_label_part(chunk)
            if score_eps_basic_line(label_part) < 0:
                continue
            if re.search(r"shares outstanding|average shares|million shares", label_part, re.I):
                continue
            if re.search(r"computing net (?:income|loss) per (?:share|ads)", label_part, re.I):
                continue
            if re.fullmatch(r"basic", label_part.strip(), re.I):
                continue
            if re.search(r"earnings per share", label_part, re.I) and not re.search(
                r"\bbasic\b", label_part, re.I
            ):
                continue
            if re.search(r"net income per share", label_part, re.I) and not re.search(
                r"\bbasic\b", label_part, re.I
            ):
                continue
        if field_id == "revenue" and re.search(
            r"operating income\s*/\s*\(?expense\)?|operating income\s+includes|"
            r"other operating income",
            chunk[:70],
            re.I,
        ):
            continue
        if field_id == "revenue" and _is_segment_sales_line(label_prefix_before_amounts(chunk)):
            continue
        label_part_rev = label_prefix_before_amounts(chunk).strip().lower()
        if field_id == "revenue" and label_part_rev in ("sales", "sale", "revenue", "revenues"):
            continue
        if field_id == "revenue" and label_part_rev.startswith("sales ") and not label_part_rev.startswith("sales to"):
            continue
        if field_id == "revenue" and re.match(r"revenues?\s+(?:automotive|energy|services)\b", chunk[:55], re.I):
            continue
        amounts = (
            parse_eps_basic_amounts(chunk, max_cols=max_cols)
            if field_id == "eps_basic"
            else _parse_amounts(chunk, per_share=per_share, unit_divisor=unit_divisor)[:max_cols]
        )
        if not amounts:
            continue
        if field_id == "eps_basic" and _eps_amounts_look_like_share_count(amounts):
            continue
        if field_id == "revenue" and re.fullmatch(r"revenues?", match.group(0).strip()):
            if not re.search(r"total\s+(?:net\s+)?(?:revenue|sales)", chunk[:70], re.I):
                tail = chunk[len(match.group(0)) :][:45].strip().lower()
                if re.match(r"[a-z][a-z\s\-/]+(?:fees|income|expense|transactions|commissions)", tail):
                    continue
                if not re.search(r"\$\s*[\d,]+|\d{1,3}(?:,\d{3})+", chunk[:45]):
                    continue
        if field_id == "revenue" and amounts[0] > 300_000:
            lp = label_prefix_before_amounts(chunk)
            if not re.search(
                r"total\s+(?:net\s+)?(?:revenue|revenues|sales|turnover)|"
                r"net\s+(?:interest|operating)\s+income",
                lp,
                re.I,
            ):
                continue
        if field_id == "cash" and abs(amounts[0]) < 1000:
            continue
        if field_id == "cash" and amounts[0] < 0:
            continue
        if field_id == "operating_income" and abs(amounts[0]) < 1000:
            continue
        if field_id == "capex":
            amounts = [abs(v) for v in amounts]
            capex_rank = score_capex_line(label_prefix_before_amounts(chunk))
            if capex_rank < 0:
                continue
        if field_id == "cfo" and re.search(r"operating activities\s*:", chunk[:80], re.I):
            continue
        if field_id in ("cfo", "cfi", "cff"):
            label_cf = label_prefix_before_amounts(chunk)
            cf_score = score_cashflow_line(label_cf, match.start(), len(amounts))
            if cf_score < 0:
                continue
        if field_id == "capex":
            score = score_capex_line(label_prefix_before_amounts(chunk)) + len(amounts) * 10_000 - match.start()
        elif field_id in ("cfo", "cfi", "cff"):
            score = score_cashflow_line(label_prefix_before_amounts(chunk), match.start(), len(amounts))
        elif statement_type in ("income", "balance"):
            score = len(amounts) * 10_000
            score -= min(match.start(), 2000)
            if field_id == "revenue" and re.search(
                r"total\s+(?:net\s+)?(?:revenue|sales)", chunk[:60], re.I
            ):
                score += 5000
            if field_id == "revenue" and re.search(
                r"net operating income\s+before", chunk[:90], re.I
            ):
                score += 8000
            if field_id == "revenue" and re.search(r"net interest income", chunk[:60], re.I):
                score += 3000
            if field_id == "revenue" and re.search(
                r"(?<![a-z])operating income(?!\s*/)", chunk[:50], re.I
            ):
                if amounts and amounts[0] > 100_000:
                    score += 6000
            if field_id == "cash" and re.search(
                r"cash and cash equivalents\s+at\s+31", chunk[:90], re.I
            ):
                score += 15_000
            if field_id == "cash" and re.search(
                r"cash and cash equivalents\s+at\s+1\s", chunk[:90], re.I
            ):
                score -= 5000
            if field_id == "net_income":
                ni_rank = score_net_income_line(label_prefix_before_amounts(chunk))
                if ni_rank < 0:
                    continue
                score += ni_rank
            if field_id == "eps_basic":
                eps_rank = score_eps_basic_line(eps_basic_label_part(chunk))
                if eps_rank < 0:
                    continue
                score += eps_rank
            if field_id == "revenue" and re.fullmatch(r"revenues?", match.group(0).strip()):
                tail = chunk[len(match.group(0)) :][:45].strip().lower()
                if re.match(r"[a-z][a-z\s\-/]+(?:fees|income|expense|transactions|commissions)", tail):
                    continue
        else:
            score = match.start()
        if score > best_score:
            best_score = score
            best_amounts = amounts
            best_label = (
                eps_basic_label_part(chunk)
                if field_id == "eps_basic"
                else label_prefix_before_amounts(chunk)
                if field_id in ("cfo", "cfi", "cff")
                else match.group(0)
            )

    return best_label, best_amounts


def _merged_period_ends(
    statement_periods: Dict[str, List[StatementPeriod]],
    max_periods: int,
) -> List[str]:
    """Merge column headers from all statements — fiscal year-end dates often differ (e.g. Feb balance vs Dec income)."""
    merged: List[str] = []
    for stype in ("income", "balance", "cashflow"):
        for period in statement_periods.get(stype, []):
            if period.period_end not in merged:
                merged.append(period.period_end)
    merged.sort(reverse=True)
    from backend.markets.us.period_parser import canonicalize_period_ends

    return canonicalize_period_ends(merged, max_periods)


class UsPdfTextExtractor:
    def extract(
        self,
        document_path: str,
        target_periods: Optional[List[str]] = None,
        max_periods: int = 3,
    ) -> PdfExtractionResult:
        source_type, full_text = _load_document_text(document_path)
        pages: List[str]
        if source_type in {"pdf", "html"}:
            doc = fitz.open(document_path)
            pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
            doc.close()
        else:
            pages = [full_text]

        statement_pages = locate_statements_from_pages(pages)
        if not statement_pages:
            return PdfExtractionResult(
                source_path=document_path,
                source_type=source_type,
                        errors=["Could not locate financial statement pages in the document"],
            )

        statement_periods: Dict[str, List[StatementPeriod]] = {}
        statement_texts: Dict[str, str] = {}
        statement_unit_divisors: Dict[str, float] = {}
        for stype, page_num in statement_pages.items():
            merged = load_statement_text(document_path, stype, page_num)
            statement_texts[stype] = merged
            statement_unit_divisors[stype] = statement_unit_divisor(merged)
            statement_periods[stype] = parse_statement_periods(merged, max_periods=max_periods)

        for stype in ("cashflow", "balance"):
            if not statement_periods.get(stype) and statement_periods.get("income"):
                statement_periods[stype] = statement_periods["income"][:max_periods]

        if statement_periods.get("income"):
            statement_periods["balance"] = resolve_balance_periods(
                statement_periods.get("balance", []),
                statement_periods["income"],
                max_periods,
            )

        period_ends = target_periods or _merged_period_ends(statement_periods, max_periods)
        period_ends = period_ends[:max_periods]

        values: List[FieldValue] = []
        errors: List[str] = []
        registry = field_by_id()
        extracted_fields: set[str] = set()
        grid_source = "pdf_grid"
        statement_grids: Dict[str, StatementGrid] = {}
        if source_type in {"pdf", "html"}:
            from backend.markets.us.statement_grid_extractor import StatementGridExtractor

            grid_extractor = StatementGridExtractor()
            if source_type == "pdf":
                grids = grid_extractor.extract_page_grids(document_path, statement_pages, pages)
            else:
                grids = grid_extractor.extract_html_grids(document_path, statement_pages, pages)
                grid_source = "html_grid"
            if grids:
                statement_grids = grids
                from backend.markets.us.statement_grid_extractor import STMT_FIELDS

                grid_values, grid_errors = grid_extractor.extract_fields(grids, period_ends)
                stmt_by_field = {f.field_id: STMT_FIELDS[f.statement] for f in GLOBAL_FIELDS_V1}
                for field_id, period_end, label, val in grid_values:
                    field_def = registry[field_id]
                    extracted_fields.add(field_id)
                    if field_id == "capex":
                        val = abs(val)
                    if field_def.scale != ValueScale.PER_SHARE:
                        div = statement_unit_divisors.get(stmt_by_field.get(field_id, ""), 1.0)
                        if div > 1.0:
                            val = val / div
                    values.append(
                        FieldValue(
                            field_id=field_id,
                            period_end=period_end,
                            fiscal_year=int(period_end[:4]),
                            value=val,
                            currency="USD",
                            scale=field_def.scale,
                            standard="US-GAAP",
                            source=grid_source,
                            source_tag=label,
                            source_form="10-K",
                            filed_date="",
                        )
                    )
                errors.extend(grid_errors)

        for field_def in GLOBAL_FIELDS_V1:
            mapping = US_PDF_FIELD_PATTERNS.get(field_def.field_id)
            if not mapping:
                errors.append(f"No PDF extraction config for: {field_def.field_id}")
                continue
            statement_type, pattern = mapping
            if statement_type not in statement_pages:
                errors.append(f"Missing statement pages: {statement_type}")
                continue

            label, amounts = _extract_line_values(
                statement_texts[statement_type],
                statement_type,
                pattern,
                field_def.field_id,
                per_share=field_def.scale == ValueScale.PER_SHARE,
                unit_divisor=statement_unit_divisors.get(statement_type, 1.0),
            )

            if field_def.field_id in extracted_fields:
                grid_count = sum(1 for v in values if v.field_id == field_def.field_id)
                grid_net_cash = any(
                    re.search(r"^net cash", v.source_tag or "", re.I)
                    for v in values
                    if v.field_id == field_def.field_id
                )
                stmt_cols = len(statement_periods.get(statement_type, [])[:max_periods])
                text_authoritative = (
                    field_def.field_id == "net_income"
                    and score_net_income_line(label) >= 50_000
                    and grid_count < len(period_ends)
                ) or (
                    field_def.field_id == "eps_basic"
                    and score_eps_basic_line(label) >= 50_000
                ) or (
                    field_def.field_id in ("cfo", "cfi", "cff")
                    and score_cashflow_line(label, 0, len(amounts)) >= 20_000
                    and re.search(r"^net cash", label, re.I)
                )
                if (
                    grid_net_cash
                    and grid_count >= len(period_ends)
                    and field_def.field_id in ("cfo", "cfi", "cff")
                ):
                    continue
                if not text_authoritative and not (
                    amounts
                    and len(amounts) > grid_count
                    and len(amounts) >= min(stmt_cols, MAX_COLS[statement_type])
                ):
                    continue
                values = [v for v in values if v.field_id != field_def.field_id]
                extracted_fields.discard(field_def.field_id)

            if not amounts:
                if field_def.field_id not in extracted_fields:
                    pass  # finalize_pdf_errors 在 service 层统一补全
                continue

            stmt_periods = statement_periods[statement_type][:max_periods]
            text_amounts = amounts
            if statement_type == "balance" and statement_grids.get("balance"):
                grid_periods = statement_grids["balance"].period_ends[:max_periods]
                if grid_periods:
                    stmt_periods = [
                        StatementPeriod(period_end=pe, label=pe, year=int(pe[:4]))
                        for pe in grid_periods
                    ]
                    if len(text_amounts) > len(stmt_periods):
                        text_amounts = text_amounts[: len(stmt_periods)]

            for col_idx, stmt_period in enumerate(stmt_periods):
                if col_idx >= len(text_amounts):
                    break
                values.append(
                    FieldValue(
                        field_id=field_def.field_id,
                        period_end=stmt_period.period_end,
                        fiscal_year=stmt_period.year,
                        value=text_amounts[col_idx],
                        currency="USD",
                        scale=field_def.scale,
                        standard="US-GAAP",
                        source="pdf_text",
                        source_tag=label,
                        source_form="10-K",
                        filed_date="",
                    )
                )

        return PdfExtractionResult(
            source_path=document_path,
            source_type=source_type,
            statement_pages=statement_pages,
            statement_periods=statement_periods,
            values=values,
            periods=period_ends,
            errors=errors,
            statement_grids=statement_grids,
        )
