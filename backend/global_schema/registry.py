from __future__ import annotations

from typing import Dict, List

from backend.global_schema.models import GlobalField, StatementType, ValueScale

GLOBAL_FIELDS_V1: List[GlobalField] = [
    # Income statement
    GlobalField("revenue", StatementType.INCOME, "Revenue", "营业收入", ValueScale.MILLIONS),
    GlobalField("gross_profit", StatementType.INCOME, "Gross Profit", "毛利润", ValueScale.MILLIONS),
    GlobalField(
        "operating_income",
        StatementType.INCOME,
        "Operating Income",
        "营业利润",
        ValueScale.MILLIONS,
    ),
    GlobalField("net_income", StatementType.INCOME, "Net Income", "净利润", ValueScale.MILLIONS),
    GlobalField(
        "eps_basic",
        StatementType.INCOME,
        "Basic EPS",
        "基本每股收益",
        ValueScale.PER_SHARE,
    ),
    # Balance sheet
    GlobalField("total_assets", StatementType.BALANCE, "Total Assets", "总资产", ValueScale.MILLIONS),
    GlobalField(
        "total_liabilities",
        StatementType.BALANCE,
        "Total Liabilities",
        "总负债",
        ValueScale.MILLIONS,
    ),
    GlobalField(
        "total_equity",
        StatementType.BALANCE,
        "Total Equity",
        "股东权益",
        ValueScale.MILLIONS,
    ),
    GlobalField("cash", StatementType.BALANCE, "Cash & Equivalents", "现金及等价物", ValueScale.MILLIONS),
    # Cash flow
    GlobalField(
        "cfo",
        StatementType.CASHFLOW,
        "Cash from Operations",
        "经营活动现金流",
        ValueScale.MILLIONS,
    ),
    GlobalField(
        "cfi",
        StatementType.CASHFLOW,
        "Cash from Investing",
        "投资活动现金流",
        ValueScale.MILLIONS,
    ),
    GlobalField(
        "cff",
        StatementType.CASHFLOW,
        "Cash from Financing",
        "筹资活动现金流",
        ValueScale.MILLIONS,
    ),
    GlobalField("capex", StatementType.CASHFLOW, "CapEx", "资本开支", ValueScale.MILLIONS),
]


def field_by_id() -> Dict[str, GlobalField]:
    return {f.field_id: f for f in GLOBAL_FIELDS_V1}
