from __future__ import annotations

from pathlib import Path

import pytest

from backend.markets.us.financials_service import UsFinancialsService

APPLE_PDF = Path("data/samples/apple_2024_annual_report_10k.pdf")


@pytest.mark.skipif(not APPLE_PDF.exists(), reason="Apple 10-K sample PDF missing")
def test_apple_verified_financials_production_quality():
    service = UsFinancialsService()
    result = service.build_verified_financials(
        ticker="AAPL",
        periods=2,
        document_path=str(APPLE_PDF),
        export_excel=False,
    )
    assert result.verification_rate >= 0.85
    assert result.reconciliation.mismatch_count <= 2
    assert len(result.reconciliation.periods) >= 2
