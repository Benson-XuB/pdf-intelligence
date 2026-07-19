import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import fitz
import pdfplumber

from backend.config import settings
from backend.pipeline.classifier import classify_page
from backend.pipeline.confidence import ConfidenceReport, score_page
from backend.pipeline.exporter import ExcelExporter
from backend.pipeline.merger import merge_results
from backend.pipeline.models import FinalTable
from backend.pipeline.models import DoclingResult, PlumberResult
from backend.pipeline.plumber_engine import PlumberEngine
from backend.pipeline.qwen_fallback import QwenFallback
from backend.pipeline.deepseek_fallback import DeepSeekFallback
from backend.pipeline.financial_table_refiner import refine_financial_dataframe
from backend.pipeline.table_refiner import refine_dataframe

logger = logging.getLogger(__name__)

# 并行线程数：笔记本场景降为 cpu_count//2，保散热
_CPU_COUNT = (__import__("os").cpu_count() or 4)
_MAX_PARALLEL_PAGES = max(2, _CPU_COUNT // 2)


@dataclass
class PipelineResult:
    output_path: Optional[str]
    qwen_calls: int
    deepseek_calls: int
    total_pages: int
    confidence_reports: Dict[int, ConfidenceReport] = field(default_factory=dict)
    tables: List[FinalTable] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class PipelineOrchestrator:
    def __init__(self) -> None:
        self.plumber = PlumberEngine()
        self.qwen = QwenFallback()
        self.deepseek = DeepSeekFallback()
        self.exporter = ExcelExporter()
        self._docling = None
        self._docling_use_vlm = None
        self._docling_fast_mode = None

    def _get_docling(self, use_vlm: Optional[bool] = None, fast_mode: Optional[bool] = None):
        vlm = use_vlm if use_vlm is not None else settings.docling_use_vlm
        fast = fast_mode if fast_mode is not None else settings.docling_fast_mode
        if self._docling is not None and (self._docling_use_vlm != vlm or self._docling_fast_mode != fast):
            self._docling = None
        if self._docling is None:
            from backend.pipeline.docling_engine import DoclingEngine

            self._docling = DoclingEngine(use_vlm=vlm, fast_mode=fast)
            self._docling_use_vlm = vlm
            self._docling_fast_mode = fast
        return self._docling

    def process(
        self,
        pdf_path: str,
        output_path: Optional[str] = None,
        progress_callback=None,
        enable_docling: Optional[bool] = None,
        fast_mode: Optional[bool] = None,
        use_vlm: Optional[bool] = None,
        use_deepseek: Optional[bool] = None,
        confidence_threshold: Optional[float] = None,
    ) -> PipelineResult:
        pdf_path = str(pdf_path)
        errors: list[str] = []

        use_docling = enable_docling if enable_docling is not None else settings.enable_docling
        re_fast = fast_mode if fast_mode is not None else settings.docling_fast_mode
        re_vlm = use_vlm if use_vlm is not None else settings.docling_use_vlm
        re_threshold = confidence_threshold if confidence_threshold is not None else settings.confidence_threshold
        re_deepseek = use_deepseek if use_deepseek is not None else False

        # 顶层打开 fitz 和 pdfplumber，整个方法复用，消除 per-page 文件 I/O
        fitz_doc = fitz.open(pdf_path)
        plumber_pdf = pdfplumber.open(pdf_path)
        total_pages = len(fitz_doc)

        try:
            # === 阶段零：Docling 与 pdfplumber 并行提取 ===
            if progress_callback:
                progress_callback("extracting", 0, total_pages)
            with ThreadPoolExecutor(max_workers=2) as ext_exec:
                plumber_future = ext_exec.submit(self.plumber.extract, pdf_path, plumber_pdf=plumber_pdf)
                docling_future = ext_exec.submit(
                    self._get_docling(use_vlm=re_vlm, fast_mode=re_fast).extract, pdf_path
                ) if use_docling else None

                plumber_result = plumber_future.result()
                docling_result = DoclingResult()
                if docling_future is not None:
                    try:
                        docling_result = docling_future.result()
                    except Exception as exc:
                        logger.warning("Docling 提取失败，降级为 pdfplumber: %s", exc)
                        errors.append(f"Docling failed: {exc}")

            pages = set(range(total_pages))
            for t in docling_result.tables:
                if 0 <= t.page_num < total_pages:
                    pages.add(t.page_num)
            for t in plumber_result.tables:
                if 0 <= t.page_num < total_pages:
                    pages.add(t.page_num)
            sorted_pages = sorted(pages)

            # 预计算 per-page 的引擎结果索引（避免每次过滤全集）
            docling_by_page: dict[int, list] = {}
            for t in docling_result.tables:
                if 0 <= t.page_num < total_pages:
                    docling_by_page.setdefault(t.page_num, []).append(t)
            plumber_by_page: dict[int, list] = {}
            for t in plumber_result.tables:
                if 0 <= t.page_num < total_pages:
                    plumber_by_page.setdefault(t.page_num, []).append(t)

            # === 阶段一：页分类 + 置信度打分（并行） ===
            confidence_reports: dict[int, ConfidenceReport] = {}
            if progress_callback:
                progress_callback("scoring", 0, len(sorted_pages))

            # 预提取 page 对象并强制触发 pdfplumber 懒加载（避免多线程冲突）
            page_data = []
            for page_num in sorted_pages:
                pp_page = plumber_pdf.pages[page_num]
                fz_page = fitz_doc[page_num]
                # 强制加载 chars 触发 pdfminer 解析
                _ = pp_page.chars
                # 用预计算的引擎结果判定：某页至少有 1 个表格即记为 has_tables
                has_tables = bool(plumber_by_page.get(page_num) or docling_by_page.get(page_num))
                page_data.append((page_num, pp_page, fz_page, has_tables))

            def _score_one_page(page_num: int, pp_page, fz_page, has_tables: bool):
                profile = classify_page(
                    pdf_path, page_num,
                    plumber_page=pp_page, fitz_page=fz_page,
                    has_tables=has_tables,
                )
                d_tables = docling_by_page.get(page_num, [])
                p_tables = plumber_by_page.get(page_num, [])
                report = score_page(d_tables, p_tables, profile, confidence_threshold=re_threshold)
                return page_num, report

            logger.info("阶段一：并行分类+置信度打分 （%d 页，%d 线程）", len(sorted_pages), _MAX_PARALLEL_PAGES)
            with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_PAGES) as executor:
                futures = {
                    executor.submit(_score_one_page, pn, pp, fp, ht): pn
                    for pn, pp, fp, ht in page_data
                }
                for future in as_completed(futures):
                    page_num, report = future.result()
                    confidence_reports[page_num] = report
                    if progress_callback:
                        progress_callback("scoring", len(confidence_reports), len(sorted_pages))

            # === 阶段二：低置信度页面调用 Qwen（并行） ===
            qwen_needed = [p for p, r in confidence_reports.items() if r.needs_qwen]
            qwen_results: dict = {}
            qwen_calls = 0

            if qwen_needed and self.qwen.is_available:
                logger.info("阶段二：并行 Qwen 调用（%d 页）", len(qwen_needed))
                if progress_callback:
                    progress_callback("qwen", 0, len(qwen_needed))

                def _call_qwen(page_num: int):
                    try:
                        html = self.qwen.extract_table(pdf_path, page_num, fitz_doc=fitz_doc)
                        return page_num, html
                    except Exception as exc:
                        return page_num, exc

                with ThreadPoolExecutor(max_workers=min(len(qwen_needed), _MAX_PARALLEL_PAGES)) as executor:
                    qwen_futures = {executor.submit(_call_qwen, p): p for p in qwen_needed}
                    for future in as_completed(qwen_futures):
                        page_num, result = future.result()
                        if isinstance(result, Exception):
                            logger.warning("Qwen 页面 %s 失败: %s", page_num, result)
                            errors.append(f"Qwen page {page_num + 1} failed: {result}")
                        else:
                            qwen_results[page_num] = QwenFallback.html_to_dataframe(result)
                            qwen_calls += 1
                        if progress_callback:
                            progress_callback("qwen", len(qwen_results), len(qwen_needed))
            elif qwen_needed:
                for p in qwen_needed:
                    errors.append(f"Page {p + 1} low confidence but no API key configured")

            # === 阶段三：DeepSeek 高精度兜底（Pro/Enterprise 专属） ===
            deepseek_calls = 0
            if re_deepseek and self.deepseek.is_available:
                deepseek_needed = [p for p, r in confidence_reports.items()
                                   if p not in qwen_results and r.needs_qwen]
                if deepseek_needed:
                    logger.info("阶段三：并行 DeepSeek 调用（%d 页）", len(deepseek_needed))
                    if progress_callback:
                        progress_callback("deepseek", 0, len(deepseek_needed))

                    def _call_deepseek(page_num: int):
                        try:
                            tables = self.deepseek.extract_tables(pdf_path, page_num, fitz_doc=fitz_doc)
                            if tables:
                                return page_num, tables[0]  # return best table
                            return page_num, ValueError("no tables found")
                        except Exception as exc:
                            return page_num, exc

                    with ThreadPoolExecutor(max_workers=min(len(deepseek_needed), _MAX_PARALLEL_PAGES)) as executor:
                        ds_futures = {executor.submit(_call_deepseek, p): p for p in deepseek_needed}
                        for future in as_completed(ds_futures):
                            page_num, result = future.result()
                            if isinstance(result, Exception):
                                logger.warning("DeepSeek page %s failed: %s", page_num, result)
                                errors.append(f"DeepSeek page {page_num + 1} failed: {result}")
                            else:
                                qwen_results[page_num] = result  # store in same dict for merger
                                deepseek_calls += 1
                            if progress_callback:
                                processed = deepseek_calls + len([v for v in qwen_results.values() if v is not None])
                                progress_callback("deepseek", len(qwen_results), len(deepseek_needed))

            final_tables = merge_results(
                docling_result, plumber_result, qwen_results, confidence_reports,
                docling_by_page=docling_by_page, plumber_by_page=plumber_by_page,
            )
            for t in final_tables:
                t.dataframe = refine_dataframe(t.dataframe)
                t.dataframe = refine_financial_dataframe(t.dataframe)

            result = PipelineResult(
                output_path=None,
                qwen_calls=qwen_calls,
                deepseek_calls=deepseek_calls,
                total_pages=total_pages,
                confidence_reports=confidence_reports,
                tables=final_tables,
                errors=errors,
            )

            if not final_tables:
                return result

            if output_path is None:
                stem = Path(pdf_path).stem
                output_path = str(Path("data/outputs") / f"{stem}.xlsx")

            metadata = {
                "source_file": Path(pdf_path).name,
                "total_pages": total_pages,
                "qwen_api_calls": qwen_calls,
                "qwen_call_rate": f"{qwen_calls}/{total_pages}",
                "deepseek_api_calls": deepseek_calls,
                "deepseek_call_rate": f"{deepseek_calls}/{total_pages}",
                "table_count": len(final_tables),
            }
            result.output_path = self.exporter.export(final_tables, metadata, output_path)
            return result

        finally:
            plumber_pdf.close()
            fitz_doc.close()
