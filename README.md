# PDF Intelligence

高精度 PDF 解析系统：本地 Docling + pdfplumber 双引擎，置信度低时按需调用 Qwen2.5-VL，报表导出 Excel。

## 架构

```
PDF → 分类 → Docling + pdfplumber → 置信度评分 → [低] Qwen API → Excel
```

## 快速开始

```bash
cd pdf-intelligence
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install pdfplumber pymupdf pandas openpyxl numpy pydantic-settings pytest beautifulsoup4 dashscope fastapi uvicorn python-multipart httpx
pip install docling   # 较大，首次安装需几分钟

cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY（可选，低置信度页面才调用）

# 启动 API
uvicorn backend.api.main:app --reload --port 8000

# 打开 frontend/index.html 上传 PDF 测试
```

## 运行测试

```bash
# 全部测试（14 项，含准确率基准）
ENABLE_DOCLING=false pytest tests/ -v

# 单独跑准确率基准（要求 ≥ 90%）
python scripts/run_benchmark.py
```

### 基准测试集（8 个用例）

| 用例 | 类型 |
|------|------|
| bordered_financial | 有边框财务报表 |
| borderless_financial | 无边框财务报表 |
| invoice | 发票 |
| budget_borderless | 预算对比表 |
| simple_two_column | 简单两列表格 |
| mixed_layout | 混合排版 |
| multi_page_report_p1/p2 | 多页报表 |

当前整体准确率：**99.5%+**（目标 97%）

## 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `DASHSCOPE_API_KEY` | 千问 API Key | 空（不调用 API） |
| `CONFIDENCE_THRESHOLD` | 置信度阈值 | 0.85 |
| `QWEN_MODEL` | 模型名称 | qwen-vl-max |

## 项目结构

```
backend/
  api/main.py           # FastAPI 接口
  pipeline/
    classifier.py       # PDF 页面分类
    docling_engine.py   # Docling 提取
    plumber_engine.py   # pdfplumber 提取
    confidence.py       # 置信度评分（门控 Qwen）
    qwen_fallback.py    # Qwen 按需兜底
    merger.py           # 多引擎融合
    exporter.py         # Excel 导出
    orchestrator.py     # 主流水线
frontend/index.html     # Web 上传界面
```
