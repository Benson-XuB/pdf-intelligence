from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from backend.evaluation.financial_statement import extract_ground_truth, locate_statements
from backend.markets.us.statement_locator import locate_statements_from_pages
from tests.benchmark.financial_10k.corpus_pdf import CORPUS_X_ARCHIVE, entries_for_tier

TSLA_ARS_PDF = Path("tests/benchmark/financial_10k/tsla_2024_10k.pdf")
TSLA_SEC_HTM = Path("tests/benchmark/financial_10k/tsla_10k.htm")


def _pages(path: Path) -> list[str]:
    doc = fitz.open(path)
    pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
    doc.close()
    return pages


@pytest.mark.skipif(not TSLA_ARS_PDF.exists(), reason="TSLA ARS PDF missing")
def test_tsla_ars_pdf_has_no_locatable_statements():
    found = locate_statements_from_pages(_pages(TSLA_ARS_PDF))
    assert found == {}


@pytest.mark.skipif(not TSLA_SEC_HTM.exists(), reason="TSLA SEC HTML missing")
def test_tsla_sec_html_locates_three_statements():
    found = locate_statements_from_pages(_pages(TSLA_SEC_HTM))
    assert set(found.keys()) == {"income", "balance", "cashflow"}


@pytest.mark.skipif(not TSLA_SEC_HTM.exists(), reason="TSLA SEC HTML missing")
def test_tsla_sec_html_extracts_revenue():
    pages = locate_statements(str(TSLA_SEC_HTM))
    truth = extract_ground_truth(str(TSLA_SEC_HTM), "income", pages["income"])
    revenue = next((i for i in truth.items if i.key == "total_net_sales"), None)
    assert revenue is not None
    assert revenue.values[0] > 50_000


def test_tier_c_corpus_entries_use_html():
    tier_c = entries_for_tier("C")
    assert {e["id"] for e in tier_c} >= {"TSLA", "CRM", "HD"}
    for entry in tier_c:
        assert Path(entry["dest"]).suffix.lower() in {".htm", ".html"}


def test_tier_x_archive_still_pdf_only():
    for entry in CORPUS_X_ARCHIVE:
        assert entry.get("tier") == "X"
        assert Path(entry["dest"]).suffix.lower() == ".pdf"
