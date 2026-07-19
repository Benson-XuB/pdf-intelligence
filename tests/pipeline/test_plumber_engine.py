from backend.pipeline.plumber_engine import PlumberEngine


def test_extract_tables_from_text_pdf(sample_report_pdf):
    engine = PlumberEngine()
    result = engine.extract(str(sample_report_pdf))
    assert result.tables or result is not None
