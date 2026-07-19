"""DeepSeek API fallback for high-confidence table extraction.

DeepSeek-V3 has strong vision capabilities (via its multimodal endpoint).
When enabled, it processes pages where pdfplumber/Docling had low confidence
and provides a second pass to improve extraction accuracy.

API docs: https://platform.deepseek.com/api-docs
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time

import fitz
import pandas as pd
import requests

from backend.config import settings
from backend.pipeline.table_refiner import refine_dataframe

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

_TABLE_PROMPT = """You are a precise financial table extraction engine. Extract all tables from this page image.

Output JSON format: {"tables": [{"headers": ["col1", "col2", ...], "rows": [["cell", "cell", ...], ...]}]}

Rules:
1. Preserve ALL numbers exactly as they appear (including commas, decimals, currency symbols, parentheses for negatives)
2. Do NOT summarize, round, or modify any values
3. Extract all rows including totals/subtotals
4. If a header cell is empty, use empty string ""
5. If no tables are found on this page, return {"tables": []}
6. Return ONLY valid JSON, no markdown, no explanation before or after"""


class DeepSeekFallback:
    def __init__(self) -> None:
        self._api_key = settings.deepseek_api_key
        self._model = "deepseek-chat"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def extract_tables(self, pdf_path: str, page_num: int, fitz_doc=None) -> list[pd.DataFrame]:
        """Extract tables from a single page using DeepSeek. Returns list of DataFrames."""
        if not self.is_available:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured.")

        img_b64 = self._page_to_base64(pdf_path, page_num, fitz_doc=fitz_doc)
        if not img_b64:
            logger.warning("DeepSeek: failed to render page %d", page_num)
            return []

        start = time.perf_counter()
        response_text = self._call_api(img_b64)
        elapsed = time.perf_counter() - start
        logger.info("DeepSeek page %d extracted in %.1fs", page_num + 1, elapsed)

        tables = self._parse_response(response_text)
        return [refine_dataframe(t) for t in tables if t is not None and not t.empty]

    def _page_to_base64(self, pdf_path: str, page_num: int, fitz_doc=None) -> str:
        close_doc = False
        doc = fitz_doc
        if doc is None:
            doc = fitz.open(pdf_path)
            close_doc = True

        try:
            page = doc[page_num]
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            return base64.b64encode(img_bytes).decode("utf-8")
        except Exception as exc:
            logger.error("DeepSeek: failed to render page %d: %s", page_num + 1, exc)
            return ""
        finally:
            if close_doc:
                doc.close()

    def _call_api(self, img_b64: str) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": _TABLE_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{img_b64}",
                                "detail": "high",
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extract all tables from this page as JSON.",
                        },
                    ],
                },
            ],
            "temperature": 0.0,
            "max_tokens": 4096,
            "stream": False,
        }

        resp = requests.post(_DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content.strip()

    def _parse_response(self, text: str) -> list[pd.DataFrame]:
        text = text.strip()
        # Find JSON block if wrapped in markdown
        json_match = re.search(r"\{[\s\S]*\}", text)
        if not json_match:
            logger.warning("DeepSeek: no JSON found in response")
            return []

        try:
            data = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            logger.warning("DeepSeek: invalid JSON response: %s", text[:200])
            return []

        tables_raw = data.get("tables", [])
        results = []
        for t in tables_raw:
            headers = t.get("headers", [])
            rows = t.get("rows", [])
            if not headers or not rows or len(headers) < 2 or len(rows) < 1:
                continue
            # Normalize: ensure all rows have same column count
            max_cols = max(len(headers), max((len(r) for r in rows), default=0))
            headers = headers + [""] * (max_cols - len(headers))
            norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]
            df = pd.DataFrame(norm_rows, columns=headers)
            results.append(df)

        return results
