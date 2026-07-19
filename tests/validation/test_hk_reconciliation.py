from backend.global_schema.models import CompanyFinancials, FieldValue, ValueScale
from backend.validation.reconciliation import FinancialReconciler, MatchStatus


def test_reconcile_pdf_only_trust_weights():
    pdf = CompanyFinancials(
        ticker="0700",
        company_name="Tencent",
        market="HK",
        cik="",
        standard="IFRS",
        periods=["2024-12-31"],
        values=[
            FieldValue(
                field_id="revenue",
                period_end="2024-12-31",
                fiscal_year=2024,
                value=100.0,
                currency="CNY",
                scale=ValueScale.MILLIONS,
                standard="IFRS",
                source="hk_pdf_grid",
                source_tag="Revenue",
                source_form="AR",
                filed_date="",
            )
        ],
    )
    reconciler = FinancialReconciler()
    skip = {f.field_id for f in __import__('backend.global_schema.registry', fromlist=['GLOBAL_FIELDS_V1']).GLOBAL_FIELDS_V1 if f.field_id != 'revenue'}
    report = reconciler.reconcile_pdf_only(pdf=pdf, skipped_fields=skip)
    assert report.pdf_only_mode is True
    item = next(i for i in report.items if i.field_id == "revenue")
    assert item.status == MatchStatus.PDF_ONLY
    assert item.pdf_value == 100.0
    assert report.trust_score >= 0.9
    assert report.pdf_coverage_rate == 1.0


def test_industry_skip_excluded_from_denominator():
    pdf = CompanyFinancials(
        ticker="1299",
        company_name="AIA",
        market="HK",
        cik="",
        standard="IFRS",
        periods=["2024-12-31"],
        values=[],
    )
    reconciler = FinancialReconciler()
    report = reconciler.reconcile_pdf_only(
        pdf=pdf,
        skipped_fields={"gross_profit", "operating_income"},
    )
    skipped = [i for i in report.items if i.status == MatchStatus.SKIPPED]
    assert len(skipped) >= 2
