from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from backend.markets.hk.statement_locator import locate_hk_statements_from_pages
from backend.markets.hk.pdf_extractor import HkPdfTextExtractor
from backend.markets.us.statement_grid_extractor import _statement_page_span, _expand_statement_start
from backend.markets.us.statement_locator import _validate_statement_page
from backend.markets.us.period_parser import filter_reporting_periods, parse_statement_periods, StatementPeriod

JD_PDF = Path("tests/benchmark/financial_hk/9618_annual.pdf")


def _pages(path: Path) -> list[str]:
    doc = fitz.open(path)
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    return pages


def test_filter_reporting_periods_drops_announcement_dates():
    periods = [
        StatementPeriod("2025-02-19", "19 February 2025", 2025),
        StatementPeriod("2024-12-31", "31 December 2024", 2024),
        StatementPeriod("2023-12-31", "31 December 2023", 2023),
    ]
    filtered = filter_reporting_periods(periods)
    assert [p.period_end for p in filtered] == ["2024-12-31", "2023-12-31"]


@pytest.mark.skipif(not JD_PDF.exists(), reason="JD HK PDF missing")
def test_jd_locator_skips_selected_summary_income():
    pages = _pages(JD_PDF)
    found = locate_hk_statements_from_pages(pages)
    assert found["income"] >= 260
    merged = "\n".join(pages[found["income"] : found["income"] + 2])
    periods = parse_statement_periods(merged, max_periods=3)
    assert [p.period_end for p in periods] == ["2022-12-31", "2023-12-31", "2024-12-31"]


@pytest.mark.skipif(not JD_PDF.exists(), reason="JD HK PDF missing")
def test_jd_balance_first_page_valid_with_annual_report_header():
    pages = _pages(JD_PDF)
    assert _validate_statement_page(pages[265], "balance") is True


@pytest.mark.skipif(not JD_PDF.exists(), reason="JD HK PDF missing")
def test_jd_balance_span_includes_assets_page():
    pages = _pages(JD_PDF)
    found = locate_hk_statements_from_pages(pages)
    start = _expand_statement_start(pages, found["balance"], "balance")
    span_start, span_end = _statement_page_span(pages, found["balance"], "balance")
    assert start == 265
    assert span_start == 265
    assert span_end == 268


@pytest.mark.skipif(not JD_PDF.exists(), reason="JD HK PDF missing")
def test_jd_extracts_balance_and_eps_after_multipage_merge():
    result = HkPdfTextExtractor().extract(str(JD_PDF))
    assert any(v.field_id == "total_assets" for v in result.values)
    assert any(v.field_id == "cash" for v in result.values)
    assert any(v.field_id == "eps_basic" for v in result.values)
    assert any(v.field_id == "capex" for v in result.values)


KS_PDF = Path("tests/benchmark/financial_hk/1024_annual.pdf")
BYD_PDF = Path("tests/benchmark/financial_hk/1211_annual.pdf")


@pytest.mark.skipif(not KS_PDF.exists(), reason="Kuaishou HK PDF missing")
def test_kuaishou_locates_condensed_cashflow_statement():
    import fitz

    doc = fitz.open(KS_PDF)
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    found = locate_hk_statements_from_pages(pages)
    assert found.get("cashflow") == 30
    result = HkPdfTextExtractor().extract(str(KS_PDF))
    assert any(v.field_id == "cfo" for v in result.values)
    assert any(v.field_id == "cfi" for v in result.values)


@pytest.mark.skipif(not BYD_PDF.exists(), reason="BYD HK PDF missing")
def test_byd_locates_consolidated_cash_flow_statement():
    import fitz

    doc = fitz.open(BYD_PDF)
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    found = locate_hk_statements_from_pages(pages)
    assert found.get("cashflow") == 130
    result = HkPdfTextExtractor().extract(str(BYD_PDF))
    assert any(v.field_id == "cfo" for v in result.values)


HSBC_PDF = Path("tests/benchmark/financial_hk/0005_annual.pdf")
CCB_PDF = Path("tests/benchmark/financial_hk/0939_annual.pdf")


@pytest.mark.skipif(not HSBC_PDF.exists(), reason="HSBC HK PDF missing")
def test_hsbc_bank_income_balance_extraction():
    result = HkPdfTextExtractor().extract(str(HSBC_PDF), stock_code="0005", max_periods=3)
    by_field = {v.field_id: v.value for v in result.values if v.period_end == "2024-12-31"}
    assert by_field.get("revenue") == 65854.0
    assert by_field.get("total_liabilities") == 2824775.0
    assert by_field.get("cash") == 434940.0
    assert "gross_profit" not in {v.field_id for v in result.values}
    assert "PDF 未提取到: gross_profit" not in result.errors


@pytest.mark.skipif(not CCB_PDF.exists(), reason="CCB HK PDF missing")
def test_ccb_annual_locates_statements_and_extracts_bank_fields():
    import fitz

    doc = fitz.open(CCB_PDF)
    head = doc[0].get_text()[:200]
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    assert "Half-Year" not in head
    assert len(pages) > 250
    found = locate_hk_statements_from_pages(pages)
    assert "income" in found and "balance" in found and "cashflow" in found
    result = HkPdfTextExtractor().extract(str(CCB_PDF), stock_code="0939", max_periods=3)
    fields = {v.field_id for v in result.values if v.value is not None}
    assert {"revenue", "total_assets", "total_liabilities", "cfo", "net_income"} <= fields
