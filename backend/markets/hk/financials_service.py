from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set

from backend.config import settings
from backend.export.verified_excel import VerifiedExcelExporter
from backend.global_schema.models import CompanyFinancials
from backend.markets.hk.constants import normalize_hk_code, us_cross_list_ticker
from backend.markets.hk.industry import has_sec_xbrl_cross_list, industry_skipped_fields
from backend.markets.hk.pdf_extractor import HkFilingResolver, HkPdfTextExtractor
from backend.markets.us.filing_resolver import FilingDocument
from backend.markets.us.xbrl_adapter import UsSecXbrlAdapter
from backend.services.verified_models import VerifiedFinancialsResult
from backend.validation.accounting_identities import AccountingIdentityValidator
from backend.validation.reconciliation import FinancialReconciler, MatchStatus
from backend.validation.skipped_fields import build_skipped_fields, build_skipped_cells, finalize_pdf_errors
from backend.markets.us.period_parser import normalize_pdf_financials_periods


def _pdf_report_currency(pdf: CompanyFinancials) -> Optional[str]:
    currencies = {v.currency for v in pdf.values if v.currency}
    if "CNY" in currencies or "RMB" in currencies:
        return "CNY"
    if "HKD" in currencies:
        return "HKD"
    if "USD" in currencies:
        return "USD"
    return None


class HkFinancialsService:
    def __init__(self) -> None:
        self.pdf_extractor = HkPdfTextExtractor()
        self.filing_resolver = HkFilingResolver()
        self.us_xbrl = UsSecXbrlAdapter()
        self.reconciler = FinancialReconciler(
            abs_tolerance_millions=settings.reconciliation_abs_tolerance_millions,
            rel_tolerance=settings.hk_cross_list_rel_tolerance,
        )
        self.exporter = VerifiedExcelExporter()
        self.identity_validator = AccountingIdentityValidator(
            rel_tolerance=settings.hk_cross_list_rel_tolerance,
            abs_tolerance_millions=settings.reconciliation_abs_tolerance_millions,
        )

    def build_verified_financials(
        self,
        ticker: str,
        periods: int = 3,
        document_path: Optional[str] = None,
        export_excel: bool = True,
        output_dir: Optional[str] = None,
    ) -> VerifiedFinancialsResult:
        code = normalize_hk_code(ticker)
        errors: List[str] = []
        filing = self.filing_resolver.resolve(code, explicit_path=document_path)

        pdf_result = self.pdf_extractor.extract(
            filing.local_path,
            stock_code=code,
            max_periods=periods + 2,
        )
        pdf = self.pdf_extractor.to_company_financials(pdf_result, code)
        pdf.periods, pdf.values = normalize_pdf_financials_periods(
            pdf.periods,
            pdf.values,
            max_periods=periods,
        )
        pdf_currency = _pdf_report_currency(pdf)

        xbrl = self._empty_financials(code, pdf.periods)
        cross_list_ticker: Optional[str] = None
        cross_us = us_cross_list_ticker(code)
        use_pdf_only = True

        if cross_us and has_sec_xbrl_cross_list(cross_us):
            cross_list_ticker = cross_us
            try:
                us_xbrl = self.us_xbrl.fetch(
                    cross_us,
                    periods=periods + 2,
                    preferred_currency=pdf_currency or "CNY",
                )
                aligned = self._align_periods(us_xbrl.periods, pdf.periods, periods)
                if aligned and us_xbrl.values:
                    xbrl = self._filter_financials(us_xbrl, aligned)
                    pdf = self._filter_financials(pdf, aligned)
                    use_pdf_only = False
                    errors.append(
                        f"Using {cross_us} SEC XBRL ({xbrl.standard}, currency {pdf_currency or 'CNY'}) for cross-verification"
                    )
                else:
                    errors.append(f"HK and {cross_us} XBRL periods could not be aligned, using PDF-only trust model")
            except Exception as exc:
                errors.append(f"Cross-listed verification failed ({cross_us}): {exc}, using PDF-only trust model")
        elif cross_us:
            errors.append(f"{cross_us} has no SEC XBRL, using PDF-only trust model")
        else:
            errors.append("No US cross-listing configured, using PDF-only trust model")

        us_filing = FilingDocument(
            form=filing.form,
            filing_date=filing.filing_date,
            accession_number="",
            primary_document=Path(filing.local_path).name,
            local_path=filing.local_path,
        )

        industry_skip = industry_skipped_fields(code)
        pdf_result.errors = finalize_pdf_errors(
            pdf.values,
            pdf_result.errors,
            skip_field_ids=set(industry_skip),
        )
        skipped_fields: Set[str] = build_skipped_fields(xbrl.errors, pdf_result.errors) | industry_skip
        skipped_cells = build_skipped_cells(
            pdf.values,
            pdf.periods or [],
            skipped_fields,
            xbrl_values=xbrl.values if not use_pdf_only else None,
        )
        errors.extend(pdf_result.errors)
        if industry_skip:
            errors.append(f"Industry field skip: {', '.join(sorted(industry_skip))}")

        if use_pdf_only:
            reconciliation = self.reconciler.reconcile_pdf_only(
                pdf=pdf,
                pdf_source=filing.local_path,
                pdf_source_type=pdf_result.source_type,
                skipped_fields=skipped_fields,
                skipped_cells=skipped_cells,
            )
            self._apply_pdf_only_flags(pdf, reconciliation)
        else:
            reconciliation = self.reconciler.reconcile(
                xbrl=xbrl,
                pdf=pdf,
                pdf_source=filing.local_path,
                pdf_source_type=pdf_result.source_type,
                skipped_fields=skipped_fields,
                skipped_cells=skipped_cells,
            )
            self.reconciler.apply_verification_flags(xbrl, reconciliation)

        authoritative = pdf if use_pdf_only else xbrl
        identity_report = self.identity_validator.validate(
            authoritative,
            standard=authoritative.standard or "IFRS",
        )

        excel_path = None
        if export_excel:
            out_dir = Path(output_dir or Path(settings.output_dir) / "verified_hk")
            out_dir.mkdir(parents=True, exist_ok=True)
            excel_path = str(out_dir / f"hk_{code}_verified_financials.xlsx")
            self.exporter.export(
                xbrl=pdf if use_pdf_only else xbrl,
                pdf=pdf,
                reconciliation=reconciliation,
                filing=us_filing,
                output_path=excel_path,
            )

        return VerifiedFinancialsResult(
            ticker=code,
            company_name=pdf.company_name,
            market="HK",
            cik="",
            xbrl=xbrl if not use_pdf_only else pdf,
            pdf=pdf,
            reconciliation=reconciliation,
            identity_report=identity_report,
            filing=us_filing,
            excel_path=excel_path,
            errors=errors,
            cross_list_ticker=cross_list_ticker,
        )

    def _apply_pdf_only_flags(
        self,
        pdf: CompanyFinancials,
        report,
    ) -> CompanyFinancials:
        verified: dict[str, dict[str, bool]] = {}
        for item in report.items:
            if item.status == MatchStatus.PDF_ONLY:
                verified.setdefault(item.field_id, {})[item.period_end] = True
        for value in pdf.values:
            value.pdf_verified = verified.get(value.field_id, {}).get(value.period_end)
        return pdf

    def _align_periods(self, xbrl_periods: List[str], pdf_periods: List[str], limit: int) -> List[str]:
        common = sorted(set(xbrl_periods) & set(pdf_periods), reverse=True)
        if common:
            return common[:limit]
        pdf_years = {p[:4]: p for p in pdf_periods}
        xbrl_years = {p[:4]: p for p in xbrl_periods}
        aligned: List[str] = []
        for period in xbrl_periods:
            year = period[:4]
            if year in pdf_years:
                aligned.append(pdf_years[year])
            if len(aligned) >= limit:
                break
        if aligned:
            return aligned
        for period in pdf_periods:
            year = period[:4]
            if year in xbrl_years:
                aligned.append(period)
            if len(aligned) >= limit:
                break
        return aligned

    def _filter_financials(self, financials: CompanyFinancials, periods: List[str]) -> CompanyFinancials:
        allowed = set(periods)
        financials.periods = periods
        financials.values = [v for v in financials.values if v.period_end in allowed]
        return financials

    def _empty_financials(self, code: str, periods: List[str]) -> CompanyFinancials:
        return CompanyFinancials(
            ticker=code,
            company_name=f"HK:{code}",
            market="HK",
            cik="",
            standard="IFRS",
            periods=periods,
            values=[],
        )
