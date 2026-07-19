from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from backend.services.verified_models import VerifiedFinancialsResult


@dataclass
class BatchVerifyItem:
    market: str
    ticker: str
    success: bool
    company_name: str = ""
    trust_score: float = 0.0
    verification_rate: float = 0.0
    pdf_coverage_rate: float = 0.0
    production_ready: bool = False
    matched_count: int = 0
    mismatch_count: int = 0
    excel_path: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    result: Optional[VerifiedFinancialsResult] = None


@dataclass
class BatchVerifyReport:
    markets: List[str]
    tickers: List[str]
    periods: int
    items: List[BatchVerifyItem] = field(default_factory=list)
    summary_path: Optional[str] = None
    portfolio_excel_path: Optional[str] = None

    @property
    def success_count(self) -> int:
        return len([i for i in self.items if i.success])

    @property
    def production_ready_count(self) -> int:
        return len([i for i in self.items if i.production_ready])

    @property
    def avg_trust_score(self) -> float:
        ok = [i.trust_score for i in self.items if i.success]
        return sum(ok) / len(ok) if ok else 0.0
