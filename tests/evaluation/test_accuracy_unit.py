import pandas as pd

from backend.evaluation.accuracy import compare_grids, grid_from_expected, normalize_cell
from backend.pipeline.text_grid_extractor import extract_text_grid_from_page


def test_normalize_cell():
    assert normalize_cell("1,000.00") == "1000"
    assert normalize_cell("¥ 280") == "280"


def test_compare_grids_exact_match():
    expected = grid_from_expected([["A", "B"], ["1", "2"]])
    actual = grid_from_expected([["A", "B"], ["1", "2"]])
    assert compare_grids(expected, actual) == 1.0


def test_compare_grids_partial_offset():
    expected = grid_from_expected([["North", "100"], ["South", "80"]])
    actual = grid_from_expected([["", ""], ["North", "100"], ["South", "80"]])
    assert compare_grids(expected, actual) >= 0.9


def test_text_grid_extractor_on_borderless_pdf():
    from tests.benchmark.generate_corpus import BENCHMARK_DIR, ensure_benchmark_corpus
    import pdfplumber

    ensure_benchmark_corpus()
    pdf_path = BENCHMARK_DIR / "borderless_financial.pdf"
    with pdfplumber.open(str(pdf_path)) as pdf:
        df = extract_text_grid_from_page(pdf.pages[0])
    assert df is not None
    assert len(df) >= 4
    flat = df.astype(str).values.flatten().tolist()
    assert any("North" in v for v in flat)
