"""European ESEF verified financials orchestrator (scaffold)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from backend.config import settings
from backend.export.formula_excel import FormulaExcelExporter
from backend.export.verified_excel import VerifiedExcelExporter
from backend.global_schema.models import CompanyFinancials
from backend.markets.eu.filing_resolver import EuFilingResolver
from backend.markets.us.filing_resolver import FilingDocument
from backend.markets.us.html_grid_extractor import extract_html_statement_grids
from backend.markets.us.statement_grid_extractor import StatementGridExtractor
from backend.markets.eu.statement_locator import locate_esef_statements_from_pages
from backend.services.verified_models import VerifiedFinancialsResult
from backend.validation.accounting_identities import AccountingIdentityValidator
from backend.validation.reconciliation import FinancialReconciler
from backend.validation.skipped_fields import build_skipped_fields, finalize_pdf_errors


class EuFinancialsService:
    """ESEF annual report pipeline — inline XHTML grid + internal consistency checks."""

    def __init__(self) -> None:
        self.filing_resolver = EuFilingResolver()
        self.grid_extractor = StatementGridExtractor()
        self.reconciler = FinancialReconciler(
            abs_tolerance_millions=settings.reconciliation_abs_tolerance_millions,
            rel_tolerance=settings.reconciliation_rel_tolerance,
        )
        self.identity_validator = AccountingIdentityValidator(
            rel_tolerance=settings.reconciliation_rel_tolerance,
            abs_tolerance_millions=settings.reconciliation_abs_tolerance_millions,
        )
        self.exporter = VerifiedExcelExporter()
        self.formula_exporter = FormulaExcelExporter()

    def build_verified_financials(
        self,
        lei: str,
        fiscal_year: int,
        periods: int = 2,
        document_path: Optional[str] = None,
        export_excel: bool = True,
        export_formula_excel: bool = True,
        output_dir: Optional[str] = None,
    ) -> VerifiedFinancialsResult:
        errors: List[str] = []
        issuer = EuFilingResolver.benchmark_issuer(lei)
        company_name = issuer["name"] if issuer else lei
        filing_doc = self.filing_resolver.resolve(
            lei,
            fiscal_year,
            explicit_path=document_path,
            company_name=company_name,
        )

        xhtml_path = str(filing_doc.local_path)
        pages = self._load_pages(xhtml_path)
        statement_pages = locate_esef_statements_from_pages(pages)
        if not statement_pages:
            errors.append("Could not locate financial statements in the ESEF document")

        grids = extract_html_statement_grids(
            xhtml_path,
            statement_pages,
            pages,
            market="ESEF",
        )
        period_ends = self._collect_periods(grids, periods)
        grid_values, grid_errors = self.grid_extractor.extract_fields(grids, period_ends)
        errors.extend(grid_errors)

        pdf = self._to_company_financials(
            lei=lei,
            company_name=company_name,
            grid_values=grid_values,
            period_ends=period_ends,
        )
        errors = finalize_pdf_errors(pdf.values, errors)

        xbrl = CompanyFinancials(
            ticker=lei[:6],
            company_name=company_name,
            market="EU",
            cik="",
            standard="IFRS",
            periods=period_ends,
            values=list(pdf.values),
        )

        skipped_fields = build_skipped_fields([], errors)
        reconciliation = self.reconciler.reconcile_pdf_only(
            pdf=pdf,
            pdf_source=xhtml_path,
            pdf_source_type="esef_xhtml",
            skipped_fields=skipped_fields,
        )
        identity_report = self.identity_validator.validate(pdf, standard="IFRS")

        us_filing = FilingDocument(
            form="ESEF Annual",
            filing_date=str(fiscal_year),
            accession_number=lei,
            primary_document=Path(xhtml_path).name,
            local_path=xhtml_path,
        )

        excel_path = None
        formula_excel_path = None
        if export_excel:
            out_dir = Path(output_dir or Path(settings.output_dir) / "verified_eu")
            out_dir.mkdir(parents=True, exist_ok=True)
            excel_path = str(out_dir / f"{lei}_{fiscal_year}_verified.xlsx")
            self.exporter.export(
                xbrl=xbrl,
                pdf=pdf,
                reconciliation=reconciliation,
                filing=us_filing,
                output_path=excel_path,
            )
        if export_formula_excel:
            out_dir = Path(output_dir or Path(settings.output_dir) / "verified_eu")
            out_dir.mkdir(parents=True, exist_ok=True)
            formula_excel_path = str(out_dir / f"{lei}_{fiscal_year}_formula_model.xlsx")
            self.formula_exporter.export(
                ticker=lei[:6],
                company_name=company_name,
                standard="IFRS",
                reconciliation=reconciliation,
                identity_report=identity_report,
                statement_grids=grids,
                authoritative=pdf,
                output_path=formula_excel_path,
            )

        return VerifiedFinancialsResult(
            ticker=lei[:6],
            company_name=company_name,
            market="EU",
            cik=lei,
            xbrl=xbrl,
            pdf=pdf,
            reconciliation=reconciliation,
            identity_report=identity_report,
            filing=us_filing,
            excel_path=excel_path,
            formula_excel_path=formula_excel_path,
            statement_grids=grids,
            errors=errors,
        )

    @staticmethod
    def _load_pages(xhtml_path: str) -> List[str]:
        import fitz

        doc = fitz.open(xhtml_path)
        pages = [doc[i].get_text().replace("\xa0", " ") for i in range(len(doc))]
        doc.close()
        return pages

    @staticmethod
    def _collect_periods(grids: dict, limit: int) -> List[str]:
        for stype in ("income", "balance", "cashflow"):
            grid = grids.get(stype)
            if grid and grid.period_ends:
                recent = [
                    period
                    for period in grid.period_ends
                    if re.fullmatch(r"20\d{2}-12-31", period)
                ]
                if recent:
                    return sorted(dict.fromkeys(recent))[-limit:]
                return grid.period_ends[:limit]
        return []

    @staticmethod
    def _to_company_financials(
        *,
        lei: str,
        company_name: str,
        grid_values: list,
        period_ends: List[str],
    ) -> CompanyFinancials:
        from backend.global_schema.models import FieldValue, ValueScale
        from backend.global_schema.registry import field_by_id

        registry = field_by_id()
        values: List[FieldValue] = []
        for field_id, period_end, label, val in grid_values:
            field_def = registry[field_id]
            values.append(
                FieldValue(
                    field_id=field_id,
                    period_end=period_end,
                    fiscal_year=int(period_end[:4]),
                    value=val,
                    currency="EUR",
                    scale=field_def.scale,
                    standard="IFRS",
                    source="esef_grid",
                    source_tag=label,
                )
            )
        return CompanyFinancials(
            ticker=lei[:6],
            company_name=company_name,
            market="EU",
            cik=lei,
            standard="IFRS",
            periods=period_ends,
            values=values,
        )
