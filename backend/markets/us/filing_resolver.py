from __future__ import annotations

import logging
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from backend.config import settings
from backend.markets.us.sec_client import SecEdgarClient

logger = logging.getLogger(__name__)

TICKER_FILENAME_HINTS: Dict[str, List[str]] = {
    "AAPL": ["apple"],
    "GOOGL": ["googl", "goog", "alphabet"],
    "AMZN": ["amzn", "amazon"],
    "META": ["meta"],
    "MSFT": ["msft", "microsoft"],
}

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"


@dataclass
class FilingDocument:
    form: str
    filing_date: str
    accession_number: str
    primary_document: str
    local_path: Optional[str] = None


class UsFilingResolver:
    def __init__(self, client: Optional[SecEdgarClient] = None) -> None:
        self.client = client or SecEdgarClient()
        self.cache_dir = Path(settings.filing_cache_dir)

    def resolve_document(
        self,
        ticker: str,
        explicit_path: Optional[str] = None,
        prefer_form: str = "10-K",
    ) -> FilingDocument:
        if explicit_path:
            path = Path(explicit_path)
            if not path.exists():
                raise FileNotFoundError(f"Document not found: {explicit_path}")
            return FilingDocument(
                form=prefer_form,
                filing_date="",
                accession_number="",
                primary_document=path.name,
                local_path=str(path.resolve()),
            )

        local = self._find_local_filing(ticker)
        if local:
            return local

        return self._download_latest_filing(ticker, prefer_form=prefer_form)

    def _find_local_filing(self, ticker: str) -> Optional[FilingDocument]:
        ticker_upper = ticker.upper()
        ticker_lower = ticker.lower()
        search_roots = [
            Path("tests/benchmark/financial_10k"),
            Path("data/samples"),
        ]
        hints = TICKER_FILENAME_HINTS.get(ticker_upper, [ticker_lower])
        patterns = []
        for hint in hints:
            patterns.extend(
                [
                    f"{hint}*_10k.pdf",
                    f"{hint}*annual*report*.pdf",
                    f"*{hint}*10k*.pdf",
                ]
            )
        patterns.extend(
            [
                f"{ticker_lower}_*_10k.pdf",
                f"{ticker_upper}_*_10k.pdf",
                f"*{ticker_lower}*10k*.pdf",
                f"{ticker_lower}_*_10k.htm",
                f"{ticker_lower}_*_10k.html",
            ]
        )
        candidates: List[Path] = []
        for root in search_roots:
            if not root.exists():
                continue
            for pattern in patterns:
                candidates.extend(root.glob(pattern))

        cache_root = Path("data/filings")
        if cache_root.exists():
            for pattern in patterns:
                candidates.extend(cache_root.glob(pattern))

        if not candidates:
            return None

        def _rank(path: Path) -> tuple:
            name = path.name.lower()
            pdf_bonus = 0 if path.suffix.lower() == ".pdf" else 1
            exact_bonus = 0 if ticker_lower in name and "10k" in name else 1
            sample_bonus = 0 if "samples" in str(path) or "benchmark" in str(path) else 1
            return (pdf_bonus, exact_bonus, sample_bonus, -path.stat().st_mtime)

        best = sorted(candidates, key=_rank)[0]
        return FilingDocument(
            form="10-K",
            filing_date="",
            accession_number="",
            primary_document=best.name,
            local_path=str(best.resolve()),
        )

    def _download_latest_filing(self, ticker: str, prefer_form: str = "10-K") -> FilingDocument:
        cik = self.client.resolve_cik(ticker)
        cik_int = int(cik)
        payload = self.client._get_json(SEC_SUBMISSIONS_URL.format(cik=cik))
        recent = payload["filings"]["recent"]
        accession = None
        filing_date = ""
        primary_doc = ""
        form = ""
        for idx, item_form in enumerate(recent["form"]):
            if item_form != prefer_form:
                continue
            accession = recent["accessionNumber"][idx]
            filing_date = recent["filingDate"][idx]
            primary_doc = recent["primaryDocument"][idx]
            form = item_form
            break

        if not accession:
            raise FileNotFoundError(f"No {prefer_form} filing found for {ticker}")

        accession_compact = accession.replace("-", "")
        url = SEC_ARCHIVES_URL.format(
            cik_int=cik_int,
            accession=accession_compact,
            document=primary_doc,
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(primary_doc).suffix.lower() or ".htm"
        local_path = self.cache_dir / f"{ticker.lower()}_{filing_date}_{prefer_form.lower()}{suffix}"

        if not local_path.exists():
            logger.info("下载 SEC 申报文件: %s", url)
            req = urllib.request.Request(url, headers=self.client._headers())
            with urllib.request.urlopen(req, timeout=settings.sec_request_timeout_seconds) as resp:
                local_path.write_bytes(resp.read())

        return FilingDocument(
            form=form,
            filing_date=filing_date,
            accession_number=accession,
            primary_document=primary_doc,
            local_path=str(local_path.resolve()),
        )
