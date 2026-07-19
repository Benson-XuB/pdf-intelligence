"""生成真实图片型（扫描件）PDF 样本，用于准确率测试。"""

from pathlib import Path

import fitz

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "data" / "samples"

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


def _render_table_image(rows: list[list[str]], title: str, width: int = 900, height: int = 1100) -> fitz.Pixmap:
    """把表格渲染成图片（模拟扫描件，无文字层）。"""
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_text((50, 60), title, fontsize=18)
    y = 100
    col_x = [50, 200, 300, 400, 500, 600]
    for r_idx, row in enumerate(rows):
        for c_idx, cell in enumerate(row):
            if c_idx < len(col_x):
                weight = 12 if r_idx == 0 or cell == "合计" else 11
                page.insert_text((col_x[c_idx], y), cell, fontsize=weight)
        y += 32
    pix = page.get_pixmap(dpi=200)
    doc.close()
    return pix


def create_image_only_pdf(path: Path, rows: list[list[str]], title: str) -> None:
    """生成纯图片页 PDF（无文字层）。"""
    pix = _render_table_image(rows, title)
    doc = fitz.open()
    page = doc.new_page(width=pix.width, height=pix.height)
    page.insert_image(page.rect, pixmap=pix)
    doc.save(path, garbage=4, deflate=True)
    doc.close()


def ensure_scanned_samples() -> dict[str, Path]:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "scanned_financial_report.pdf": (FINANCIAL_ROWS, "2024 Q1 Financial Report (Scanned)"),
        "scanned_invoice.pdf": (INVOICE_ROWS, "Invoice #INV-2024-088 (Scanned)"),
    }
    paths = {}
    for name, (rows, title) in files.items():
        p = SAMPLES_DIR / name
        create_image_only_pdf(p, rows, title)
        paths[name] = p
    return paths


if __name__ == "__main__":
    paths = ensure_scanned_samples()
    for name, p in paths.items():
        doc = fitz.open(p)
        page = doc[0]
        text = page.get_text().strip()
        imgs = page.get_images()
        print(f"{name}: pages={len(doc)}, text_len={len(text)}, images={len(imgs)}, size={p.stat().st_size//1024}KB")
        doc.close()
