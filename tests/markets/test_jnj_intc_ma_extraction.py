from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.evaluation.financial_statement import extract_ground_truth, locate_statements
from backend.markets.us.financials_service import UsFinancialsService
from backend.markets.us.statement_grid_extractor import (
    _dedupe_stuttered_text,
    _detect_period_columns,
    _normalize_label,
    build_statement_grid,
)
from backend.pipeline.text_grid_extractor import extract_text_grid_from_page
import pdfplumber

JNJ_PDF = Path("tests/benchmark/financial_10k/jnj_2024_10k.pdf")
INTC_PDF = Path("tests/benchmark/financial_10k/intc_2024_10k.pdf")
MA_PDF = Path("tests/benchmark/financial_10k/ma_2024_10k.pdf")


def test_dedupe_stuttered_pdf_text():
    assert _dedupe_stuttered_text("NNeett  rreevveennuuee") == "Net revenue"
    assert _normalize_label("GGrroossss  mmaarrggiinn") == "gross margin"


def test_detect_period_columns_from_dataframe_column_names():
    df = pd.DataFrame(
        [["Sales", "$88,821", "85,159", "79,990"]],
        columns=["", "2024", "2023", "2022"],
    )
    cols, periods = _detect_period_columns(df, "Year ended December 29, 2024")
    assert cols == [1, 2, 3]
    assert periods == ["2024-12-31", "2023-12-31", "2022-12-31"]


@pytest.mark.skipif(not JNJ_PDF.exists(), reason="JNJ PDF missing")
def test_jnj_income_grid_builds_from_year_column_headers():
    pages = locate_statements(str(JNJ_PDF))
    with pdfplumber.open(JNJ_PDF) as pdf:
        page = pdf.pages[pages["income"]]
        import fitz

        text = fitz.open(JNJ_PDF)[pages["income"]].get_text()
        grid = build_statement_grid(page, text, "income")
    assert grid is not None
    assert len(grid.period_ends) == 3
    labels = dict(grid.rows)
    assert "Gross profit" in labels or any("gross profit" in k.lower() for k in labels)


@pytest.mark.skipif(not MA_PDF.exists(), reason="MA PDF missing")
def test_ma_ground_truth_total_liabilities_not_combined_line():
    pages = locate_statements(str(MA_PDF))
    truth = extract_ground_truth(str(MA_PDF), "balance", pages["balance"])
    liab = next(i for i in truth.items if i.key == "total_liabilities")
    assert liab.values[:2] == [46411.0, 41566.0]


@pytest.mark.skipif(not all(p.exists() for p in (JNJ_PDF, INTC_PDF, MA_PDF)), reason="PDF samples missing")
@pytest.mark.parametrize(
    "ticker,pdf_path,min_accuracy",
    [
        ("JNJ", str(JNJ_PDF), 0.85),
        ("INTC", str(INTC_PDF), 0.85),
        ("MA", str(MA_PDF), 0.90),
    ],
)
def test_verified_pdf_extraction_accuracy(ticker, pdf_path, min_accuracy):
    from scripts.run_verified_accuracy_benchmark import evaluate_company

    report = evaluate_company({"id": ticker, "name": ticker, "pdf": pdf_path}, periods=3)
    assert report is not None
    assert report.pdf_extraction_accuracy >= min_accuracy, report.details


def test_total_equity_prefers_parent_shareholders_line():
    from backend.global_schema.registry import field_by_id
    from backend.markets.us.statement_grid_extractor import _row_label_score

    field = field_by_id()["total_equity"]
    parent = "Total JD.com, Inc. shareholders' equity"
    consolidated = "Total shareholders' equity"
    assert _row_label_score(parent, field) > _row_label_score(consolidated, field)
    assert _row_label_score("MEZZANINE EQUITY", field) == 0.0
