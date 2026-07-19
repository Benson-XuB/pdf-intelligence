from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ANCHOR_FIELDS = ("revenue", "net_income", "gross_profit", "cfo", "total_assets")

from backend.config import settings
from backend.global_schema.models import CompanyFinancials, FieldValue, ValueScale
from backend.global_schema.registry import field_by_id
from backend.export.formula_excel import FormulaExcelExporter
from backend.export.verified_excel import VerifiedExcelExporter
from backend.markets.us.filing_resolver import FilingDocument
from backend.markets.us.pdf_extractor import UsPdfTextExtractor
from backend.markets.us.xbrl_adapter import UsSecXbrlAdapter
from backend.services.verified_models import VerifiedFinancialsResult
from backend.validation.accounting_identities import AccountingIdentityValidator
from backend.validation.reconciliation import FinancialReconciler
from backend.validation.skipped_fields import build_skipped_fields, build_skipped_cells, finalize_pdf_errors


class UsFinancialsService:
    def __init__(self) -> None:
        self.xbrl_adapter = UsSecXbrlAdapter()
        self.pdf_extractor = UsPdfTextExtractor()
        from backend.markets.us.filing_resolver import UsFilingResolver

        self.filing_resolver = UsFilingResolver()
        self.reconciler = FinancialReconciler(
            abs_tolerance_millions=settings.reconciliation_abs_tolerance_millions,
            rel_tolerance=settings.reconciliation_rel_tolerance,
        )
        self.exporter = VerifiedExcelExporter()
        self.formula_exporter = FormulaExcelExporter()
        self.identity_validator = AccountingIdentityValidator(
            rel_tolerance=settings.reconciliation_rel_tolerance,
            abs_tolerance_millions=settings.reconciliation_abs_tolerance_millions,
        )

    def build_verified_financials(
        self,
        ticker: str,
        periods: int = 3,
        document_path: Optional[str] = None,
        export_excel: bool = True,
        export_formula_excel: bool = True,
        output_dir: Optional[str] = None,
    ) -> VerifiedFinancialsResult:
        errors: List[str] = []
        filing = self.filing_resolver.resolve_document(ticker, explicit_path=document_path)

        pdf_result = self.pdf_extractor.extract(
            filing.local_path or "",
            target_periods=None,
            max_periods=periods + 2,
        )
        pdf_periods = pdf_result.periods[: periods + 2]

        xbrl = self.xbrl_adapter.fetch(ticker, periods=periods + 2)
        errors.extend(xbrl.errors)

        pdf_company = pdf_result.to_company_financials(
            ticker=ticker,
            company_name=xbrl.company_name,
            cik=xbrl.cik,
        )
        xbrl = self._refine_xbrl_equity_tag(xbrl, pdf_company, periods + 2)
        aligned_periods, pdf_period_map = self._align_periods(
            xbrl.periods,
            pdf_periods,
            periods,
            xbrl=xbrl,
            pdf=pdf_company,
        )
        if not aligned_periods:
            aligned_periods = xbrl.periods[:periods]
            pdf_period_map = {}
            errors.append("PDF and XBRL periods could not be aligned, outputting XBRL data only")

        xbrl = self._filter_financials(xbrl, aligned_periods, remap_by_year=False)
        pdf = self._filter_financials(pdf_company, aligned_periods, pdf_period_map=pdf_period_map)
        pdf_result.errors = finalize_pdf_errors(pdf_company.values, pdf_result.errors)

        skipped_fields = build_skipped_fields(xbrl.errors, pdf_result.errors)
        skipped_cells = build_skipped_cells(
            pdf.values,
            aligned_periods,
            skipped_fields,
            xbrl_values=xbrl.values,
        )
        errors.extend(pdf_result.errors)
        reconciliation = self.reconciler.reconcile(
            xbrl=xbrl,
            pdf=pdf,
            pdf_source=filing.local_path or "",
            pdf_source_type=pdf_result.source_type,
            skipped_fields=skipped_fields,
            skipped_cells=skipped_cells,
        )
        self.reconciler.apply_verification_flags(xbrl, reconciliation)
        identity_report = self.identity_validator.validate(xbrl, standard=xbrl.standard)

        excel_path = None
        formula_excel_path = None
        if export_excel:
            out_dir = Path(output_dir or Path(settings.output_dir) / "verified_us")
            out_dir.mkdir(parents=True, exist_ok=True)
            excel_path = str(out_dir / f"{ticker.lower()}_verified_financials.xlsx")
            self.exporter.export(
                xbrl=xbrl,
                pdf=pdf,
                reconciliation=reconciliation,
                filing=filing,
                output_path=excel_path,
            )
        if export_formula_excel:
            out_dir = Path(output_dir or Path(settings.output_dir) / "verified_us")
            out_dir.mkdir(parents=True, exist_ok=True)
            formula_excel_path = str(out_dir / f"{ticker.lower()}_formula_model.xlsx")
            self.formula_exporter.export(
                ticker=xbrl.ticker,
                company_name=xbrl.company_name,
                standard=xbrl.standard,
                reconciliation=reconciliation,
                identity_report=identity_report,
                statement_grids=pdf_result.statement_grids,
                authoritative=xbrl,
                output_path=formula_excel_path,
            )

        return VerifiedFinancialsResult(
            ticker=xbrl.ticker,
            company_name=xbrl.company_name,
            market=xbrl.market,
            cik=xbrl.cik,
            xbrl=xbrl,
            pdf=pdf,
            reconciliation=reconciliation,
            identity_report=identity_report,
            filing=filing,
            excel_path=excel_path,
            formula_excel_path=formula_excel_path,
            statement_grids=pdf_result.statement_grids,
            errors=errors,
        )

    def _align_periods(
        self,
        xbrl_periods: List[str],
        pdf_periods: List[str],
        limit: int,
        xbrl=None,
        pdf=None,
    ) -> Tuple[List[str], Dict[str, str]]:
        exact = sorted(set(xbrl_periods) & set(pdf_periods), reverse=True)
        if len(exact) >= limit:
            chosen = exact[:limit]
            return chosen, {period: period for period in chosen}

        period_map: Dict[str, str] = {}
        if xbrl is not None and pdf is not None:
            period_map = self._match_pdf_periods_by_values(xbrl, pdf, limit)

        pdf_by_year = {p[:4]: p for p in sorted(pdf_periods, reverse=True)}
        aligned: List[str] = []
        seen_years: set[str] = set()
        for xbrl_period in sorted(xbrl_periods, reverse=True):
            year = xbrl_period[:4]
            if year in seen_years:
                continue
            if xbrl_period in period_map:
                aligned.append(xbrl_period)
            elif year in pdf_by_year:
                aligned.append(xbrl_period)
                period_map.setdefault(xbrl_period, pdf_by_year[year])
            else:
                continue
            seen_years.add(year)
            if len(aligned) >= limit:
                break
        return aligned, period_map

    def _match_pdf_periods_by_values(self, xbrl, pdf, limit: int) -> Dict[str, str]:
        xbrl_lookup = self._field_value_lookup(xbrl)
        pdf_lookup = self._field_value_lookup(pdf)
        mapping: Dict[str, str] = {}
        used_pdf: set[str] = set()

        for xbrl_period in sorted(xbrl.periods or [], reverse=True):
            if len(mapping) >= limit:
                break

            best_pdf = None
            best_score = 0
            for pdf_period in sorted(pdf.periods or [], reverse=True):
                if pdf_period in used_pdf:
                    continue
                score = sum(
                    1
                    for field_id in ANCHOR_FIELDS
                    if self._anchor_values_match(
                        xbrl_lookup.get(field_id, {}).get(xbrl_period),
                        pdf_lookup.get(field_id, {}).get(pdf_period),
                    )
                )
                if score > best_score:
                    best_score = score
                    best_pdf = pdf_period
            if best_pdf and best_score >= 1:
                mapping[xbrl_period] = best_pdf
                used_pdf.add(best_pdf)
        return mapping

    def _refine_xbrl_equity_tag(self, xbrl, pdf, periods_limit: int):
        """在多个 equity tag 中选取与 PDF 合计行最一致的一组（如是否含 NCI）。"""
        gaap = self.xbrl_adapter._gaap_cache.get(xbrl.ticker.upper())
        if not gaap:
            return xbrl

        pdf_lookup = self._field_value_lookup(pdf).get("total_equity", {})
        if not pdf_lookup:
            return xbrl

        from backend.markets.us.xbrl_adapter import US_GAAP_TAGS, _normalize_value, _pick_tag_entries

        field_def = field_by_id()["total_equity"]
        best_picked = None
        best_score = -1
        for tag in US_GAAP_TAGS["total_equity"]:
            picked = _pick_tag_entries(gaap, [tag], "total_equity", field_def.scale, periods_limit)
            if not picked:
                continue
            score = 0
            for _, entry in picked:
                val = _normalize_value(float(entry["val"]), field_def.scale)
                period = entry["end"]
                for pdf_period, pdf_val in pdf_lookup.items():
                    if pdf_period == period or pdf_period[:4] == period[:4]:
                        if self._anchor_values_match(val, pdf_val):
                            score += 1
                            break
            if score > best_score:
                best_score = score
                best_picked = picked

        if not best_picked or best_score < 1:
            return xbrl

        kept = [v for v in xbrl.values if v.field_id != "total_equity"]
        for tag, entry in best_picked:
            kept.append(
                FieldValue(
                    field_id="total_equity",
                    period_end=entry["end"],
                    fiscal_year=entry.get("fy"),
                    value=_normalize_value(float(entry["val"]), field_def.scale),
                    currency="USD",
                    scale=field_def.scale,
                    standard="US-GAAP",
                    source="xbrl",
                    source_tag=f"us-gaap:{tag}",
                    source_form=entry.get("form", ""),
                    filed_date=entry.get("filed", ""),
                )
            )
        xbrl.values = kept
        return xbrl

    @staticmethod
    def _field_value_lookup(financials) -> Dict[str, Dict[str, float]]:
        table: Dict[str, Dict[str, float]] = {}
        for item in financials.values:
            if item.value is None:
                continue
            table.setdefault(item.field_id, {})[item.period_end] = item.value
        return table

    @staticmethod
    def _anchor_values_match(xbrl_value: Optional[float], pdf_value: Optional[float]) -> bool:
        if xbrl_value is None or pdf_value is None:
            return False
        delta = abs(xbrl_value - pdf_value)
        baseline = max(abs(xbrl_value), abs(pdf_value), 1.0)
        return delta <= max(settings.reconciliation_abs_tolerance_millions, baseline * settings.reconciliation_rel_tolerance)

    def _filter_financials(
        self,
        financials,
        periods: List[str],
        pdf_period_map: Optional[Dict[str, str]] = None,
        remap_by_year: bool = True,
    ):
        allowed = set(periods)
        year_to_period = {p[:4]: p for p in periods}
        pdf_to_canonical = {pdf_period: xbrl_period for xbrl_period, pdf_period in (pdf_period_map or {}).items()}
        financials.periods = periods
        remapped = []
        for value in financials.values:
            if value.period_end in allowed:
                remapped.append(value)
                continue
            canonical = pdf_to_canonical.get(value.period_end)
            if canonical:
                remapped.append(
                    replace(
                        value,
                        period_end=canonical,
                        fiscal_year=int(canonical[:4]),
                    )
                )
                continue
            if not remap_by_year:
                continue
            canonical = year_to_period.get(value.period_end[:4])
            if canonical and value.period_end not in pdf_to_canonical:
                remapped.append(
                    replace(
                        value,
                        period_end=canonical,
                        fiscal_year=int(canonical[:4]),
                    )
                )
        financials.values = remapped
        return financials
