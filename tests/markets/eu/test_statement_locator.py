"""Tests for ESEF statement locator."""

from __future__ import annotations

import fitz
import pytest

from backend.markets.eu.statement_locator import (
    _esef_validate_statement_page,
    locate_esef_statements_from_pages,
)
from tests.benchmark.financial_esef.corpus import corpus_path, available_entries


def _load_pages(xhtml_path: str) -> list[str]:
    doc = fitz.open(xhtml_path)
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    return pages


@pytest.mark.skipif(
    not any(e["id"] == "ADYEN" for e in available_entries()),
    reason="ADYEN ESEF corpus not downloaded",
)
def test_esef_locator_adyen_finds_all_three_statements() -> None:
    entry = next(e for e in available_entries() if e["id"] == "ADYEN")
    pages = _load_pages(str(corpus_path(entry)))
    found = locate_esef_statements_from_pages(pages)
    assert "income" in found
    assert "balance" in found
    assert "cashflow" in found
    assert found["balance"] < 450, "should not pick company balance sheet in tail section"
    assert _esef_validate_statement_page(pages[found["income"]], "income")
    assert _esef_validate_statement_page(pages[found["balance"]], "balance")
    assert _esef_validate_statement_page(pages[found["cashflow"]], "cashflow")


@pytest.mark.skipif(
    not any(e["id"] == "ADYEN" for e in available_entries()),
    reason="ADYEN ESEF corpus not downloaded",
)
def test_esef_adyen_field_coverage_and_identity() -> None:
    from backend.global_schema.registry import GLOBAL_FIELDS_V1
    from backend.markets.eu.financials_service import EuFinancialsService

    entry = next(e for e in available_entries() if e["id"] == "ADYEN")
    result = EuFinancialsService().build_verified_financials(
        lei=entry["lei"],
        fiscal_year=entry["fiscal_year"],
        document_path=str(corpus_path(entry)),
        export_excel=False,
        export_formula_excel=False,
    )
    periods = set(result.pdf.periods or [])
    lookup = {(v.field_id, v.period_end) for v in result.pdf.values if v.value is not None}
    hits = sum(
        1
        for field_def in GLOBAL_FIELDS_V1
        for period in periods
        if (field_def.field_id, period) in lookup
    )
    total = len(GLOBAL_FIELDS_V1) * len(periods)
    assert hits >= 18, f"expected >=18 field hits, got {hits}/{total}"
    assert result.identity_report.all_passed


@pytest.mark.skipif(
    not any(e["id"] == "LVMH" for e in available_entries()),
    reason="LVMH ESEF corpus not downloaded",
)
def test_esef_locator_lvmh_french_statements() -> None:
    entry = next(e for e in available_entries() if e["id"] == "LVMH")
    pages = _load_pages(str(corpus_path(entry)))
    found = locate_esef_statements_from_pages(pages)
    assert len(found) >= 2, f"expected at least 2 statements, got {found}"
