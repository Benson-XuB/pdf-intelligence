from __future__ import annotations

from pathlib import Path

import pytest

from backend.markets.us.pdf_extractor import UsPdfTextExtractor


GOOGL_PDF = Path("tests/benchmark/financial_10k/googl_2024_10k.pdf")


@pytest.mark.skipif(not GOOGL_PDF.exists(), reason="GOOGL benchmark PDF missing")
def test_googl_balance_cash_and_derived_fields():
    result = UsPdfTextExtractor().extract(str(GOOGL_PDF), max_periods=3)
    assets = {v.period_end: v.value for v in result.values if v.field_id == "total_assets"}
    liabilities = {v.period_end: v.value for v in result.values if v.field_id == "total_liabilities"}
    equity = {v.period_end: v.value for v in result.values if v.field_id == "total_equity"}
    cash = {v.period_end: v.value for v in result.values if v.field_id == "cash"}

    assert assets.get("2024-12-31") == 450_256.0
    assert liabilities.get("2024-12-31") == 125_172.0
    assert equity.get("2024-12-31") == 325_084.0
    assert cash.get("2024-12-31") == 23_466.0
    assert liabilities.get("2023-12-31") == 119_013.0
    assert equity.get("2023-12-31") == 283_379.0
    assert cash.get("2023-12-31") == 24_048.0

    for period in ("2023-12-31", "2024-12-31"):
        if period in assets and period in liabilities and period in equity:
            assert abs(assets[period] - liabilities[period] - equity[period]) < 1.0
