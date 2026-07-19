from __future__ import annotations

from backend.global_schema.models import CompanyFinancials, FieldValue, ValueScale
from backend.validation.reconciliation import FinancialReconciler, MatchStatus, TrustLevel
from backend.validation.skipped_fields import build_skipped_cells


def _field(field_id: str, period: str, value: float, source: str = "xbrl") -> FieldValue:
    return FieldValue(
        field_id=field_id,
        period_end=period,
        fiscal_year=int(period[:4]),
        value=value,
        scale=ValueScale.MILLIONS,
        standard="US-GAAP",
        source=source,
        source_tag=source,
    )


def test_reconciler_matched_and_mismatch():
    periods = ["2024-09-28", "2023-09-30"]
    xbrl = CompanyFinancials(
        ticker="AAPL",
        company_name="Apple Inc.",
        market="US",
        cik="0000320193",
        standard="US-GAAP",
        periods=periods,
        values=[
            _field("revenue", periods[0], 391035.0),
            _field("revenue", periods[1], 383285.0),
            _field("net_income", periods[0], 93736.0),
        ],
    )
    pdf = CompanyFinancials(
        ticker="AAPL",
        company_name="Apple Inc.",
        market="US",
        cik="0000320193",
        standard="US-GAAP",
        periods=periods,
        values=[
            _field("revenue", periods[0], 391035.0, source="pdf_text"),
            _field("revenue", periods[1], 382000.0, source="pdf_text"),
            _field("net_income", periods[0], 93736.0, source="pdf_text"),
        ],
    )

    report = FinancialReconciler(abs_tolerance_millions=1.0).reconcile(xbrl, pdf)
    lookup = {(i.field_id, i.period_end): i for i in report.items}

    assert lookup[("revenue", periods[0])].status == MatchStatus.MATCHED
    assert lookup[("revenue", periods[0])].trust_level == TrustLevel.VERIFIED
    assert lookup[("revenue", periods[1])].status == MatchStatus.MISMATCH
    assert lookup[("net_income", periods[0])].status == MatchStatus.MATCHED
    assert report.verification_rate == 2 / 3
    assert report.pdf_coverage_rate == 1.0


def test_pdf_coverage_rate_excludes_skipped_xbrl_without_pdf():
    periods = ["2024-12-31"]
    xbrl = CompanyFinancials(
        ticker="MSFT",
        company_name="Microsoft",
        market="US",
        cik="0000789019",
        standard="US-GAAP",
        periods=periods,
        values=[
            _field("total_assets", periods[0], 512163.0),
            _field("revenue", periods[0], 245122.0),
        ],
    )
    pdf = CompanyFinancials(
        ticker="MSFT",
        company_name="Microsoft",
        market="US",
        cik="0000789019",
        standard="US-GAAP",
        periods=periods,
        values=[_field("total_assets", periods[0], 512163.0, source="pdf_text")],
    )
    report = FinancialReconciler().reconcile(
        xbrl,
        pdf,
        skipped_fields={"revenue"},
    )
    assert report.pdf_coverage_rate == 1.0


def test_pdf_coverage_rate_excludes_skipped_partial_balance_cells():
    periods = ["2024-03-31", "2023-03-31", "2022-03-31"]
    xbrl = CompanyFinancials(
        ticker="BABA",
        company_name="Alibaba",
        market="US",
        cik="0001577552",
        standard="US-GAAP",
        periods=periods,
        values=[
            _field("total_assets", periods[0], 100.0),
            _field("total_assets", periods[1], 90.0),
            _field("total_assets", periods[2], 80.0),
        ],
    )
    pdf = CompanyFinancials(
        ticker="BABA",
        company_name="Alibaba",
        market="US",
        cik="0001577552",
        standard="US-GAAP",
        periods=periods,
        values=[
            _field("total_assets", periods[0], 100.0, source="pdf_text"),
            _field("total_assets", periods[1], 90.0, source="pdf_text"),
        ],
    )
    skipped_cells = build_skipped_cells(pdf.values, periods, set(), xbrl_values=xbrl.values)
    report = FinancialReconciler().reconcile(xbrl, pdf, skipped_cells=skipped_cells)
    assert report.pdf_coverage_rate == 1.0


def test_reconciler_xbrl_only():
    periods = ["2024-09-28"]
    xbrl = CompanyFinancials(
        ticker="AAPL",
        company_name="Apple Inc.",
        market="US",
        cik="0000320193",
        standard="US-GAAP",
        periods=periods,
        values=[_field("gross_profit", periods[0], 180683.0)],
    )
    pdf = CompanyFinancials(
        ticker="AAPL",
        company_name="Apple Inc.",
        market="US",
        cik="0000320193",
        standard="US-GAAP",
        periods=periods,
        values=[],
    )
    report = FinancialReconciler().reconcile(xbrl, pdf)
    item = {(i.field_id, i.period_end): i for i in report.items}[("gross_profit", periods[0])]
    assert item.status == MatchStatus.XBRL_ONLY
    assert item.authoritative_source == "xbrl"


def test_reconciler_eps_split_factor_matches():
    periods = ["2024-01-28"]
    xbrl = CompanyFinancials(
        ticker="NVDA",
        company_name="NVIDIA",
        market="US",
        cik="0001045810",
        standard="US-GAAP",
        periods=periods,
        values=[
            FieldValue(
                field_id="eps_basic",
                period_end=periods[0],
                fiscal_year=2024,
                value=1.21,
                scale=ValueScale.PER_SHARE,
                standard="US-GAAP",
                source="xbrl",
                source_tag="us-gaap:EarningsPerShareBasic",
            )
        ],
    )
    pdf = CompanyFinancials(
        ticker="NVDA",
        company_name="NVIDIA",
        market="US",
        cik="0001045810",
        standard="US-GAAP",
        periods=periods,
        values=[
            FieldValue(
                field_id="eps_basic",
                period_end=periods[0],
                fiscal_year=2024,
                value=12.05,
                scale=ValueScale.PER_SHARE,
                standard="US-GAAP",
                source="pdf_text",
                source_tag="pdf_text",
            )
        ],
    )
    report = FinancialReconciler(abs_tolerance_millions=1.0).reconcile(xbrl, pdf)
    item = {(i.field_id, i.period_end): i for i in report.items}[("eps_basic", periods[0])]
    assert item.status == MatchStatus.MATCHED


def test_reconciler_skips_missing_xbrl_tag_when_both_empty():
    periods = ["2024-12-31"]
    xbrl = CompanyFinancials(
        ticker="GOOGL",
        company_name="Alphabet Inc.",
        market="US",
        cik="0001652044",
        standard="US-GAAP",
        periods=periods,
        values=[],
    )
    pdf = CompanyFinancials(
        ticker="GOOGL",
        company_name="Alphabet Inc.",
        market="US",
        cik="0001652044",
        standard="US-GAAP",
        periods=periods,
        values=[],
    )
    report = FinancialReconciler().reconcile(xbrl, pdf, skipped_fields={"gross_profit"})
    item = {(i.field_id, i.period_end): i for i in report.items}[("gross_profit", periods[0])]
    assert item.status == MatchStatus.SKIPPED


def test_reconciler_skips_pdf_only_when_xbrl_tag_missing():
    periods = ["2024-12-31"]
    xbrl = CompanyFinancials(
        ticker="JPM",
        company_name="JPMorgan",
        market="US",
        cik="0000019617",
        standard="US-GAAP",
        periods=periods,
        values=[],
    )
    pdf = CompanyFinancials(
        ticker="JPM",
        company_name="JPMorgan",
        market="US",
        cik="0000019617",
        standard="US-GAAP",
        periods=periods,
        values=[_field("gross_profit", periods[0], 99999.0, source="pdf_text")],
    )
    report = FinancialReconciler().reconcile(xbrl, pdf, skipped_fields={"gross_profit"})
    item = {(i.field_id, i.period_end): i for i in report.items}[("gross_profit", periods[0])]
    assert item.status == MatchStatus.SKIPPED
    assert item.authoritative_value is None


def test_reconciler_skips_xbrl_only_when_pdf_field_missing():
    periods = ["2024-12-31"]
    xbrl = CompanyFinancials(
        ticker="MSFT",
        company_name="Microsoft",
        market="US",
        cik="0000789019",
        standard="US-GAAP",
        periods=periods,
        values=[_field("total_assets", periods[0], 512163.0)],
    )
    pdf = CompanyFinancials(
        ticker="MSFT",
        company_name="Microsoft",
        market="US",
        cik="0000789019",
        standard="US-GAAP",
        periods=periods,
        values=[],
    )
    report = FinancialReconciler().reconcile(
        xbrl,
        pdf,
        skipped_fields={"total_assets"},
    )
    item = {(i.field_id, i.period_end): i for i in report.items}[("total_assets", periods[0])]
    assert item.status == MatchStatus.SKIPPED


def test_reconciler_capex_opposite_sign_matches():
    periods = ["2024-12-31"]
    xbrl = CompanyFinancials(
        ticker="GOOGL",
        company_name="Alphabet Inc.",
        market="US",
        cik="0001652044",
        standard="US-GAAP",
        periods=periods,
        values=[_field("capex", periods[0], 52535.0)],
    )
    pdf = CompanyFinancials(
        ticker="GOOGL",
        company_name="Alphabet Inc.",
        market="US",
        cik="0001652044",
        standard="US-GAAP",
        periods=periods,
        values=[_field("capex", periods[0], -52535.0, source="pdf_grid")],
    )
    report = FinancialReconciler(abs_tolerance_millions=1.0).reconcile(xbrl, pdf)
    item = {(i.field_id, i.period_end): i for i in report.items}[("capex", periods[0])]
    assert item.status == MatchStatus.MATCHED
    assert item.trust_level == TrustLevel.VERIFIED
