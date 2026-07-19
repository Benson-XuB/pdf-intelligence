from pathlib import Path
from typing import Optional

import pandas as pd
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorOptions,
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

from backend.config import settings
from backend.pipeline.models import DoclingResult, ExtractedTable

DEFAULT_ARTIFACTS_PATH = Path.home() / ".cache/docling/models"

# 传统模式：减少 ONNX Runtime 线程池，避免与 ThreadPoolExecutor 争核
_ONNX_THREADS = 2


def _has_real_merged_cells(item) -> bool:
    try:
        cells = item.data.table_cells if hasattr(item, "data") else None
        if not cells:
            return False
        for cell in cells:
            rs = getattr(cell, "row_span", 1)
            cs = getattr(cell, "col_span", 1)
            if rs > 1 or cs > 1:
                return True
        return False
    except Exception:
        return False


class DoclingEngine:
    def __init__(
        self,
        artifacts_path: Optional[Path] = None,
        use_vlm: Optional[bool] = None,
        fast_mode: Optional[bool] = None,
    ) -> None:
        art_path = artifacts_path or DEFAULT_ARTIFACTS_PATH
        self._use_vlm = use_vlm if use_vlm is not None else settings.docling_use_vlm
        self._fast_mode = fast_mode if fast_mode is not None else settings.docling_fast_mode

        if self._use_vlm:
            self.converter = self._build_vlm_converter(art_path)
        else:
            self.converter = self._build_standard_converter(art_path, fast_mode=self._fast_mode)

    @classmethod
    def _build_standard_converter(cls, art_path: Path, fast_mode: bool = False) -> DocumentConverter:
        mode = TableFormerMode.FAST if fast_mode else TableFormerMode.ACCURATE
        options = PdfPipelineOptions(artifacts_path=str(art_path))
        options.do_table_structure = True
        options.table_structure_options = TableStructureOptions(
            mode=mode,
            do_cell_matching=True,
        )
        options.do_ocr = False
        options.accelerator_options = AcceleratorOptions(num_threads=_ONNX_THREADS)
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    @staticmethod
    def _build_vlm_converter(art_path: Path) -> DocumentConverter:
        from docling.datamodel.pipeline_options import (
            VlmPipelineOptions,
            smoldocling_vlm_conversion_options,
        )
        from docling.pipeline.vlm_pipeline import VlmPipeline

        pipeline_options = VlmPipelineOptions(
            artifacts_path=str(art_path),
            vlm_options=smoldocling_vlm_conversion_options,
            accelerator_options=AcceleratorOptions(num_threads=2),
        )
        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=VlmPipeline,
                    pipeline_options=pipeline_options,
                )
            }
        )

    def extract(self, pdf_path: str) -> DoclingResult:
        result = self.converter.convert(pdf_path)
        tables: list[ExtractedTable] = []
        table_index = 0

        for item, _level in result.document.iterate_items():
            label = getattr(item, "label", None)
            if str(label).lower() != "table":
                continue
            try:
                df = item.export_to_dataframe(doc=result.document)
            except Exception:
                continue
            if df is None or df.empty:
                continue

            page_num = 0
            prov = getattr(item, "prov", None)
            if prov and len(prov) > 0:
                page_num = max(getattr(prov[0], "page_no", 1) - 1, 0)

            tables.append(
                ExtractedTable(
                    page_num=page_num,
                    table_index=table_index,
                    dataframe=df,
                    confidence=0.9,
                    has_merged_cells=_has_real_merged_cells(item),
                )
            )
            table_index += 1

        page_count = len(result.document.pages) if hasattr(result.document, "pages") else 0
        return DoclingResult(
            tables=tables,
            page_count=page_count,
        )
