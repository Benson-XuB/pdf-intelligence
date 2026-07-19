from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from backend.evaluation.financial_statement import extract_ground_truth, locate_statements
from backend.markets.us.statement_locator import locate_statements_from_pages

V_PDF = Path("tests/benchmark/financial_10k/v_2024_10k.pdf")
JNJ_PDF = Path("tests/benchmark/financial_10k/jnj_2024_10k.pdf")
CRM_PDF = Path("tests/benchmark/financial_10k/crm_2024_10k.pdf")
MSFT_PDF = Path("tests/benchmark/financial_10k/msft_2024_10k.pdf")


def _pages(path: Path) -> list[str]:
    doc = fitz.open(path)
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    return pages


@pytest.mark.skipif(not V_PDF.exists(), reason="Visa PDF missing")
def test_v_ars_locator_finds_three_statements():
    found = locate_statements_from_pages(_pages(V_PDF))
    assert set(found.keys()) == {"income", "balance", "cashflow"}


@pytest.mark.skipif(not V_PDF.exists(), reason="Visa PDF missing")
def test_v_ground_truth_includes_dot_leader_revenue_and_cashflow():
    pages = locate_statements(str(V_PDF))
    income = extract_ground_truth(str(V_PDF), "income", pages["income"])
    revenue = next(i for i in income.items if i.key == "total_net_sales")
    assert revenue.values[:3] == [40000.0, 35926.0, 32653.0]

    cashflow = extract_ground_truth(str(V_PDF), "cashflow", pages["cashflow"])
    operating = next(i for i in cashflow.items if i.key == "operating")
    assert operating.values[0] > 15_000


@pytest.mark.skipif(not JNJ_PDF.exists(), reason="JNJ PDF missing")
def test_jnj_income_not_matched_from_mda_page():
    found = locate_statements_from_pages(_pages(JNJ_PDF))
    assert found["income"] == 49


@pytest.mark.skipif(not CRM_PDF.exists(), reason="CRM PDF missing")
def test_crm_marketing_pdf_has_no_locatable_statements():
    found = locate_statements_from_pages(_pages(CRM_PDF))
    assert len(found) == 0


@pytest.mark.skipif(not Path('tests/benchmark/financial_10k/jpm_2024_10k.pdf').exists(), reason='JPM PDF missing')
def test_jpm_ars_locator_finds_untitled_statements():
    from backend.markets.us.statement_locator import locate_statements_from_pages
    import fitz

    path = Path('tests/benchmark/financial_10k/jpm_2024_10k.pdf')
    doc = fitz.open(path)
    pages = [doc[i].get_text().replace('\xa0', ' ') for i in range(len(doc))]
    doc.close()
    found = locate_statements_from_pages(pages)
    assert found.get('income') == 205
    assert found.get('balance') == 207
    assert found.get('cashflow') == 209


@pytest.mark.skipif(not Path('tests/benchmark/financial_10k/v_2024_10k.pdf').exists(), reason='Visa PDF missing')
def test_v_operating_income_matches_ground_truth():
    from backend.markets.us.pdf_extractor import UsPdfTextExtractor

    path = 'tests/benchmark/financial_10k/v_2024_10k.pdf'
    pages = locate_statements(path)
    truth = extract_ground_truth(path, 'income', pages['income'])
    expected = next(i for i in truth.items if i.key == 'operating_income').values
    ext = UsPdfTextExtractor().extract(path)
    actual = sorted(
        [v.value for v in ext.values if v.field_id == 'operating_income'],
        reverse=True,
    )
    assert actual[:3] == expected[:3]


@pytest.mark.skipif(not MSFT_PDF.exists(), reason="MSFT PDF missing")
def test_msft_short_titles_locator_finds_three_statements():
    found = locate_statements_from_pages(_pages(MSFT_PDF))
    assert set(found.keys()) == {"income", "balance", "cashflow"}


@pytest.mark.skipif(not MSFT_PDF.exists(), reason="MSFT PDF missing")
def test_msft_pdf_extractor_includes_balance_and_cashflow():
    from backend.markets.us.pdf_extractor import UsPdfTextExtractor

    ext = UsPdfTextExtractor().extract(str(MSFT_PDF), max_periods=3)
    fields = {v.field_id for v in ext.values}
    assert {"total_assets", "cfo", "capex"}.issubset(fields)
