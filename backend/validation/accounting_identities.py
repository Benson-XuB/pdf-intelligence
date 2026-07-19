from __future__ import annotations

from typing import Dict, List, Optional

from backend.global_schema.models import CompanyFinancials
from backend.validation.identity_models import IdentityCheckItem, IdentityReport

BALANCE_EQUATION_RULE = "balance_equation"
BALANCE_EQUATION_LABEL = "Total Assets = Total Liabilities + Total Equity"


def _field_lookup(financials: CompanyFinancials) -> Dict[str, Dict[str, float]]:
    table: Dict[str, Dict[str, float]] = {}
    for item in financials.values:
        if item.value is None:
            continue
        table.setdefault(item.field_id, {})[item.period_end] = item.value
    return table


def _periods_for_rule(
    financials: CompanyFinancials,
    required_fields: List[str],
) -> List[str]:
    lookup = _field_lookup(financials)
    periods: List[str] = []
    for period in financials.periods or []:
        if all(period in lookup.get(field_id, {}) for field_id in required_fields):
            periods.append(period)
    return periods


class AccountingIdentityValidator:
    """L3 accounting identity checks on authoritative financial data."""

    def __init__(
        self,
        *,
        rel_tolerance: float = 0.0001,
        abs_tolerance_millions: float = 1.0,
    ) -> None:
        self.rel_tolerance = rel_tolerance
        self.abs_tolerance_millions = abs_tolerance_millions

    def validate(
        self,
        financials: CompanyFinancials,
        *,
        standard: Optional[str] = None,
    ) -> IdentityReport:
        std = standard or financials.standard or "US-GAAP"
        items: List[IdentityCheckItem] = []
        items.extend(self._check_balance_equation(financials))
        return IdentityReport(standard=std, items=items)

    def _check_balance_equation(self, financials: CompanyFinancials) -> List[IdentityCheckItem]:
        lookup = _field_lookup(financials)
        items: List[IdentityCheckItem] = []
        for period in _periods_for_rule(
            financials,
            ["total_assets", "total_liabilities", "total_equity"],
        ):
            assets = lookup["total_assets"][period]
            liabilities = lookup["total_liabilities"][period]
            equity = lookup["total_equity"][period]
            rhs = liabilities + equity
            delta = assets - rhs
            baseline = max(abs(assets), abs(rhs), 1.0)
            delta_rel = abs(delta) / baseline
            passed = abs(delta) <= max(
                self.abs_tolerance_millions,
                baseline * self.rel_tolerance,
            )
            items.append(
                IdentityCheckItem(
                    rule_id=BALANCE_EQUATION_RULE,
                    label=BALANCE_EQUATION_LABEL,
                    period_end=period,
                    passed=passed,
                    lhs_value=assets,
                    rhs_value=rhs,
                    delta=delta,
                    delta_rel=delta_rel,
                    message=(
                        f"assets={assets:.3f}, liabilities+equity={rhs:.3f}, delta={delta:.3f}"
                        if not passed
                        else "balanced"
                    ),
                )
            )
        return items
