from backend.pipeline.classifier import PageType, classify_page
from backend.pipeline.confidence import score_page
from backend.pipeline.models import ExtractedTable, PlumberTable
import pandas as pd


def test_high_confidence_when_engines_agree(sample_report_pdf):
    df = pd.DataFrame(
        {"A": ["North", "South", "合计"], "B": ["100", "80", "180"]},
    )
    docling_tables = [
        ExtractedTable(0, 0, df, 0.9, False),
    ]
    plumber_tables = [
        PlumberTable(0, 0, df.copy()),
    ]
    profile = classify_page(str(sample_report_pdf), 0)
    report = score_page(docling_tables, plumber_tables, profile)
    assert 0 <= report.score <= 1.0
    assert report.breakdown["cross_engine"] >= 0.8


def test_low_confidence_triggers_qwen_for_scanned(sample_scanned_pdf):
    profile = classify_page(str(sample_scanned_pdf), 0)
    report = score_page([], [], profile)
    assert profile.page_type == PageType.SCANNED
    assert report.needs_qwen is True
    assert "扫描页未提取到表格" in report.reasons


def test_cross_engine_disagreement_triggers_qwen():
    docling_df = pd.DataFrame({"col": ["100", "200", "300"]})
    plumber_df = pd.DataFrame({"col": ["100", "999", "300"]})
    from backend.pipeline.classifier import PageProfile

    profile = PageProfile(0, PageType.TEXT_NATIVE, True, 0.1, 0.0, 200)
    report = score_page(
        [ExtractedTable(0, 0, docling_df, 0.9, False)],
        [PlumberTable(0, 0, plumber_df)],
        profile,
    )
    assert report.needs_qwen is True
    assert "双引擎结果不一致" in report.reasons
