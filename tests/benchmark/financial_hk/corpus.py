"""港股 benchmark 语料定义。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, TypedDict

from backend.markets.hk.constants import us_cross_list_ticker

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_DIR = Path(__file__).resolve().parent


class HkCorpusEntry(TypedDict, total=False):
    id: str
    name: str
    pdf: str
    urls: List[str]
    sec_ticker: str  # 交叉上市 SEC ticker，用于 20-F / ARS 回退
    tier: str  # A=HKEX 全文年报 | B=SEC 20-F 副本 | C=仅 PDF 无 US XBRL


def _p(rel: str) -> str:
    return str(ROOT / rel)


def _dest(code: str) -> str:
    return _p(f"tests/benchmark/financial_hk/{code}_annual.pdf")


def _cross(code: str) -> str:
    return us_cross_list_ticker(code) or ""


CORPUS_HK: List[HkCorpusEntry] = [
    {
        "id": "0700",
        "name": "Tencent",
        "pdf": _dest("0700"),
        "urls": [
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0408/2024040801822.pdf",
        ],
        "sec_ticker": _cross("0700"),
        "tier": "A",
    },
    {
        "id": "9988",
        "name": "Alibaba",
        "pdf": _dest("9988"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2024/0523/2024052301569.pdf",
        ],
        "sec_ticker": "BABA",
        "tier": "A",
    },
    {
        "id": "3690",
        "name": "Meituan",
        "pdf": _dest("3690"),
        "urls": [
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0428/2025042800235.pdf",
        ],
        "sec_ticker": _cross("3690"),
        "tier": "A",
    },
    {
        "id": "9618",
        "name": "JD.com",
        "pdf": _dest("9618"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0417/2025041701385.pdf",
        ],
        "sec_ticker": "JD",
        "tier": "A",
    },
    {
        "id": "1810",
        "name": "Xiaomi",
        "pdf": _dest("1810"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0424/2025042401119.pdf",
        ],
        "sec_ticker": _cross("1810"),
        "tier": "A",
    },
    {
        "id": "9888",
        "name": "Baidu",
        "pdf": _dest("9888"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0328/2025032802704.pdf",
        ],
        "sec_ticker": "BIDU",
        "tier": "A",
    },
    {
        "id": "1024",
        "name": "Kuaishou",
        "pdf": _dest("1024"),
        "urls": [
            "https://ir.kuaishou.com/system/files-encrypted/nasdaq_kms/assets/2025/04/25/19-18-32/Annual%20report%202024_CN.pdf",
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0325/2025032500309.pdf",
        ],
        "sec_ticker": _cross("1024"),
        "tier": "A",
    },
    {
        "id": "1299",
        "name": "AIA",
        "pdf": _dest("1299"),
        "urls": [
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0408/2025040800585.pdf",
        ],
        "sec_ticker": _cross("1299"),
        "tier": "A",
    },
    {
        "id": "0941",
        "name": "China Mobile",
        "pdf": _dest("0941"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0411/2025041100488.pdf",
        ],
        "sec_ticker": _cross("0941"),
        "tier": "A",
    },
    {
        "id": "0005",
        "name": "HSBC",
        "pdf": _dest("0005"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0219/2025021900181.pdf",
        ],
        "sec_ticker": _cross("0005"),
        "tier": "A",
    },
    # --- 扩样本：交叉上市 + 纯港股 ---
    {
        "id": "9999",
        "name": "NetEase",
        "pdf": _dest("9999"),
        "urls": [
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0415/2025041501189.pdf",
        ],
        "sec_ticker": _cross("9999"),
        "tier": "A",
    },
    {
        "id": "2015",
        "name": "Li Auto",
        "pdf": _dest("2015"),
        "urls": [
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0410/2025041000477.pdf",
        ],
        "sec_ticker": _cross("2015"),
        "tier": "A",
    },
    {
        "id": "9868",
        "name": "XPeng",
        "pdf": _dest("9868"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0416/2025041600064.pdf",
        ],
        "sec_ticker": _cross("9868"),
        "tier": "A",
    },
    {
        "id": "9866",
        "name": "NIO",
        "pdf": _dest("9866"),
        "urls": [
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0409/2025040900011.pdf",
        ],
        "sec_ticker": _cross("9866"),
        "tier": "A",
    },
    {
        "id": "2318",
        "name": "Ping An",
        "pdf": _dest("2318"),
        "urls": [
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0319/2025031900856.pdf",
        ],
        "sec_ticker": "",
        "tier": "A",
    },
    {
        "id": "2628",
        "name": "China Life",
        "pdf": _dest("2628"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0326/2025032600799.pdf",
        ],
        "sec_ticker": "",
        "tier": "A",
    },
    {
        "id": "0992",
        "name": "Lenovo",
        "pdf": _dest("0992"),
        "urls": [
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0619/2024061900373.pdf",
        ],
        "sec_ticker": "",
        "tier": "A",
    },
    {
        "id": "0883",
        "name": "CNOOC",
        "pdf": _dest("0883"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0408/2025040800613.pdf",
        ],
        "sec_ticker": "",
        "tier": "A",
    },
    {
        "id": "0939",
        "name": "CCB",
        "pdf": _dest("0939"),
        "urls": [
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0425/2025042501077.pdf",
            "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0328/2025032801481_c.pdf",
        ],
        "sec_ticker": "",
        "tier": "A",
    },
    {
        "id": "1211",
        "name": "BYD",
        "pdf": _dest("1211"),
        "urls": [
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0324/2025032401238.pdf",
        ],
        "sec_ticker": "",
        "tier": "A",
    },
]


def corpus_path(entry: HkCorpusEntry) -> Path:
    return Path(entry["pdf"])


def available_entries() -> List[HkCorpusEntry]:
    return [e for e in CORPUS_HK if corpus_path(e).exists()]


def missing_entries() -> List[HkCorpusEntry]:
    return [e for e in CORPUS_HK if not corpus_path(e).exists()]
