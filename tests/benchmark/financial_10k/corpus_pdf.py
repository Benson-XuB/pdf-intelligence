"""PDF / SEC 10-K HTML 语料：公司 IR PDF + ARS 附表 + Tier C SEC HTML。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, TypedDict

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_DIR = Path(__file__).resolve().parent

VALID_SUFFIXES = {".pdf", ".htm", ".html"}


class PdfCorpusEntry(TypedDict, total=False):
    id: str
    name: str
    dest: str
    url: Optional[str]
    tier: str  # A=标准10-K PDF | B=ARS/设计型 PDF | C=SEC 10-K HTML | X=营销ARS PDF(无文本层)
    sec_fallback: bool  # 下载失败时尝试 SEC 10-K HTML


def _p(rel: str) -> str:
    return str(ROOT / rel)


def _htm(ticker: str) -> str:
    return _p(f"tests/benchmark/financial_10k/{ticker.lower()}_10k.htm")


CORPUS_PDF: List[PdfCorpusEntry] = [
    {"id": "AAPL", "name": "Apple", "dest": _p("data/samples/apple_2024_annual_report_10k.pdf"), "url": None, "tier": "A"},
    {"id": "MSFT", "name": "Microsoft", "dest": _p("tests/benchmark/financial_10k/msft_2024_10k.pdf"), "url": "https://microsoft.gcs-web.com/static-files/1c864583-06f7-40cc-a94d-d11400c83cc8", "tier": "A"},
    {"id": "GOOGL", "name": "Alphabet", "dest": _p("tests/benchmark/financial_10k/googl_2024_10k.pdf"), "url": "https://s206.q4cdn.com/479360582/files/doc_financials/2024/q4/goog-10-k-2024.pdf", "tier": "A"},
    {"id": "AMZN", "name": "Amazon", "dest": _p("tests/benchmark/financial_10k/amzn_2024_10k.pdf"), "url": "https://s2.q4cdn.com/299287126/files/doc_financials/2025/ar/Amazon-2024-Annual-Report.pdf", "tier": "A"},
    {"id": "META", "name": "Meta", "dest": _p("tests/benchmark/financial_10k/meta_2024_10k.pdf"), "url": "https://s21.q4cdn.com/399680738/files/doc_financials/2024/ar/Meta-12-31-2024-10K-ARS.pdf", "tier": "A"},
    {"id": "NVDA", "name": "NVIDIA", "dest": _p("tests/benchmark/financial_10k/nvda_2024_10k.pdf"), "url": "https://d18rn0p25nwr6d.cloudfront.net/CIK-0001045810/1cbe8fe7-e08a-46e3-8dcc-b429fc06c1a4.pdf", "tier": "A"},
    {"id": "JNJ", "name": "Johnson & Johnson", "dest": _p("tests/benchmark/financial_10k/jnj_2024_10k.pdf"), "url": "https://s203.q4cdn.com/636242992/files/doc_financials/2024/q4/Form-10-K-2024-as-filed-13Feb2025.pdf", "tier": "A"},
    {"id": "WMT", "name": "Walmart", "dest": _p("tests/benchmark/financial_10k/wmt_2024_10k.pdf"), "url": "https://s203.q4cdn.com/254064492/files/doc_financials/2025/q4/2025-Annual-Report-Walmart-Inc.pdf", "tier": "A"},
    {"id": "CRM", "name": "Salesforce", "dest": _htm("CRM"), "url": None, "tier": "C", "sec_fallback": True},
    {"id": "INTC", "name": "Intel", "dest": _p("tests/benchmark/financial_10k/intc_2024_10k.pdf"), "url": "https://www.intc.com/media/intc-corp/documents/intel-2024-annual-report.pdf", "tier": "A"},
    {"id": "AMD", "name": "AMD", "dest": _p("tests/benchmark/financial_10k/amd_2024_10k.pdf"), "url": "https://www.amd.com/content/dam/amd/en/documents/corporate/cr/annual-reports/2024-amd-annual-report.pdf", "tier": "B"},
    {"id": "AVGO", "name": "Broadcom", "dest": _p("tests/benchmark/financial_10k/avgo_2024_10k.pdf"), "url": "https://s203.q4cdn.com/805085098/files/doc_financials/2024/ar/AVGO-2024-Annual-Report.pdf", "tier": "A"},
    {"id": "NFLX", "name": "Netflix", "dest": _p("tests/benchmark/financial_10k/nflx_2024_10k.pdf"), "url": "https://s22.q4cdn.com/959853165/files/doc_financials/2024/ar/2024-Annual-Report.pdf", "tier": "A"},
    {"id": "TSLA", "name": "Tesla", "dest": _htm("TSLA"), "url": None, "tier": "C", "sec_fallback": True},
    {"id": "UNH", "name": "UnitedHealth", "dest": _htm("UNH"), "url": "https://www.unitedhealthgroup.com/content/dam/UHG/PDF/investors/2024/UNH-Annual-Report-2024.pdf", "tier": "B", "sec_fallback": True},
    {"id": "HD", "name": "Home Depot", "dest": _htm("HD"), "url": None, "tier": "C", "sec_fallback": True},
    {"id": "LLY", "name": "Eli Lilly", "dest": _htm("LLY"), "url": "https://www.sec.gov/Archives/edgar/data/59478/000005947825000012/lly-20241231x10k.pdf", "tier": "A", "sec_fallback": True},
    {"id": "V", "name": "Visa", "dest": _p("tests/benchmark/financial_10k/v_2024_10k.pdf"), "url": "https://s1.q4cdn.com/050606653/files/doc_financials/2024/ar/Visa-Inc-Fiscal-2024-Annual-Report.pdf", "tier": "B"},
    {"id": "MA", "name": "Mastercard", "dest": _p("tests/benchmark/financial_10k/ma_2024_10k.pdf"), "url": "https://s202.q4cdn.com/759944473/files/doc_financials/2024/ar/2024-Annual-Report.pdf", "tier": "A"},
    {"id": "JPM", "name": "JPMorgan", "dest": _p("tests/benchmark/financial_10k/jpm_2024_10k.pdf"), "url": "https://www.jpmorganchase.com/content/dam/jpmc/jpmorgan-chase-and-co/investor-relations/documents/annualreport-2024.pdf", "tier": "B"},
]

# 旧营销 ARS PDF（仅对照，不参与 benchmark）
CORPUS_X_ARCHIVE: List[PdfCorpusEntry] = [
    {"id": "CRM", "name": "Salesforce ARS PDF", "dest": _p("tests/benchmark/financial_10k/crm_2024_10k.pdf"), "url": None, "tier": "X"},
    {"id": "TSLA", "name": "Tesla ARS PDF", "dest": _p("tests/benchmark/financial_10k/tsla_2024_10k.pdf"), "url": None, "tier": "X"},
    {"id": "HD", "name": "Home Depot ARS PDF", "dest": _p("tests/benchmark/financial_10k/hd_2024_10k.pdf"), "url": None, "tier": "X"},
]


def dest_path(entry: PdfCorpusEntry) -> Path:
    return Path(entry["dest"])


def available_pdf_entries() -> List[PdfCorpusEntry]:
    return [
        e
        for e in CORPUS_PDF
        if dest_path(e).exists() and dest_path(e).suffix.lower() in VALID_SUFFIXES
    ]


def missing_pdf_entries() -> List[PdfCorpusEntry]:
    return [e for e in CORPUS_PDF if not dest_path(e).exists()]


def entries_for_tier(tier: str) -> List[PdfCorpusEntry]:
    return [e for e in available_pdf_entries() if e.get("tier") == tier]


def as_benchmark_templates(tier: Optional[str] = None) -> List[dict]:
    entries = available_pdf_entries() if tier is None else entries_for_tier(tier)
    return [{"id": e["id"], "name": e["name"], "pdf": e["dest"], "tier": e.get("tier", "A")} for e in entries]
