import os

import pytest

# 基准测试聚焦提取准确率；Docling 模型下载不稳定时由 pdfplumber 兜底
os.environ.setdefault("ENABLE_DOCLING", "false")
