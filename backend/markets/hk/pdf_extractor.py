from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz

from backend.global_schema.models import CompanyFinancials, FieldValue, ValueScale
from backend.global_schema.registry import GLOBAL_FIELDS_V1, field_by_id
from backend.markets.hk.constants import HK_FILENAME_HINTS, normalize_hk_code
from backend.markets.hk.industry import industry_skipped_fields, industry_type
from backend.markets.hk.statement_locator import locate_hk_statements_from_pages
from backend.markets.us.pdf_extractor import (
    PdfExtractionResult,
    MAX_COLS,
    _extract_line_values,
    _load_document_text,
    _merged_period_ends,
)
from backend.markets.us.period_parser import align_periods_to_xbrl, parse_statement_periods, resolve_balance_periods
from backend.markets.us.statement_text import (
    cashflow_line_pattern,
    EPS_BASIC_TEXT_PATTERN,
    load_statement_text,
    score_cashflow_line,
    score_eps_basic_line,
    score_net_income_line,
    statement_unit_divisor,
)

# Global field -> (statement, bilingual regex)
HK_PDF_FIELD_PATTERNS: Dict[str, Tuple[str, str]] = {
    "revenue": (
        "income",
        r"(?:total\s+)?(?:net\s+)?(?:revenue|revenues|turnover)|"
        r"营业(?:总)?收入|营业收入|收入",
    ),
    "gross_profit": ("income", r"gross\s+profit|毛利|毛利润"),
    "operating_income": (
        "income",
        r"(?:operating\s+(?:profit|income)|income|loss)\s+from\s+operations|"
        r"经营[性]?溢利|经营利润|营业利润|"
        r"profit\s+from\s+operations",
    ),
    "net_income": (
        "income",
        r"(?:profit|income)\s+(?:for the year|attributable)|net\s+(?:profit|income)|"
        r"本公司(?:权益)?(?:拥有人|持有人)应占溢利|股东应占溢利|净利润",
    ),
    "eps_basic": (
        "income",
        EPS_BASIC_TEXT_PATTERN,
    ),
    "total_assets": ("balance", r"total\s+assets(?!\s+less)|总资产|资产总值|资产总额"),
    "total_liabilities": (
        "balance",
        r"total\s+liabilities(?!\s+and\s+(?:stockholders|shareholders|equity))|"
        r"总负债|负债总额|负债总值",
    ),
    "total_equity": (
        "balance",
        r"total\s+(?:equity|shareholders?.?\s+equity)|股东权益|权益总额|权益总值",
    ),
    "cash": (
        "balance",
        r"monetary funds|货币资金|貨幣資金|"
        r"cash and (?:cash equivalents|amounts due from banks)(?:\s+at\s+31|\s+at\s+1)?|"
        r"现金及现金等价物|现金及等同现金",
    ),
    "cfo": ("cashflow", cashflow_line_pattern("operating")),
    "cfi": ("cashflow", cashflow_line_pattern("investing")),
    "cff": ("cashflow", cashflow_line_pattern("financing")),
    "capex": (
        "cashflow",
        r"purchase(?:s)?(?:\s+and\s+prepayments)? of property|capital expenditure|"
        r"acquisition of fixed assets|payment for property,?\s*plant and equipment|"
        r"purchase and construction of fixed assets|"
        r"购置物业|购建固定资产|购建固定|资本开支",
    ),
}

INSURANCE_CASH_PATTERN = (
    "balance",
    r"cash and amounts due from banks|"
    r"货币资金|现金及(?:现金等价物|存放中央银行款项)",
)

BANK_REVENUE_PATTERN = (
    "income",
    r"net operating income(?:\s+before|\s*$)|"
    r"net interest income|"
    r"total operating income|"
    r"(?<![a-z/])operating income(?!\s*/|\s+includes|\s+margin)|"
    r"利息净收入|营业收入|经营收入",
)

BANK_CASH_PATTERN = (
    "balance",
    r"cash and (?:cash equivalents|deposits with central banks)|"
    r"现金及(?:现金等价物|存放中央银行款项)",
)


def hk_pdf_field_patterns(stock_code: str) -> Dict[str, Tuple[str, str]]:
    patterns = dict(HK_PDF_FIELD_PATTERNS)
    itype = industry_type(stock_code)
    if itype == "bank":
        patterns["revenue"] = BANK_REVENUE_PATTERN
        patterns["cash"] = BANK_CASH_PATTERN
    elif itype == "insurance":
        patterns["cash"] = INSURANCE_CASH_PATTERN
    return patterns


def _sum_balance_component_lines(
    page_text: str,
    non_current_pattern: str,
    current_pattern: str,
    unit_divisor: float = 1.0,
) -> Tuple[str, List[float]]:
    """部分 IFRS 资产负债表仅披露 current / non-current 分项合计。"""
    _, non_cur = _extract_line_values(
        page_text, "balance", non_current_pattern, "total_assets", unit_divisor=unit_divisor
    )
    _, current = _extract_line_values(
        page_text, "balance", current_pattern, "total_assets", unit_divisor=unit_divisor
    )
    if not non_cur or not current:
        return "", []
    cols = min(len(non_cur), len(current), MAX_COLS["balance"])
    amounts = [non_cur[i] + current[i] for i in range(cols)]
    label = f"{non_current_pattern} + {current_pattern}"
    return label, amounts


def _detect_report_currency(page_text: str) -> str:
    head = page_text[:2500].upper()
    if re.search(r"\bRMB\b|人民币|CNY", head):
        return "CNY"
    if re.search(r"\bHKD\b|港元|港幣", head):
        return "HKD"
    if re.search(r"\bUSD\b|US\$", head):
        return "USD"
    return "HKD"


@dataclass
class HkFilingDocument:
    form: str
    filing_date: str
    local_path: str
    stock_code: str


class HkFilingResolver:
    def resolve(self, ticker: str, explicit_path: Optional[str] = None) -> HkFilingDocument:
        code = normalize_hk_code(ticker)
        if explicit_path:
            path = Path(explicit_path)
            if not path.exists():
                raise FileNotFoundError(f"Document not found: {explicit_path}")
            return HkFilingDocument(
                form="Annual Report",
                filing_date="",
                local_path=str(path.resolve()),
                stock_code=code,
            )

        hints = HK_FILENAME_HINTS.get(code, [code.lstrip("0"), code])
        search_roots = [
            Path("tests/benchmark/financial_hk"),
            Path("data/samples/hk"),
            Path("data/filings/hk"),
        ]
        patterns = []
        for hint in hints:
            patterns.extend([f"*{hint}*annual*.pdf", f"*{hint}*ar*.pdf", f"*{hint}*.pdf", f"*{code}*.pdf"])

        candidates: List[Path] = []
        for root in search_roots:
            if not root.exists():
                continue
            for pattern in patterns:
                candidates.extend(root.glob(pattern))

        if not candidates:
            raise FileNotFoundError(
                f"No HK annual report PDF found for {code}. "
                f"Please place the file under tests/benchmark/financial_hk/ or upload via API."
            )

        best = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        return HkFilingDocument(
            form="Annual Report",
            filing_date="",
            local_path=str(best.resolve()),
            stock_code=code,
        )


class HkPdfTextExtractor:
    def extract(
        self,
        document_path: str,
        company_name: str = "",
        stock_code: str = "",
        target_periods: Optional[List[str]] = None,
        max_periods: int = 3,
    ) -> PdfExtractionResult:
        source_type, _ = _load_document_text(document_path)
        doc = fitz.open(document_path)
        pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
        doc.close()

        statement_pages = locate_hk_statements_from_pages(pages)
        if not statement_pages:
            return PdfExtractionResult(
                source_path=document_path,
                source_type=source_type,
                errors=["Could not locate financial statement pages in the HK annual report"],
            )

        statement_periods: Dict[str, List] = {}
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

        field_patterns = hk_pdf_field_patterns(stock_code)
        industry_skip = industry_skipped_fields(stock_code)

        report_currency = _detect_report_currency(
            "\n".join(statement_texts.get(st, "") for st in ("income", "balance", "cashflow"))
        )

        values: List[FieldValue] = []
        errors: List[str] = []
        registry = field_by_id()
        extracted_fields: set[str] = set()

        if source_type == "pdf":
            from backend.markets.us.statement_grid_extractor import StatementGridExtractor, STMT_FIELDS

            grid_extractor = StatementGridExtractor()
            xbrl_currency = report_currency
            if xbrl_currency == "RMB":
                xbrl_currency = "CNY"
            grids = grid_extractor.extract_page_grids(
                document_path,
                statement_pages,
                pages,
                preferred_currency=xbrl_currency,
            )
            if grids:
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
                            currency=report_currency,
                            scale=field_def.scale,
                            standard="IFRS",
                            source="hk_pdf_grid",
                            source_tag=label,
                            source_form="Annual Report",
                            filed_date="",
                        )
                    )
                errors.extend(grid_errors)

        for field_def in GLOBAL_FIELDS_V1:
            if field_def.field_id in industry_skip:
                continue
            mapping = field_patterns.get(field_def.field_id)
            if not mapping:
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
                    errors.append(f"PDF extraction failed for: {field_def.field_id}")
                continue

            col_map = align_periods_to_xbrl(statement_periods[statement_type], period_ends)
            for period_end in period_ends:
                col_idx = col_map.get(period_end)
                if col_idx is None or col_idx >= len(amounts):
                    continue
                values.append(
                    FieldValue(
                        field_id=field_def.field_id,
                        period_end=period_end,
                        fiscal_year=int(period_end[:4]),
                        value=amounts[col_idx],
                        currency=report_currency,
                        scale=field_def.scale,
                        standard="IFRS",
                        source="hk_pdf",
                        source_tag=label,
                        source_form="Annual Report",
                        filed_date="",
                    )
                )

        balance_text = statement_texts.get("balance", "")
        if balance_text and "balance" in statement_pages:
            balance_div = statement_unit_divisors.get("balance", 1.0)
            extracted_ids = {v.field_id for v in values if v.value is not None}
            composite_fields = (
                ("total_assets", r"total non-current assets", r"total current assets"),
                ("total_liabilities", r"total non-current liabilities", r"total current liabilities"),
            )
            for field_id, non_pat, cur_pat in composite_fields:
                if field_id in extracted_ids or field_id in industry_skip:
                    continue
                label, amounts = _sum_balance_component_lines(
                    balance_text, non_pat, cur_pat, unit_divisor=balance_div
                )
                if not amounts:
                    continue
                field_def = registry[field_id]
                col_map = align_periods_to_xbrl(statement_periods["balance"], period_ends)
                for period_end in period_ends:
                    col_idx = col_map.get(period_end)
                    if col_idx is None or col_idx >= len(amounts):
                        continue
                    values.append(
                        FieldValue(
                            field_id=field_id,
                            period_end=period_end,
                            fiscal_year=int(period_end[:4]),
                            value=amounts[col_idx],
                            currency=report_currency,
                            scale=field_def.scale,
                            standard="IFRS",
                            source="hk_pdf",
                            source_tag=label,
                            source_form="Annual Report",
                            filed_date="",
                        )
                    )
                errors = [e for e in errors if e != f"PDF extraction failed for: {field_id}"]

        text_stmt_types = {
            registry[v.field_id].statement.value
            for v in values
            if v.source == "hk_pdf"
        }
        errors = [
            e
            for e in errors
            if not (
                e.startswith("Missing statement grid:")
                and e.split(":", 1)[1].strip() in text_stmt_types
            )
        ]

        return PdfExtractionResult(
            source_path=document_path,
            source_type=source_type,
            statement_pages=statement_pages,
            statement_periods=statement_periods,
            values=values,
            periods=period_ends,
            errors=errors,
        )

    def to_company_financials(
        self,
        result: PdfExtractionResult,
        ticker: str,
        company_name: str = "",
    ) -> CompanyFinancials:
        code = normalize_hk_code(ticker)
        return CompanyFinancials(
            ticker=code,
            company_name=company_name or f"HK:{code}",
            market="HK",
            cik="",
            standard="IFRS",
            values=result.values,
            periods=result.periods,
            errors=result.errors,
        )
