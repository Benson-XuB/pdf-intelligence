from __future__ import annotations

from backend.global_schema.models import CompanyFinancials, FieldValue, ValueScale
from backend.validation.accounting_identities import (
    BALANCE_EQUATION_RULE,
    AccountingIdentityValidator,
)


def _field(field_id: str, period: str, value: float) -> FieldValue:
    return FieldValue(
        field_id=field_id,
        period_end=period,
        fiscal_year=int(period[:4]),
        value=value,
        scale=ValueScale.MILLIONS,
        standard="US-GAAP",
        source="xbrl",
    )


def _financials(*values: FieldValue) -> CompanyFinancials:
    periods = sorted({v.period_end for v in values}, reverse=True)
    return CompanyFinancials(
        ticker="TEST",
        company_name="Test Co",
        market="US",
        cik="0000000000",
        standard="US-GAAP",
        periods=periods,
        values=list(values),
    )


def test_balance_equation_passes_when_balanced():
    period = "2024-12-31"
    fv = _financials(
        _field("total_assets", period, 1000.0),
        _field("total_liabilities", period, 600.0),
        _field("total_equity", period, 400.0),
    )
    report = AccountingIdentityValidator().validate(fv, standard="US-GAAP")
    assert report.all_passed
    assert report.pass_count == 1
    assert report.items[0].rule_id == BALANCE_EQUATION_RULE


def test_balance_equation_fails_when_imbalanced():
    period = "2024-12-31"
    fv = _financials(
        _field("total_assets", period, 1000.0),
        _field("total_liabilities", period, 600.0),
        _field("total_equity", period, 350.0),
    )
    report = AccountingIdentityValidator().validate(fv)
    assert not report.all_passed
    assert report.fail_count == 1
    assert report.items[0].delta == 50.0


def test_balance_equation_skips_incomplete_periods():
    fv = _financials(
        _field("total_assets", "2024-12-31", 1000.0),
        _field("total_liabilities", "2024-12-31", 600.0),
        _field("total_equity", "2023-12-31", 400.0),
    )
    report = AccountingIdentityValidator().validate(fv)
    assert report.pass_count == 0
    assert report.items == []


def test_balance_equation_ifrs_standard():
    period = "2024-12-31"
    fv = _financials(
        _field("total_assets", period, 500.0),
        _field("total_liabilities", period, 300.0),
        _field("total_equity", period, 200.0),
    )
    fv.standard = "IFRS"
    report = AccountingIdentityValidator().validate(fv, standard="IFRS")
    assert report.standard == "IFRS"
    assert report.all_passed
