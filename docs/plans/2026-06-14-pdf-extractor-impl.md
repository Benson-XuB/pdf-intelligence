# PDF 智能解析系统 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建 Web 应用，本地 Docling + pdfplumber 高精度解析 PDF，置信度低时按需调用 Qwen API，报表导出 Excel。

**Architecture:** 级联流水线 + 页面级置信度门控。本地双引擎并行提取，纯代码评分，仅低置信度页面调用 DashScope Qwen2.5-VL，融合后导出 Excel。

**Tech Stack:** Python 3.11, FastAPI, Celery, pdfplumber, Docling, PyMuPDF, DashScope SDK, pandas, openpyxl, React, PDF.js

---

## Phase 1: 项目骨架 + 本地解析核心

### Task 1: 初始化项目结构

**Files:**
- Create: `pdf-intelligence/pyproject.toml`
- Create: `pdf-intelligence/backend/__init__.py`
- Create: `pdf-intelligence/backend/config.py`
- Create: `pdf-intelligence/.env.example`
- Create: `pdf-intelligence/docker-compose.yml`

**Step 1: 创建 pyproject.toml**

```toml
[project]
name = "pdf-intelligence"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "celery[redis]>=5.3",
    "pdfplumber>=0.11",
    "docling>=2.0",
    "pymupdf>=1.24",
    "pandas>=2.2",
    "openpyxl>=3.1",
    "dashscope>=1.20",
    "pydantic-settings>=2.2",
    "python-multipart>=0.0.9",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.4"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 2: 创建 config.py**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    dashscope_api_key: str = ""
    confidence_threshold: float = 0.85
    qwen_model: str = "qwen-vl-max"
    upload_dir: str = "./data/uploads"
    output_dir: str = "./data/outputs"
    redis_url: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"

settings = Settings()
```

**Step 3: 创建 .env.example**

```
DASHSCOPE_API_KEY=sk-xxx
CONFIDENCE_THRESHOLD=0.85
QWEN_MODEL=qwen-vl-max
```

**Step 4: 验证安装**

```bash
cd pdf-intelligence && pip install -e ".[dev]"
python -c "import pdfplumber, docling; print('OK')"
```
Expected: `OK`

---

### Task 2: PDF 页面分类器

**Files:**
- Create: `backend/pipeline/classifier.py`
- Create: `tests/pipeline/test_classifier.py`

**Step 1: 写失败测试**

```python
# tests/pipeline/test_classifier.py
from backend.pipeline.classifier import classify_page, PageType

def test_text_native_page():
    # 使用 fixtures/sample_text.pdf 第一页
    result = classify_page("tests/fixtures/sample_text.pdf", page_num=0)
    assert result.page_type == PageType.TEXT_NATIVE
    assert result.has_tables is True or result.has_tables is False

def test_scanned_page_detection():
    result = classify_page("tests/fixtures/sample_scanned.pdf", page_num=0)
    assert result.page_type == PageType.SCANNED
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/pipeline/test_classifier.py -v
```
Expected: FAIL — module not found

**Step 3: 实现 classifier.py**

```python
from enum import Enum
from dataclasses import dataclass
import fitz  # PyMuPDF
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
    text_coverage: float      # 有文字层的面积比
    image_coverage: float     # 图片面积比
    char_count: int

def classify_page(pdf_path: str, page_num: int) -> PageProfile:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_num]
        chars = page.chars
        char_count = len(chars)
        page_area = page.width * page.height
        text_area = sum(
            (c["x1"] - c["x0"]) * (c["bottom"] - c["top"])
            for c in chars
        ) if chars else 0
        text_coverage = text_area / page_area if page_area else 0
        tables = page.extract_tables()
        has_tables = len(tables) > 0

    doc = fitz.open(pdf_path)
    fitz_page = doc[page_num]
    image_coverage = sum(
        (img[2] - img[0]) * (img[3] - img[1])
        for img in fitz_page.get_image_info()
    ) / (fitz_page.rect.width * fitz_page.rect.height)
    doc.close()

    if char_count < 10 and image_coverage > 0.5:
        page_type = PageType.SCANNED
    elif char_count > 50 and text_coverage > 0.01:
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
```

**Step 4: 运行测试**

```bash
pytest tests/pipeline/test_classifier.py -v
```
Expected: PASS（需准备 sample PDF fixtures）

---

### Task 3: Docling 引擎封装

**Files:**
- Create: `backend/pipeline/docling_engine.py`
- Create: `tests/pipeline/test_docling_engine.py`

**Step 1: 写失败测试**

```python
def test_extract_tables_from_pdf():
    from backend.pipeline.docling_engine import DoclingEngine
    engine = DoclingEngine()
    result = engine.extract("tests/fixtures/sample_report.pdf")
    assert len(result.tables) >= 1
    assert result.tables[0].dataframe is not None
    assert result.tables[0].confidence > 0
```

**Step 2: 实现 docling_engine.py**

```python
from dataclasses import dataclass, field
import pandas as pd
from docling.document_converter import DocumentConverter
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, TableStructureOptions, TableFormerMode,
)
from docling.datamodel.base_models import InputFormat
from docling.document_converter import PdfFormatOption

@dataclass
class ExtractedTable:
    page_num: int
    table_index: int
    dataframe: pd.DataFrame
    confidence: float
    has_merged_cells: bool

@dataclass
class DoclingResult:
    tables: list[ExtractedTable] = field(default_factory=list)
    full_text: str = ""
    page_count: int = 0

class DoclingEngine:
    def __init__(self):
        options = PdfPipelineOptions()
        options.do_table_structure = True
        options.table_structure_options = TableStructureOptions(
            mode=TableFormerMode.ACCURATE,
            do_cell_matching=True,
        )
        options.do_ocr = True
        self.converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    def extract(self, pdf_path: str) -> DoclingResult:
        result = self.converter.convert(pdf_path)
        tables = []
        for i, item in enumerate(result.document.iterate_items()):
            if item.label == "table":
                df = item.export_to_dataframe()
                if df is not None:
                    tables.append(ExtractedTable(
                        page_num=getattr(item, "page_no", 0),
                        table_index=i,
                        dataframe=df,
                        confidence=0.9,  # 后续由 confidence 模块重算
                        has_merged_cells=_detect_merged_cells(df),
                    ))
        return DoclingResult(
            tables=tables,
            full_text=result.document.export_to_markdown(),
            page_count=len(result.document.pages) if hasattr(result.document, "pages") else 0,
        )

def _detect_merged_cells(df: pd.DataFrame) -> bool:
    return df.isnull().sum().sum() > len(df) * 0.1
```

**Step 3: 运行测试**

```bash
pytest tests/pipeline/test_docling_engine.py -v
```

---

### Task 4: pdfplumber 引擎封装

**Files:**
- Create: `backend/pipeline/plumber_engine.py`
- Create: `tests/pipeline/test_plumber_engine.py`

**Step 1: 实现并测试**

```python
# backend/pipeline/plumber_engine.py
from dataclasses import dataclass, field
import pdfplumber
import pandas as pd

@dataclass
class PlumberTable:
    page_num: int
    table_index: int
    dataframe: pd.DataFrame

@dataclass
class PlumberResult:
    tables: list[PlumberTable] = field(default_factory=list)
    chars_by_page: dict[int, list] = field(default_factory=dict)

class PlumberEngine:
    def extract(self, pdf_path: str) -> PlumberResult:
        tables = []
        chars_by_page = {}
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                chars_by_page[page_num] = page.chars
                for i, table in enumerate(page.extract_tables() or []):
                    if table:
                        df = pd.DataFrame(table[1:], columns=table[0])
                        tables.append(PlumberTable(page_num, i, df))
        return PlumberResult(tables=tables, chars_by_page=chars_by_page)
```

---

### Task 5: 置信度评分模块（核心）

**Files:**
- Create: `backend/pipeline/confidence.py`
- Create: `tests/pipeline/test_confidence.py`

**Step 1: 写失败测试**

```python
def test_high_confidence_simple_table():
    from backend.pipeline.confidence import score_page, ConfidenceReport
    report = score_page(docling_table, plumber_table, page_profile)
    assert isinstance(report, ConfidenceReport)
    assert 0 <= report.score <= 1.0

def test_low_confidence_triggers_qwen():
    report = score_page(messy_docling, messy_plumber, scanned_profile)
    assert report.needs_qwen is True
    assert report.score < 0.85

def test_cross_engine_disagreement_triggers_qwen():
    report = score_page(docling_df, different_plumber_df, text_profile)
    assert report.needs_qwen is True
```

**Step 2: 实现 confidence.py**

```python
from dataclasses import dataclass
import pandas as pd
import numpy as np
from backend.config import settings

@dataclass
class ConfidenceReport:
    score: float
    needs_qwen: bool
    reasons: list[str]
    breakdown: dict[str, float]

def score_page(
    docling_tables: list,
    plumber_tables: list,
    page_profile,
) -> ConfidenceReport:
    reasons = []
    scores = {}

    # 1. 表格结构分
    scores["table_structure"] = _table_structure_score(docling_tables)

    # 2. 双引擎一致率
    scores["cross_engine"] = _cross_engine_agreement(docling_tables, plumber_tables)
    if scores["cross_engine"] < 0.8:
        reasons.append("双引擎结果不一致")

    # 3. 数值一致性（合计行）
    scores["numeric"] = _numeric_consistency(docling_tables)
    if scores["numeric"] < 0.7:
        reasons.append("合计行校验失败")

    # 4. OCR 质量
    scores["ocr"] = 1.0 if page_profile.page_type.value != "scanned" else 0.6

    # 5. 版面连贯性
    scores["layout"] = 0.9 if page_profile.char_count > 50 else 0.5

    weights = {
        "table_structure": 0.25,
        "cross_engine": 0.25,
        "numeric": 0.20,
        "ocr": 0.15,
        "layout": 0.15,
    }
    total = sum(scores[k] * weights[k] for k in weights)

    needs_qwen = (
        total < settings.confidence_threshold
        or scores["cross_engine"] < 0.8
        or any(t.has_merged_cells and scores["table_structure"] < 0.7
               for t in docling_tables)
    )

    return ConfidenceReport(
        score=round(total, 3),
        needs_qwen=needs_qwen,
        reasons=reasons,
        breakdown=scores,
    )

def _cross_engine_agreement(docling_tables, plumber_tables) -> float:
    if not docling_tables or not plumber_tables:
        return 0.5
    # 比对同页表格的单元格文本一致率
    matches, total = 0, 0
    for dt in docling_tables:
        for pt in plumber_tables:
            if dt.page_num != pt.page_num:
                continue
            d_vals = dt.dataframe.astype(str).values.flatten()
            p_vals = pt.dataframe.astype(str).values.flatten()
            min_len = min(len(d_vals), len(p_vals))
            if min_len == 0:
                continue
            for i in range(min_len):
                total += 1
                if _normalize(d_vals[i]) == _normalize(p_vals[i]):
                    matches += 1
    return matches / total if total > 0 else 0.5

def _normalize(val: str) -> str:
    return val.strip().replace(",", "").replace(" ", "")

def _table_structure_score(tables) -> float:
    if not tables:
        return 1.0
    scores = []
    for t in tables:
        df = t.dataframe
        empty_ratio = df.isnull().sum().sum() / df.size
        scores.append(1.0 - min(empty_ratio * 2, 0.5))
    return np.mean(scores)

def _numeric_consistency(tables) -> float:
    # 检测最后一行是否为合计行，验证列之和
    if not tables:
        return 1.0
    for t in tables:
        df = t.dataframe
        if len(df) < 2:
            continue
        last_row = df.iloc[-1].astype(str)
        if any(kw in str(last_row.iloc[0]) for kw in ("合计", "总计", "Total", "Sum")):
            for col_idx in range(1, len(df.columns)):
                try:
                    col_vals = pd.to_numeric(df.iloc[:-1, col_idx], errors="coerce")
                    last_val = pd.to_numeric(df.iloc[-1, col_idx], errors="coerce")
                    if col_vals.notna().sum() > 0 and last_val is not None:
                        if abs(col_vals.sum() - last_val) > 0.01:
                            return 0.3
                except (ValueError, TypeError):
                    pass
    return 1.0
```

**Step 3: 运行测试**

```bash
pytest tests/pipeline/test_confidence.py -v
```
Expected: PASS

---

## Phase 2: Qwen 兜底 + 融合导出

### Task 6: Qwen 按需调用模块

**Files:**
- Create: `backend/pipeline/qwen_fallback.py`
- Create: `tests/pipeline/test_qwen_fallback.py`

**Step 1: 实现（仅低置信度页面调用）**

```python
import base64
import fitz
import dashscope
from dashscope import MultiModalConversation
from backend.config import settings

class QwenFallback:
    def __init__(self):
        dashscope.api_key = settings.dashscope_api_key

    def extract_table(self, pdf_path: str, page_num: int) -> str:
        """仅对单页调用，返回 HTML 表格"""
        img_b64 = self._page_to_base64(pdf_path, page_num)
        response = MultiModalConversation.call(
            model=settings.qwen_model,
            messages=[{
                "role": "user",
                "content": [
                    {"image": f"data:image/png;base64,{img_b64}"},
                    {"text": "Extract all tables from this page. "
                             "Return as HTML table with data-bbox attributes. "
                             "Preserve merged cells."},
                ],
            }],
        )
        return response.output.choices[0].message.content[0]["text"]

    def _page_to_base64(self, pdf_path: str, page_num: int) -> str:
        doc = fitz.open(pdf_path)
        pix = doc[page_num].get_pixmap(dpi=200)
        doc.close()
        return base64.b64encode(pix.tobytes("png")).decode()

    @staticmethod
    def html_to_dataframe(html: str) -> "pd.DataFrame":
        from bs4 import BeautifulSoup
        import pandas as pd
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return pd.DataFrame()
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            rows.append(cells)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows[1:], columns=rows[0])
```

**Step 2: 测试（mock API）**

```python
from unittest.mock import patch

@patch("backend.pipeline.qwen_fallback.MultiModalConversation.call")
def test_only_called_on_low_confidence(mock_call):
    mock_call.return_value = mock_response_with_html_table()
    # 验证 needs_qwen=True 时才调用
    ...
```

---

### Task 7: 结果融合器

**Files:**
- Create: `backend/pipeline/merger.py`

```python
def merge_results(docling_result, plumber_result, qwen_results: dict, confidence_reports: dict):
    """按页融合：优先本地高置信度，低置信度用 Qwen 覆盖"""
    final_tables = []
    for page_num, report in confidence_reports.items():
        if report.needs_qwen and page_num in qwen_results:
            final_tables.append({
                "source": "qwen",
                "page_num": page_num,
                "dataframe": qwen_results[page_num],
                "confidence": report.score,
            })
        else:
            # 取 Docling 结果，用 pdfplumber 校验过的单元格
            for t in docling_result.tables:
                if t.page_num == page_num:
                    final_tables.append({
                        "source": "docling",
                        "page_num": page_num,
                        "dataframe": t.dataframe,
                        "confidence": report.score,
                    })
    return final_tables
```

---

### Task 8: Excel 导出器

**Files:**
- Create: `backend/pipeline/exporter.py`
- Create: `tests/pipeline/test_exporter.py`

```python
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font
import pandas as pd

YELLOW = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

class ExcelExporter:
    def export(self, tables: list, metadata: dict, output_path: str, low_confidence_cells: dict):
        wb = Workbook()
        wb.remove(wb.active)

        # 元数据 Sheet
        meta_ws = wb.create_sheet("_metadata")
        for i, (k, v) in enumerate(metadata.items(), 1):
            meta_ws.cell(row=i, column=1, value=k)
            meta_ws.cell(row=i, column=2, value=str(v))

        for idx, table in enumerate(tables):
            ws = wb.create_sheet(f"table_{idx + 1}")
            df = table["dataframe"]
            for r_idx, row in enumerate(df.itertuples(), 2):
                for c_idx, val in enumerate(row[1:], 1):
                    cell = ws.cell(row=r_idx, column=c_idx, value=val)
                    key = (table["page_num"], r_idx - 2, c_idx - 1)
                    if key in low_confidence_cells:
                        cell.fill = YELLOW
                        cell.comment = low_confidence_cells[key]

            if table["confidence"] < 0.85:
                ws.cell(row=1, column=1, value=f"⚠ 置信度: {table['confidence']}")

        wb.save(output_path)
        return output_path
```

---

### Task 9: 主流水线编排

**Files:**
- Create: `backend/pipeline/orchestrator.py`

```python
class PipelineOrchestrator:
    def __init__(self):
        self.classifier = ...
        self.docling = DoclingEngine()
        self.plumber = PlumberEngine()
        self.qwen = QwenFallback()
        self.exporter = ExcelExporter()

    def process(self, pdf_path: str) -> dict:
        docling_result = self.docling.extract(pdf_path)
        plumber_result = self.plumber.extract(pdf_path)

        qwen_calls = 0
        qwen_results = {}
        confidence_reports = {}

        pages = set(t.page_num for t in docling_result.tables)
        for page_num in pages:
            profile = classify_page(pdf_path, page_num)
            d_tables = [t for t in docling_result.tables if t.page_num == page_num]
            p_tables = [t for t in plumber_result.tables if t.page_num == page_num]
            report = score_page(d_tables, p_tables, profile)
            confidence_reports[page_num] = report

            if report.needs_qwen:
                html = self.qwen.extract_table(pdf_path, page_num)
                qwen_results[page_num] = QwenFallback.html_to_dataframe(html)
                qwen_calls += 1

        final = merge_results(docling_result, plumber_result, qwen_results, confidence_reports)
        output = self.exporter.export(final, metadata={
            "qwen_api_calls": qwen_calls,
            "total_pages": len(pages),
            "qwen_call_rate": f"{qwen_calls}/{len(pages)}",
        }, ...)

        return {"output_path": output, "qwen_calls": qwen_calls, "confidence_reports": confidence_reports}
```

---

## Phase 3: API + Web UI

### Task 10: FastAPI 后端

**Files:**
- Create: `backend/api/main.py`
- Create: `backend/api/routes/upload.py`
- Create: `backend/api/routes/jobs.py`
- Create: `backend/tasks/process_pdf.py`

端点：
- `POST /api/upload` — 上传 PDF，返回 job_id
- `GET /api/jobs/{id}` — 查询状态和置信度报告
- `GET /api/jobs/{id}/preview` — 预览解析结果
- `GET /api/jobs/{id}/download` — 下载 Excel

### Task 11: React 前端

**Files:**
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/pages/Upload.tsx`
- Create: `frontend/src/pages/Preview.tsx`

功能：拖拽上传、进度条、左右对照预览、低置信度标红、下载 Excel。

### Task 12: Docker Compose 部署

**Files:**
- Modify: `docker-compose.yml`

服务：backend (FastAPI), worker (Celery), redis, frontend (nginx)。

---

## 验证清单

```bash
# 单元测试
pytest tests/ -v

# 端到端（本地引擎 only，无 API）
CONFIDENCE_THRESHOLD=1.0 python -m backend.pipeline.orchestrator tests/fixtures/sample_report.pdf

# 端到端（含 Qwen 兜底）
DASHSCOPE_API_KEY=sk-xxx python -m backend.pipeline.orchestrator tests/fixtures/complex_report.pdf

# API 调用率统计
# 预期：文本型报表 < 15%，复杂表格 < 50%
```
