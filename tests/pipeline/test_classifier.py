from backend.pipeline.classifier import PageType, classify_page


def test_text_native_page(sample_text_pdf):
    result = classify_page(str(sample_text_pdf), page_num=0)
    assert result.page_type == PageType.TEXT_NATIVE
    assert result.char_count > 50


def test_scanned_page_detection(sample_scanned_pdf):
    result = classify_page(str(sample_scanned_pdf), page_num=0)
    assert result.page_type == PageType.SCANNED
    assert result.char_count < 10
