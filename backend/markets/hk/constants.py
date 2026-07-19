"""港股代码与美国交叉上市映射（用于 PDF vs US XBRL 校验）。"""

from __future__ import annotations

from typing import Dict, Optional

# HK 代码 -> US ticker
HK_US_CROSS_LIST: Dict[str, str] = {
    "0700": "TCEHY",
    "9988": "BABA",
    "3690": "MPNGY",
    "9618": "JD",
    "9888": "BIDU",
    "1024": "KUASF",
    "1810": "XIACY",
    "1299": "AIA",
    "0941": "CHL",
    "0005": "HSBC",
    "9999": "NTES",
    "2015": "LI",
    "9868": "XPEV",
    "9866": "NIO",
}

HK_FILENAME_HINTS: Dict[str, list[str]] = {
    "0700": ["tencent", "0700"],
    "9988": ["alibaba", "9988", "baba"],
    "3690": ["meituan", "3690"],
    "9618": ["jd", "9618", "jingdong"],
    "9888": ["baidu", "9888"],
    "1024": ["kuaishou", "1024"],
    "1810": ["xiaomi", "1810"],
    "1299": ["aia", "1299"],
    "0941": ["china mobile", "0941", "cmcc"],
    "0005": ["hsbc", "0005"],
    "9999": ["netease", "9999", "ntes"],
    "2015": ["li auto", "2015", "lixiang"],
    "9868": ["xpeng", "9868", "xiaopeng"],
    "9866": ["nio", "9866"],
    "2318": ["ping an", "2318"],
    "2628": ["china life", "2628"],
    "0992": ["lenovo", "0992"],
    "0883": ["cnooc", "0883"],
    "0939": ["ccb", "0939", "construction bank"],
    "1211": ["byd", "1211"],
}


def normalize_hk_code(ticker: str) -> str:
    raw = ticker.upper().strip().replace(".HK", "")
    if raw.isdigit():
        return raw.zfill(4)
    return raw


def us_cross_list_ticker(hk_ticker: str) -> Optional[str]:
    code = normalize_hk_code(hk_ticker)
    return HK_US_CROSS_LIST.get(code)
