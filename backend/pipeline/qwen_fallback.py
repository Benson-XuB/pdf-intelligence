import base64
import logging

import fitz
import pandas as pd
from bs4 import BeautifulSoup

from backend.config import settings
from backend.pipeline.table_refiner import refine_dataframe

logger = logging.getLogger(__name__)


class QwenFallback:
    def __init__(self) -> None:
        self._api_key = settings.dashscope_api_key

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def extract_table(self, pdf_path: str, page_num: int, fitz_doc=None) -> str:
        if not self.is_available:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured. Cannot call Qwen API.")

        import dashscope
        from dashscope import MultiModalConversation

        dashscope.api_key = self._api_key
        img_b64 = self._page_to_base64(pdf_path, page_num, fitz_doc=fitz_doc)
        response = MultiModalConversation.call(
            model=settings.qwen_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": f"data:image/png;base64,{img_b64}"},
                        {
                            "text": (
                                "请提取本页所有表格，输出为 HTML <table> 格式。"
                                "要求：1) 保留合并单元格；2) 数字精度不变；"
                                "3) 合计/总计行第一列必须写「合计」；"
                                "4) 表头与数据行列对齐。"
                            ),
                        },
                    ],
                }
            ],
            timeout=60,  # 60 秒超时，避免卡死
        )
        if response.status_code != 200:
            raise RuntimeError(f"Qwen API call failed: {response.message}")
        return response.output.choices[0].message.content[0]["text"]

    def _page_to_base64(self, pdf_path: str, page_num: int, fitz_doc=None) -> str:
        if fitz_doc is not None:
            pix = fitz_doc[page_num].get_pixmap(dpi=200)
        else:
            doc = fitz.open(pdf_path)
            pix = doc[page_num].get_pixmap(dpi=200)
            doc.close()
        return base64.b64encode(pix.tobytes("png")).decode()

    @staticmethod
    def html_to_dataframe(html: str) -> pd.DataFrame:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return pd.DataFrame()
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if not rows:
            return pd.DataFrame()
        if len(rows) == 1:
            return pd.DataFrame([rows[0]])
        max_cols = max(len(r) for r in rows)
        normalized = [r + [""] * (max_cols - len(r)) for r in rows]
        return refine_dataframe(pd.DataFrame(normalized[1:], columns=normalized[0]))
