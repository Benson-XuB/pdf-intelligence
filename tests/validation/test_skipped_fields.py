from backend.global_schema.models import CompanyFinancials, FieldValue, StatementType, ValueScale
from backend.validation.reconciliation import FinancialReconciler, MatchStatus
from backend.validation.skipped_fields import (
    build_skipped_cells,
    build_skipped_fields,
    finalize_pdf_errors,
)


def test_skipped_from_missing_xbrl_tag():
    skipped = build_skipped_fields(["缺少 XBRL 标签: gross_profit"], [])
    assert skipped == {"gross_profit"}


def test_skipped_from_pdf_field_error():
    skipped = build_skipped_fields([], ["PDF 未提取到: capex"])
    assert "capex" in skipped


def test_skipped_entire_statement_when_page_missing():
    skipped = build_skipped_fields([], ["缺少报表页: balance"])
    assert "total_assets" in skipped
    assert "total_liabilities" in skipped
    assert "total_equity" in skipped
    assert "cash" in skipped
    assert "revenue" not in skipped


def test_grid_missing_does_not_skip_entire_statement():
    skipped = build_skipped_fields([], ["缺少报表网格: cashflow"])
    assert "cfo" not in skipped
    assert StatementType.CASHFLOW.value == "cashflow"


def test_skipped_cells_when_pdf_covers_partial_periods():
    periods = ["2024-09-28", "2023-09-30", "2022-09-24"]
    pdf_values = [
        FieldValue(
            field_id="total_assets",
            period_end=periods[0],
            fiscal_year=2024,
            value=100.0,
            scale=ValueScale.MILLIONS,
            standard="US-GAAP",
            source="pdf_text",
            source_tag="total assets",
        ),
        FieldValue(
            field_id="total_assets",
            period_end=periods[1],
            fiscal_year=2023,
            value=90.0,
            scale=ValueScale.MILLIONS,
            standard="US-GAAP",
            source="pdf_text",
            source_tag="total assets",
        ),
    ]
    skipped_cells = build_skipped_cells(pdf_values, periods, set())
    assert ("total_assets", periods[2]) in skipped_cells
    assert ("total_assets", periods[0]) not in skipped_cells


def test_skipped_cells_when_xbrl_covers_partial_periods():
    periods = ["2024-12-31", "2023-12-31", "2022-12-31"]
    pdf_values = [
        FieldValue(
            field_id="revenue",
            period_end=periods[2],
            fiscal_year=2022,
            value=282836.0,
            scale=ValueScale.MILLIONS,
            standard="US-GAAP",
            source="pdf_text",
            source_tag="revenue",
        ),
    ]
    xbrl_values = [
        FieldValue(
            field_id="revenue",
            period_end=periods[0],
            fiscal_year=2024,
            value=350000.0,
            scale=ValueScale.MILLIONS,
            standard="US-GAAP",
            source="xbrl",
            source_tag="xbrl",
        ),
    ]
    skipped_cells = build_skipped_cells(pdf_values, periods, set(), xbrl_values=xbrl_values)
    assert ("revenue", periods[2]) in skipped_cells


def test_finalize_pdf_errors_suppresses_industry_skipped_fields():
    errors = finalize_pdf_errors(
        [],
        ["PDF 未提取到: gross_profit", "PDF 未提取到: revenue"],
        skip_field_ids={"gross_profit", "capex"},
    )
    assert "PDF 未提取到: gross_profit" not in errors
    assert "PDF 未提取到: capex" not in errors
    assert "PDF 未提取到: revenue" in errors


def test_finalize_pdf_errors_suppresses_missing_page_fields():
    errors = finalize_pdf_errors(
        [],
        ["缺少报表页: balance", "PDF 未提取到: total_assets"],
    )
    assert "PDF 未提取到: total_assets" not in errors
    assert "缺少报表页: balance" in errors


def test_finalize_pdf_errors_drops_false_missing():
    values = [
        FieldValue(
            field_id="revenue",
            period_end="2024-12-31",
            fiscal_year=2024,
            value=100.0,
            scale=ValueScale.MILLIONS,
            standard="US-GAAP",
            source="pdf_text",
            source_tag="revenue",
        )
    ]
    errors = finalize_pdf_errors(
        values,
        ["PDF 未提取到: revenue", "缺少报表网格: income", "缺少报表网格: income"],
    )
    assert "PDF 未提取到: revenue" not in errors
    assert errors.count("缺少报表网格: income") == 1
    assert "PDF 未提取到: gross_profit" in errors


def test_skipped_cells_when_neither_side_has_period():
    periods = ["2024-12-28", "2023-12-30", "2022-12-31"]
    pdf_values = [
        FieldValue(
            field_id="cash",
            period_end=periods[0],
            fiscal_year=2024,
            value=8249.0,
            scale=ValueScale.MILLIONS,
            standard="US-GAAP",
            source="pdf_text",
            source_tag="cash",
        ),
        FieldValue(
            field_id="cash",
            period_end=periods[1],
            fiscal_year=2023,
            value=7079.0,
            scale=ValueScale.MILLIONS,
            standard="US-GAAP",
            source="pdf_text",
            source_tag="cash",
        ),
    ]
    xbrl_values = [
        FieldValue(
            field_id="cash",
            period_end=periods[0],
            fiscal_year=2024,
            value=8249.0,
            scale=ValueScale.MILLIONS,
            standard="US-GAAP",
            source="xbrl",
            source_tag="xbrl",
        ),
    ]
    skipped = build_skipped_cells(pdf_values, periods, set(), xbrl_values=xbrl_values)
    assert ("cash", periods[2]) in skipped


def test_reconcile_skips_partial_pdf_period():
    periods = ["2024-09-28", "2023-09-30", "2022-09-24"]
    xbrl = CompanyFinancials(
        ticker="AAPL",
        company_name="Apple Inc.",
        market="US",
        cik="0000320193",
        standard="US-GAAP",
        periods=periods,
        values=[
            FieldValue(
                field_id="total_assets",
                period_end=periods[0],
                fiscal_year=2024,
                value=352.0,
                scale=ValueScale.MILLIONS,
                standard="US-GAAP",
                source="xbrl",
                source_tag="xbrl",
            ),
            FieldValue(
                field_id="total_assets",
                period_end=periods[2],
                fiscal_year=2022,
                value=300.0,
                scale=ValueScale.MILLIONS,
                standard="US-GAAP",
                source="xbrl",
                source_tag="xbrl",
            ),
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
            FieldValue(
                field_id="total_assets",
                period_end=periods[0],
                fiscal_year=2024,
                value=352.0,
                scale=ValueScale.MILLIONS,
                standard="US-GAAP",
                source="pdf_text",
                source_tag="total assets",
            )
        ],
    )
    skipped_cells = build_skipped_cells(pdf.values, periods, set(), xbrl_values=xbrl.values)
    report = FinancialReconciler().reconcile(xbrl, pdf, skipped_cells=skipped_cells)
    lookup = {(i.field_id, i.period_end): i for i in report.items}
    assert lookup[("total_assets", periods[0])].status == MatchStatus.MATCHED
    assert lookup[("total_assets", periods[2])].status == MatchStatus.SKIPPED
