from pathlib import Path

import pytest

from backend.pipeline.exporter import ExcelExporter
from backend.pipeline.models import FinalTable
from backend.pipeline.orchestrator import PipelineOrchestrator
import pandas as pd


def test_orchestrator_exports_excel_for_report(sample_report_pdf, tmp_path):
    orchestrator = PipelineOrchestrator()
    output = tmp_path / "out.xlsx"
    result = orchestrator.process(str(sample_report_pdf), output_path=str(output))
    assert result.total_pages >= 1
    if result.tables:
        assert result.output_path is not None
        assert Path(result.output_path).exists()


def test_excel_exporter_creates_workbook(tmp_path):
    tables = [
        FinalTable(
            source="pdfplumber",
            page_num=0,
            table_index=0,
            dataframe=pd.DataFrame({"A": ["1", "2"], "B": ["3", "4"]}),
            confidence=0.9,
        )
    ]
    exporter = ExcelExporter()
    out = exporter.export(tables, {"test": "ok"}, str(tmp_path / "test.xlsx"))
    assert Path(out).exists()
