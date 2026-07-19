from __future__ import annotations

from pathlib import Path

import pytest

from backend.evaluation.financial_statement import extract_ground_truth, locate_statements
from backend.markets.us.financials_service import UsFinancialsService
from backend.validation.reconciliation import MatchStatus

AMZN_PDF = Path("tests/benchmark/financial_10k/amzn_2024_10k.pdf")


@pytest.mark.skipif(not AMZN_PDF.exists(), reason="AMZN 10-K sample missing")
def test_amzn_ground_truth_operating_income_not_non_operating():
    pages = locate_statements(str(AMZN_PDF))
    truth = extract_ground_truth(str(AMZN_PDF), "income", pages["income"])
    op = next(i for i in truth.items if i.key == "operating_income")
    assert op.values[:3] == [12248.0, 36852.0, 68593.0]


@pytest.mark.skipif(not AMZN_PDF.exists(), reason="AMZN 10-K sample missing")
def test_amzn_ground_truth_net_income_includes_2022_loss():
    pages = locate_statements(str(AMZN_PDF))
    truth = extract_ground_truth(str(AMZN_PDF), "income", pages["income"])
    ni = next(i for i in truth.items if i.key == "net_income")
    assert ni.values[0] == -2722.0
    assert ni.values[1:] == [30425.0, 59248.0]


@pytest.mark.skipif(not AMZN_PDF.exists(), reason="AMZN 10-K sample missing")
def test_amzn_verified_financials_income_lines_match_xbrl():
    result = UsFinancialsService().build_verified_financials(
        ticker="AMZN",
        periods=3,
        document_path=str(AMZN_PDF),
        export_excel=False,
    )
    for field_id in ("revenue", "operating_income", "net_income", "eps_basic"):
        for item in result.reconciliation.items:
            if item.field_id != field_id:
                continue
            assert item.status == MatchStatus.MATCHED, (
                f"{field_id} {item.period_end}: xbrl={item.xbrl_value} pdf={item.pdf_value}"
            )
