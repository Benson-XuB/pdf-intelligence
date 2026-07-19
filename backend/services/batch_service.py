from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from backend.config import settings
from backend.export.batch_excel import BatchPortfolioExporter
from backend.markets.eu.financials_service import EuFinancialsService
from backend.markets.hk.financials_service import HkFinancialsService
from backend.markets.us.financials_service import UsFinancialsService
from backend.services.batch_models import BatchVerifyItem, BatchVerifyReport

logger = logging.getLogger(__name__)


class BatchVerificationService:
    def __init__(self) -> None:
        self.us_service = UsFinancialsService()
        self.hk_service = HkFinancialsService()
        self.eu_service = EuFinancialsService()
        self.exporter = BatchPortfolioExporter()

    def run(
        self,
        jobs: List[Tuple[str, str]],
        periods: int = 3,
        export_excel: bool = True,
        output_dir: Optional[str] = None,
    ) -> BatchVerifyReport:
        out_dir = Path(output_dir or Path(settings.output_dir) / "batch_verified")
        out_dir.mkdir(parents=True, exist_ok=True)

        items: List[BatchVerifyItem] = []
        markets = sorted({m.upper() for m, _ in jobs})
        tickers = [t.upper() for _, t in jobs]

        for market, ticker in jobs:
            market = market.upper()
            ticker = ticker.upper()
            item = BatchVerifyItem(market=market, ticker=ticker, success=False)
            try:
                if market == "US":
                    result = self.us_service.build_verified_financials(
                        ticker=ticker,
                        periods=periods,
                        export_excel=export_excel,
                        output_dir=str(out_dir / "us"),
                    )
                elif market == "HK":
                    result = self.hk_service.build_verified_financials(
                        ticker=ticker,
                        periods=periods,
                        export_excel=export_excel,
                        output_dir=str(out_dir / "hk"),
                    )
                elif market == "EU":
                    parts = ticker.split(":")
                    lei = parts[0]
                    fiscal_year = int(parts[1]) if len(parts) >= 2 else 2024
                    result = self.eu_service.build_verified_financials(
                        lei=lei,
                        fiscal_year=fiscal_year,
                        periods=periods,
                        export_excel=export_excel,
                        export_formula_excel=True,
                        output_dir=str(out_dir / "eu"),
                    )
                else:
                    raise ValueError(f"Unsupported market: {market}")

                item.success = True
                item.result = result
                item.company_name = result.company_name
                item.trust_score = result.trust_score
                item.verification_rate = result.verification_rate
                item.pdf_coverage_rate = result.pdf_coverage_rate
                item.production_ready = result.is_production_ready
                item.matched_count = result.reconciliation.matched_count
                item.mismatch_count = result.reconciliation.mismatch_count
                item.excel_path = result.excel_path
                item.errors = result.errors
            except Exception as exc:
                logger.warning("Batch verification failed %s %s: %s", market, ticker, exc)
                item.errors = [str(exc)]
            items.append(item)

        report = BatchVerifyReport(
            markets=markets,
            tickers=tickers,
            periods=periods,
            items=items,
        )

        if export_excel:
            portfolio_path = str(out_dir / "portfolio_summary.xlsx")
            self.exporter.export(report, portfolio_path)
            report.portfolio_excel_path = portfolio_path

        return report
