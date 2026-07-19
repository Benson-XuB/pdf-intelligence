from __future__ import annotations

from pathlib import Path

import pytest

from backend.markets.us.html_grid_extractor import extract_html_statement_grids
from backend.markets.us.pdf_extractor import UsPdfTextExtractor
from backend.markets.us.statement_locator import locate_statements_from_pages

NVDA_HTM = Path("tests/benchmark/financial_10k/nvda_10k.htm")
TSLA_HTM = Path("tests/benchmark/financial_10k/tsla_10k.htm")
UNH_HTM = Path("tests/benchmark/financial_10k/unh_10k.htm")
WMT_HTM = Path("tests/benchmark/financial_10k/wmt_10k.htm")


def _pages(path: Path) -> list[str]:
    import fitz

    doc = fitz.open(path)
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    return pages


@pytest.mark.skipif(not NVDA_HTM.exists(), reason="NVDA HTML missing")
def test_nvda_html_grid_finds_three_statements():
    pages = _pages(NVDA_HTM)
    statement_pages = locate_statements_from_pages(pages)
    grids = extract_html_statement_grids(str(NVDA_HTM), statement_pages, pages)
    assert set(grids.keys()) == {"income", "balance", "cashflow"}
    assert len(grids["income"].period_ends) >= 3


@pytest.mark.skipif(not NVDA_HTM.exists(), reason="NVDA HTML missing")
def test_nvda_html_extractor_uses_grid_for_revenue():
    result = UsPdfTextExtractor().extract(str(NVDA_HTM), max_periods=3)
    revenue = [v for v in result.values if v.field_id == "revenue"]
    assert revenue
    assert any(v.source == "html_grid" for v in revenue)
    assert max(v.value for v in revenue) > 100_000


@pytest.mark.skipif(not TSLA_HTM.exists(), reason="TSLA HTML missing")
def test_tsla_html_grid_income_has_three_periods():
    pages = _pages(TSLA_HTM)
    statement_pages = locate_statements_from_pages(pages)
    grids = extract_html_statement_grids(str(TSLA_HTM), statement_pages, pages)
    assert "income" in grids
    assert len(grids["income"].period_ends) >= 3


@pytest.mark.skipif(not UNH_HTM.exists(), reason="UNH HTML missing")
def test_unh_html_grid_uses_consolidated_balance_sheet():
    pages = _pages(UNH_HTM)
    statement_pages = locate_statements_from_pages(pages)
    grids = extract_html_statement_grids(str(UNH_HTM), statement_pages, pages)
    assert "balance" in grids
    result = UsPdfTextExtractor().extract(str(UNH_HTM), max_periods=2)
    assets = {v.period_end: v.value for v in result.values if v.field_id == "total_assets"}
    liabilities = {v.period_end: v.value for v in result.values if v.field_id == "total_liabilities"}
    assert assets["2025-12-31"] == 309_581.0
    assert liabilities["2025-12-31"] == 207_883.0
    assert all(v.source == "html_grid" for v in result.values if v.field_id in ("total_assets", "total_liabilities"))


@pytest.mark.skipif(not UNH_HTM.exists(), reason="UNH HTML missing")
def test_unh_html_grid_cashflow_matches_consolidated_statement():
    result = UsPdfTextExtractor().extract(str(UNH_HTM), max_periods=2)
    cfi = {v.period_end: v.value for v in result.values if v.field_id == "cfi"}
    cff = {v.period_end: v.value for v in result.values if v.field_id == "cff"}
    assert cfi["2025-12-31"] == -8685.0
    assert cff["2025-12-31"] == -11644.0


@pytest.mark.skipif(not WMT_HTM.exists(), reason="WMT HTML missing")
def test_wmt_html_grid_revenue_and_net_income():
    result = UsPdfTextExtractor().extract(str(WMT_HTM), max_periods=3)
    revenue = sorted(
        [v.value for v in result.values if v.field_id == "revenue"],
        reverse=True,
    )
    net_income = sorted(
        [v.value for v in result.values if v.field_id == "net_income"],
        reverse=True,
    )
    assert revenue == [713_163.0, 680_985.0, 648_125.0]
    assert net_income == [21_893.0, 19_436.0, 15_511.0]
