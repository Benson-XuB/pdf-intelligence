import hashlib
import logging
from typing import List, Optional

import pandas as pd
import pdfplumber

from backend.pipeline.models import PlumberResult, PlumberTable
from backend.pipeline.table_refiner import refine_dataframe
from backend.pipeline.text_grid_extractor import extract_text_grid_from_page

logger = logging.getLogger(__name__)

def _df_hash(df: pd.DataFrame) -> str:
    """快速计算 DataFrame 的哈希值，用于去重。"""
    h = hashlib.sha256()
    h.update(str(df.shape).encode())
    for col in df.columns:
        h.update(str(col).encode())
    for val in df.values.flatten():
        h.update(str(val).encode())
    return h.hexdigest()


TABLE_SETTINGS = [
    {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "intersection_tolerance": 8,
    },
    {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "snap_tolerance": 12,
        "join_tolerance": 12,
        "edge_min_length": 3,
        "min_words_vertical": 3,
    },
    {
        "vertical_strategy": "lines_strict",
        "horizontal_strategy": "lines_strict",
    },
]


class PlumberEngine:
    def extract(self, pdf_path: str, plumber_pdf=None) -> PlumberResult:
        tables: list[PlumberTable] = []
        chars_by_page: dict[int, list] = {}

        _own_pdf = plumber_pdf is None
        if _own_pdf:
            plumber_pdf = pdfplumber.open(pdf_path)

        try:
            for page_num, page in enumerate(plumber_pdf.pages):
                page_tables = self._extract_page_tables(page)
                for table_index, df in enumerate(page_tables):
                    tables.append(
                        PlumberTable(
                            page_num=page_num,
                            table_index=table_index,
                            dataframe=df,
                        )
                    )
        finally:
            if _own_pdf:
                plumber_pdf.close()

        return PlumberResult(tables=tables)

    def _extract_page_tables(self, page) -> List[pd.DataFrame]:
        found: list[pd.DataFrame] = []
        seen: set[str] = set()

        for settings in TABLE_SETTINGS:
            try:
                raw_tables = page.extract_tables(table_settings=settings) or []
            except Exception:
                continue
            for table in raw_tables:
                df = self._table_to_df(table)
                if df is None:
                    continue
                df = refine_dataframe(df)
                key = _df_hash(df)
                if key not in seen:
                    seen.add(key)
                    found.append(df)

        grid_df = extract_text_grid_from_page(page)
        if grid_df is not None and not grid_df.empty:
            grid_df = refine_dataframe(grid_df)
            key = _df_hash(grid_df)
            if key not in seen:
                seen.add(key)
                found.append(grid_df)

        return found

    @staticmethod
    def _table_to_df(table: list) -> Optional[pd.DataFrame]:
        if not table or len(table) < 2:
            return None
        header = [str(c) if c is not None else "" for c in table[0]]
        rows = [
            [str(c) if c is not None else "" for c in row]
            for row in table[1:]
        ]
        if not any(any(cell for cell in row) for row in rows):
            return None
        return pd.DataFrame(rows, columns=header)
