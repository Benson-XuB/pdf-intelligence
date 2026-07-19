from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from backend.global_schema.models import CompanyFinancials
from backend.markets.us.filing_resolver import FilingDocument
from backend.markets.us.statement_grid_extractor import StatementGrid
from backend.validation.identity_models import IdentityReport
from backend.validation.reconciliation import ReconciliationReport


def _empty_identity_report() -> IdentityReport:
    return IdentityReport(standard="")


@dataclass
class VerifiedFinancialsResult:
    ticker: str
    company_name: str
    market: str = "US"
    cik: str = ""
    xbrl: CompanyFinancials = field(default_factory=CompanyFinancials)
    pdf: CompanyFinancials = field(default_factory=CompanyFinancials)
    reconciliation: ReconciliationReport = field(default_factory=ReconciliationReport)
    identity_report: IdentityReport = field(default_factory=_empty_identity_report)
    filing: Optional[FilingDocument] = None
    excel_path: Optional[str] = None
    formula_excel_path: Optional[str] = None
    statement_grids: Dict[str, StatementGrid] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    cross_list_ticker: Optional[str] = None

    @property
    def trust_score(self) -> float:
        return self.reconciliation.trust_score

    @property
    def verification_rate(self) -> float:
        return self.reconciliation.verification_rate

    @property
    def pdf_coverage_rate(self) -> float:
        return self.reconciliation.pdf_coverage_rate

    @property
    def is_production_ready(self) -> bool:
        from backend.config import settings

        return (
            self.verification_rate >= settings.verification_rate_threshold
            and self.reconciliation.mismatch_count == 0
        )
