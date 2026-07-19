from enum import Enum
from dataclasses import dataclass
from typing import Optional

import fitz
import pdfplumber


class PageType(str, Enum):
    TEXT_NATIVE = "text_native"
    SCANNED = "scanned"
    MIXED = "mixed"


@dataclass
class PageProfile:
    page_num: int
    page_type: PageType
    has_tables: bool
    text_coverage: float
    image_coverage: float
    char_count: int


def _classify_from_objects(
    plumber_page,
    fitz_page,
    page_num: int,
    has_tables: Optional[bool] = None,
) -> PageProfile:
    """核心分类逻辑，接受已打开的页面对象，避免重复 I/O。"""
    chars = plumber_page.chars
    char_count = len(chars)
    page_area = plumber_page.width * plumber_page.height
    text_area = (
        sum((c["x1"] - c["x0"]) * (c["bottom"] - c["top"]) for c in chars)
        if chars
        else 0
    )
    text_coverage = text_area / page_area if page_area else 0

    if has_tables is None:
        tables = plumber_page.extract_tables()
        has_tables = len(tables) > 0

    page_rect_area = fitz_page.rect.width * fitz_page.rect.height
    image_area = 0.0
    for block in fitz_page.get_text("dict")["blocks"]:
        if block.get("type") == 1:
            x0, y0, x1, y1 = block["bbox"]
            image_area += (x1 - x0) * (y1 - y0)
    image_coverage = image_area / page_rect_area if page_rect_area else 0

    if char_count < 10 and image_coverage > 0.3:
        page_type = PageType.SCANNED
    elif char_count < 10 and text_coverage < 0.001:
        page_type = PageType.SCANNED
    elif char_count > 50 and text_coverage > 0.001:
        page_type = PageType.TEXT_NATIVE
    else:
        page_type = PageType.MIXED

    return PageProfile(
        page_num=page_num,
        page_type=page_type,
        has_tables=has_tables,
        text_coverage=text_coverage,
        image_coverage=image_coverage,
        char_count=char_count,
    )


def classify_page(
    pdf_path: str,
    page_num: int,
    plumber_page=None,
    fitz_page=None,
    has_tables: Optional[bool] = None,
) -> PageProfile:
    """分类页面类型。

    如果传入预打开的 plumber_page / fitz_page 则直接使用，不重复打开文件；
    否则自行打开（向后兼容）。
    has_tables 如果已从调用方预计算，可跳过 extract_tables() 二次调用。
    """
    _plumber_pdf = None
    _fitz_doc = None

    if plumber_page is None:
        _plumber_pdf = pdfplumber.open(pdf_path)
        plumber_page = _plumber_pdf.pages[page_num]

    if fitz_page is None:
        _fitz_doc = fitz.open(pdf_path)
        fitz_page = _fitz_doc[page_num]

    try:
        return _classify_from_objects(plumber_page, fitz_page, page_num, has_tables=has_tables)
    finally:
        if _plumber_pdf is not None:
            _plumber_pdf.close()
        if _fitz_doc is not None:
            _fitz_doc.close()
