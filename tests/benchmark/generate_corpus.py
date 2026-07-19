"""生成带标准答案的 PDF 基准测试集。"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

BENCHMARK_DIR = Path(__file__).parent / "corpus"
GROUND_TRUTH_PATH = BENCHMARK_DIR / "ground_truth.json"

FINANCIAL_ROWS = [
    ["Region", "Q1", "Q2", "Q3", "Q4"],
    ["North", "100", "120", "130", "140"],
    ["South", "80", "90", "95", "100"],
    ["East", "60", "70", "75", "80"],
    ["West", "40", "50", "55", "60"],
    ["合计", "280", "330", "355", "380"],
]

INVOICE_ROWS = [
    ["Item", "Qty", "Unit Price", "Amount"],
    ["Widget A", "10", "25.00", "250.00"],
    ["Widget B", "5", "40.00", "200.00"],
    ["Widget C", "8", "15.50", "124.00"],
    ["合计", "23", "", "574.00"],
]

BUDGET_ROWS = [
    ["Department", "Budget", "Actual", "Variance"],
    ["Sales", "500000", "520000", "20000"],
    ["Marketing", "200000", "185000", "-15000"],
    ["R&D", "350000", "360000", "10000"],
    ["合计", "1050000", "1065000", "15000"],
]

SIMPLE_ROWS = [
    ["Name", "Score"],
    ["Alice", "95"],
    ["Bob", "87"],
    ["Carol", "92"],
    ["合计", "274"],
]


def _insert_text(page, point, text, fontsize=11):
    """插入文本，优先使用中文字体。"""
    for fontname in ("china-s", "china-ss", "helv"):
        try:
            page.insert_text(point, text, fontname=fontname, fontsize=fontsize)
            return
        except Exception:
            continue
    page.insert_text(point, text, fontsize=fontsize)


def _draw_bordered_table(page, x0, y0, col_widths, rows, row_height=22):
    x_positions = [x0]
    for w in col_widths:
        x_positions.append(x_positions[-1] + w)
    table_width = sum(col_widths)
    table_height = row_height * len(rows)
    page.draw_rect(fitz.Rect(x0, y0, x0 + table_width, y0 + table_height), width=0.5)
    for i in range(1, len(rows)):
        line_y = y0 + i * row_height
        page.draw_line((x0, line_y), (x0 + table_width, line_y), width=0.5)
    for x in x_positions[1:-1]:
        page.draw_line((x, y0), (x, y0 + table_height), width=0.5)
    for row_idx, row in enumerate(rows):
        cy = y0 + row_idx * row_height + 6
        for col_idx, cell in enumerate(row):
            _insert_text(page, (x_positions[col_idx] + 4, cy), cell, fontsize=10)


def _draw_borderless_table(page, x_positions, y_start, rows, row_height=22):
    y = y_start
    for row in rows:
        for i, cell in enumerate(row):
            _insert_text(page, (x_positions[i], y), cell, fontsize=11)
        y += row_height


def _save_bordered(path, title, col_widths, rows):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), title, fontsize=14)
    _draw_bordered_table(page, 50, 80, col_widths, rows)
    doc.save(path)
    doc.close()


def _save_borderless(path, title, x_positions, rows):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), title, fontsize=14)
    _draw_borderless_table(page, x_positions, 100, rows)
    doc.save(path)
    doc.close()


def create_multi_page_report(path: Path) -> None:
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((50, 50), "Report Page 1", fontsize=14)
    _draw_bordered_table(page1, 50, 80, [90, 60, 60, 60, 60], FINANCIAL_ROWS[:4])
    page2 = doc.new_page()
    page2.insert_text((50, 50), "Report Page 2", fontsize=14)
    _draw_bordered_table(page2, 50, 80, [90, 60, 60, 60, 60], [FINANCIAL_ROWS[0], FINANCIAL_ROWS[4]])
    doc.save(path)
    doc.close()


def ensure_benchmark_corpus() -> dict:
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

    files = {
        "bordered_financial.pdf": lambda: _save_bordered(
            BENCHMARK_DIR / "bordered_financial.pdf",
            "2024 Q1 Financial Report",
            [90, 60, 60, 60, 60],
            FINANCIAL_ROWS,
        ),
        "borderless_financial.pdf": lambda: _save_borderless(
            BENCHMARK_DIR / "borderless_financial.pdf",
            "Borderless Financial Report",
            [50, 150, 220, 290, 360],
            FINANCIAL_ROWS,
        ),
        "invoice.pdf": lambda: _save_bordered(
            BENCHMARK_DIR / "invoice.pdf",
            "Invoice #INV-2024-001",
            [120, 50, 80, 80],
            INVOICE_ROWS,
        ),
        "budget_borderless.pdf": lambda: _save_borderless(
            BENCHMARK_DIR / "budget_borderless.pdf",
            "Annual Budget vs Actual",
            [50, 160, 250, 340, 430],
            BUDGET_ROWS,
        ),
        "simple_two_column.pdf": lambda: _save_bordered(
            BENCHMARK_DIR / "simple_two_column.pdf",
            "Score Sheet",
            [120, 80],
            SIMPLE_ROWS,
        ),
        "mixed_layout.pdf": lambda: _save_borderless(
            BENCHMARK_DIR / "mixed_layout.pdf",
            "Company Annual Summary 2024",
            [50, 150, 220, 290, 360],
            FINANCIAL_ROWS,
        ),
    }

    for p in BENCHMARK_DIR.glob("*.pdf"):
        p.unlink()
    for fn in files:
        files[fn]()
    create_multi_page_report(BENCHMARK_DIR / "multi_page_report.pdf")

    cases = [
        {"name": "bordered_financial", "pdf": "bordered_financial.pdf", "page": 0, "expected_rows": FINANCIAL_ROWS},
        {"name": "borderless_financial", "pdf": "borderless_financial.pdf", "page": 0, "expected_rows": FINANCIAL_ROWS},
        {"name": "invoice", "pdf": "invoice.pdf", "page": 0, "expected_rows": INVOICE_ROWS},
        {"name": "budget_borderless", "pdf": "budget_borderless.pdf", "page": 0, "expected_rows": BUDGET_ROWS},
        {"name": "simple_two_column", "pdf": "simple_two_column.pdf", "page": 0, "expected_rows": SIMPLE_ROWS},
        {"name": "mixed_layout", "pdf": "mixed_layout.pdf", "page": 0, "expected_rows": FINANCIAL_ROWS},
        {"name": "multi_page_report_p1", "pdf": "multi_page_report.pdf", "page": 0, "expected_rows": FINANCIAL_ROWS[:4]},
        {"name": "multi_page_report_p2", "pdf": "multi_page_report.pdf", "page": 1, "expected_rows": [FINANCIAL_ROWS[0], FINANCIAL_ROWS[4]]},
    ]
    for c in cases:
        c["min_accuracy"] = 0.9

    ground_truth = {"cases": cases, "target_overall_accuracy": 0.9}
    GROUND_TRUTH_PATH.write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2))
    return ground_truth
