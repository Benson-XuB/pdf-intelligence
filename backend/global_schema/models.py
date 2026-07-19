from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class StatementType(str, Enum):
    INCOME = "income"
    BALANCE = "balance"
    CASHFLOW = "cashflow"


class ValueScale(str, Enum):
    UNITS = "units"
    THOUSANDS = "thousands"
    MILLIONS = "millions"
    PER_SHARE = "per_share"


@dataclass(frozen=True)
class GlobalField:
    field_id: str
    statement: StatementType
    label_en: str
    label_zh: str
    scale: ValueScale


@dataclass
class FieldValue:
    field_id: str
    period_end: str
    fiscal_year: Optional[int]
    value: Optional[float]
    currency: str = "USD"
    scale: ValueScale = ValueScale.MILLIONS
    standard: str = ""
    source: str = ""
    source_tag: str = ""
    source_form: str = ""
    filed_date: str = ""
    pdf_verified: Optional[bool] = None


@dataclass
class CompanyFinancials:
    ticker: str
    company_name: str
    market: str
    cik: str
    standard: str
    values: List[FieldValue] = field(default_factory=list)
    periods: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def by_statement(self, statement: StatementType) -> List[FieldValue]:
        from backend.global_schema.registry import field_by_id

        ids = {
            f.field_id
            for f in field_by_id().values()
            if f.statement == statement
        }
        return [v for v in self.values if v.field_id in ids]
