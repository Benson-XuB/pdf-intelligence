"""Generate test PDF fixtures programmatically."""

from pathlib import Path

import fitz
import pdfplumber


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def create_text_report_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 80), "2024 Q1 Financial Report", fontsize=16)
    page.insert_text((50, 120), "Revenue breakdown by region", fontsize=12)

    y = 160
    headers = ["Region", "Q1", "Q2", "Q3", "Q4"]
    x_positions = [50, 150, 220, 290, 360]
    for i, h in enumerate(headers):
        page.insert_text((x_positions[i], y), h, fontsize=11)
    y += 25

    rows = [
        ["North", "100", "120", "130", "140"],
        ["South", "80", "90", "95", "100"],
        ["East", "60", "70", "75", "80"],
        ["West", "40", "50", "55", "60"],
        ["合计", "280", "330", "355", "380"],
    ]
    for row in rows:
        for i, cell in enumerate(row):
            page.insert_text((x_positions[i], y), cell, fontsize=11)
        y += 22

    doc.save(path)
    doc.close()


def create_scanned_like_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rect = fitz.Rect(50, 50, 545, 792)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), 1)
    pix.clear_with(220)
    page.insert_image(rect, pixmap=pix)
    doc.save(path)
    doc.close()


def ensure_fixtures() -> dict[str, Path]:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    text_pdf = FIXTURES_DIR / "sample_text.pdf"
    scanned_pdf = FIXTURES_DIR / "sample_scanned.pdf"
    report_pdf = FIXTURES_DIR / "sample_report.pdf"

    for p in (text_pdf, scanned_pdf, report_pdf):
        if p.exists():
            p.unlink()

    create_text_report_pdf(text_pdf)
    create_scanned_like_pdf(scanned_pdf)
    create_text_report_pdf(report_pdf)

    return {
        "sample_text": text_pdf,
        "sample_scanned": scanned_pdf,
        "sample_report": report_pdf,
    }


if __name__ == "__main__":
    paths = ensure_fixtures()
    for name, p in paths.items():
        with pdfplumber.open(p) as pdf:
            print(f"{name}: {len(pdf.pages)} page(s)")
