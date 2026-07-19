"""financial_10k 基准语料：20 家美股 10-K（PDF/HTML）。"""

from __future__ import annotations

from pathlib import Path
from typing import List, TypedDict

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_DIR = Path(__file__).resolve().parent


class CorpusEntry(TypedDict):
    id: str
    name: str
    pdf: str


def _p(rel: str) -> str:
    return str(ROOT / rel)


# 已有 5 家保留原路径；新增 15 家统一放 financial_10k/
CORPUS_20: List[CorpusEntry] = [
    {"id": "AAPL", "name": "Apple", "pdf": _p("data/samples/apple_2024_annual_report_10k.pdf")},
    {"id": "MSFT", "name": "Microsoft", "pdf": _p("tests/benchmark/financial_10k/msft_2024_10k.pdf")},
    {"id": "GOOGL", "name": "Alphabet", "pdf": _p("tests/benchmark/financial_10k/googl_2024_10k.pdf")},
    {"id": "AMZN", "name": "Amazon", "pdf": _p("tests/benchmark/financial_10k/amzn_2024_10k.pdf")},
    {"id": "META", "name": "Meta", "pdf": _p("tests/benchmark/financial_10k/meta_2024_10k.pdf")},
    {"id": "NVDA", "name": "NVIDIA", "pdf": _p("tests/benchmark/financial_10k/nvda_10k.htm")},
    {"id": "TSLA", "name": "Tesla", "pdf": _p("tests/benchmark/financial_10k/tsla_10k.htm")},
    {"id": "JPM", "name": "JPMorgan", "pdf": _p("tests/benchmark/financial_10k/jpm_10k.htm")},
    {"id": "V", "name": "Visa", "pdf": _p("tests/benchmark/financial_10k/v_10k.htm")},
    {"id": "UNH", "name": "UnitedHealth", "pdf": _p("tests/benchmark/financial_10k/unh_10k.htm")},
    {"id": "JNJ", "name": "Johnson & Johnson", "pdf": _p("tests/benchmark/financial_10k/jnj_10k.htm")},
    {"id": "WMT", "name": "Walmart", "pdf": _p("tests/benchmark/financial_10k/wmt_10k.htm")},
    {"id": "MA", "name": "Mastercard", "pdf": _p("tests/benchmark/financial_10k/ma_10k.htm")},
    {"id": "HD", "name": "Home Depot", "pdf": _p("tests/benchmark/financial_10k/hd_10k.htm")},
    {"id": "LLY", "name": "Eli Lilly", "pdf": _p("tests/benchmark/financial_10k/lly_10k.htm")},
    {"id": "AVGO", "name": "Broadcom", "pdf": _p("tests/benchmark/financial_10k/avgo_10k.htm")},
    {"id": "AMD", "name": "AMD", "pdf": _p("tests/benchmark/financial_10k/amd_10k.htm")},
    {"id": "CRM", "name": "Salesforce", "pdf": _p("tests/benchmark/financial_10k/crm_10k.htm")},
    {"id": "NFLX", "name": "Netflix", "pdf": _p("tests/benchmark/financial_10k/nflx_10k.htm")},
    {"id": "INTC", "name": "Intel", "pdf": _p("tests/benchmark/financial_10k/intc_10k.htm")},
]


def corpus_path(entry: CorpusEntry) -> Path:
    return Path(entry["pdf"])


def available_entries() -> List[CorpusEntry]:
    return [e for e in CORPUS_20 if corpus_path(e).exists()]


def missing_entries() -> List[CorpusEntry]:
    return [e for e in CORPUS_20 if not corpus_path(e).exists()]
