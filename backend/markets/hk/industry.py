"""港股行业分类与字段跳过（结构级，非 ticker 硬编码规则）。"""

from __future__ import annotations

from typing import Dict, FrozenSet, Optional

from backend.markets.hk.constants import normalize_hk_code

# 行业类型 → 通常不披露的 global schema 字段
INDUSTRY_TYPE_SKIP_FIELDS: Dict[str, FrozenSet[str]] = {
    "insurance": frozenset({"gross_profit", "operating_income", "capex"}),
    "telecom": frozenset({"gross_profit"}),
    "bank": frozenset({"gross_profit", "operating_income", "capex"}),
    "platform": frozenset({"gross_profit"}),
    "energy": frozenset({"gross_profit", "operating_income"}),
    "automotive": frozenset({"gross_profit"}),
}

# HK 代码 → 行业类型（用于 skip + PDF-only 说明）
HK_INDUSTRY_TYPE: Dict[str, str] = {
    "0700": "platform",
    "9988": "platform",
    "3690": "platform",
    "9618": "platform",
    "9888": "platform",
    "1024": "platform",
    "1810": "platform",
    "1299": "insurance",
    "0941": "telecom",
    "0005": "bank",
    "9999": "platform",
    "2015": "platform",
    "9868": "platform",
    "9866": "platform",
    "2318": "insurance",
    "2628": "insurance",
    "0939": "bank",
    "0883": "energy",
    "1211": "automotive",
}

# 交叉上市：SEC company_tickers 未收录的 OTC / 退市代码 → 仍可用 SEC facts 的主 ticker
SEC_TICKER_ALIASES: Dict[str, str] = {
    "TCEHY": "TCEHY",  # 占位；无 SEC facts 时走 PDF-only
    "MPNGY": "MPNGY",
    "XIACY": "XIACY",
    "KUASF": "KUASF",
    "AIA": "AIA",
    "CHL": "CHL",
}


def industry_type(hk_code: str) -> Optional[str]:
    return HK_INDUSTRY_TYPE.get(normalize_hk_code(hk_code))


def industry_skipped_fields(hk_code: str) -> FrozenSet[str]:
    itype = industry_type(hk_code)
    if not itype:
        return frozenset()
    return INDUSTRY_TYPE_SKIP_FIELDS.get(itype, frozenset())


def resolve_sec_ticker(us_ticker: str) -> str:
    return SEC_TICKER_ALIASES.get(us_ticker.upper(), us_ticker.upper())


def has_sec_xbrl_cross_list(us_ticker: str) -> bool:
    """是否预期能从 SEC companyfacts 拉到 XBRL（非 OTC-only）。"""
    known_with_facts = frozenset({"BABA", "JD", "BIDU", "HSBC", "NTES", "LI", "XPEV", "NIO"})
    return us_ticker.upper() in known_with_facts
