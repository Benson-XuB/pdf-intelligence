from typing import Optional, Protocol, runtime_checkable

from backend.services.verified_models import VerifiedFinancialsResult


@runtime_checkable
class MarketFinancialsService(Protocol):
    def build_verified_financials(
        self,
        identifier: str,
        periods: int = 3,
        document_path: Optional[str] = None,
        export_excel: bool = True,
        output_dir: Optional[str] = None,
    ) -> VerifiedFinancialsResult: ...
