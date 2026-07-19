# PDF 智能解析系统 — 设计文档

**日期:** 2026-06-14  
**状态:** 已确认

## 目标

构建一个 Web 应用，高精度解析各类 PDF（文本型、扫描件、复杂表格、多栏排版），报表类文档导出为 Excel。速度可慢，**精确率优先**，**API 预算有限**，仅在本地引擎置信度不足时调用 Qwen2.5-VL。

## 已确认约束

| 约束 | 决策 |
|------|------|
| PDF 类型 | 混合，自动识别 |
| 部署 | 混合：Docling + pdfplumber 本地，Qwen 云端 API 兜底 |
| 产品形态 | Web UI（上传 → 预览 → 下载 Excel） |
| 速度 | 可慢，不优先 |
| 精确率 | 最高优先级 |
| API 成本 | 预算不高，必须门控调用 |

## 架构：级联 + 置信度门控

```
PDF 上传
  → 页面级分类（文本层 / 扫描 / 表格密度）
  → 本地双引擎并行（Docling + pdfplumber）
  → 置信度评分（纯代码，零 API 成本）
  → [score ≥ 阈值] 直接输出
  → [score < 阈值] 仅对该页调用 Qwen API
  → 结果融合 + 语义校验
  → Excel 导出（低置信度单元格标黄）
```

### 三层引擎分工

**pdfplumber（本地，快路径校验）**
- 提取文本坐标、简单表格
- 数字/日期正则校验（金额、百分比）
- 与 Docling 交叉比对，不一致则降分

**IBM Docling（本地，主力）**
- 版面分析、阅读顺序、TableFormer 表格重建
- 配置：`TableFormerMode.ACCURATE`，`do_cell_matching=True`
- 扫描件启用 OCR
- 输出 `DoclingDocument` → pandas DataFrame

**Qwen2.5-VL（云端，按需兜底）**
- 仅当页面置信度 < 阈值时触发
- 任务：`table_parsing`（表格 HTML）/ `document_parsing`（复杂版面）
- 解析 QwenVL HTML（`data-bbox`）→ 结构化数据
- 与本地结果融合，取高置信度字段

## 置信度评分（核心，控制 API 成本）

每页独立评分，满分 1.0。**默认阈值 0.85**，可在配置中调整。

```python
page_confidence = weighted_sum([
    (0.25, table_structure_score),   # 行列对齐、无断裂空行
    (0.25, cross_engine_agreement),  # Docling vs pdfplumber 单元格一致率
    (0.20, numeric_consistency),     # 合计行 = 列之和（报表）
    (0.15, ocr_quality_score),       # 扫描件字符置信度
    (0.15, layout_coherence),        # 阅读顺序连贯性
])
```

### 触发 Qwen 的条件（任一满足）

1. `page_confidence < 0.85`
2. Docling 与 pdfplumber 同一单元格数值差异 > 5%
3. 检测到合并单元格但 TableFormer 结构不完整
4. 扫描页 OCR 字符置信度 < 0.7
5. 表格合计行校验失败

### 不触发 Qwen 的条件（节省 API）

1. 纯文本页，无表格，`cross_engine_agreement > 0.95`
2. 简单网格表（无合并单元格），`table_structure_score > 0.9`
3. 用户手动标记「已确认」的页面

### 预期 API 调用率

| PDF 类型 | 预估 Qwen 调用比例 |
|----------|-------------------|
| 文本型标准报表 | 5–15% 页面 |
| 复杂表格（合并单元格） | 30–50% 页面 |
| 扫描件 | 50–70% 页面 |
| 纯文本文档 | 0–5% 页面 |

## 系统组件

```
pdf-intelligence/
├── backend/
│   ├── api/              # FastAPI 路由
│   ├── pipeline/
│   │   ├── classifier.py     # PDF/页面分类
│   │   ├── docling_engine.py
│   │   ├── plumber_engine.py
│   │   ├── confidence.py     # 置信度评分（纯代码）
│   │   ├── qwen_fallback.py  # 按需调用 DashScope
│   │   ├── merger.py         # 多引擎融合
│   │   └── exporter.py       # Excel 导出
│   ├── models/           # Pydantic 数据模型
│   └── tasks/            # Celery 异步任务
├── frontend/             # React Web UI
├── tests/
└── docker-compose.yml
```

## Web UI 功能

| 页面 | 功能 |
|------|------|
| 上传 | 拖拽 PDF，显示预估处理时间和 API 用量 |
| 预览 | 原 PDF 与解析结果左右对照，低置信度区域红色边框 |
| 编辑 | 手动修正低置信度单元格，修正后不再重调 API |
| 导出 | 下载 `.xlsx`，附元数据 Sheet（引擎来源、置信度、是否用过 Qwen） |

## Excel 导出规则

- 每个表格 → 独立 Sheet
- 保留合并单元格（openpyxl `merge_cells`）
- 低置信度单元格黄色背景 + 批注说明原因
- 元数据 Sheet：文件名、页码、置信度、引擎来源、Qwen 调用次数

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React + PDF.js |
| 后端 | FastAPI + Celery + Redis |
| PDF 引擎 | pdfplumber, Docling, PyMuPDF |
| VLM | DashScope `qwen-vl-max` |
| Excel | pandas + openpyxl |
| 存储 | 本地文件 + SQLite |

## 准确率保障

1. 双引擎交叉验证（零 API 成本）
2. 报表语义校验（合计行、日期格式）
3. 分页级 Qwen 兜底（不全文重跑）
4. Qwen 结构化 Prompt + JSON Schema 约束
5. 低置信度单元格人工复核入口

## 目标准确率

| PDF 类型 | 目标准确率 |
|----------|-----------|
| 文本型报表 | 95–98% |
| 复杂表格 | 90–95% |
| 扫描件 | 85–92% |
