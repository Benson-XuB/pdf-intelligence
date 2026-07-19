from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.config import settings

SITE_BASE = "https://filings.xbrl.org"

# LEI + fiscal_year verified against filings.xbrl.org (2026-07)
ESEF_BENCHMARK_ISSUERS = [
    {"id": "ASML", "name": "ASML Holding N.V.", "lei": "724500Y6DUVHQD6OXN27", "fiscal_year": 2025, "country": "NL"},
    {"id": "AIRBUS", "name": "AIRBUS SE", "lei": "MINO79WLOO247M1IL051", "fiscal_year": 2025, "country": "NL"},
    {"id": "SANOFI", "name": "SANOFI", "lei": "549300E9PC51EN656011", "fiscal_year": 2025, "country": "FR"},
    {"id": "TTE", "name": "TotalEnergies SE", "lei": "529900S21EQ1BO4ESM68", "fiscal_year": 2025, "country": "FR"},
    {"id": "OR", "name": "L'OREAL", "lei": "529900JI1GG6F7RKVI53", "fiscal_year": 2025, "country": "FR"},
    {"id": "SU", "name": "Schneider Electric SE", "lei": "969500A1YF1XUYYXS284", "fiscal_year": 2025, "country": "FR"},
    {"id": "PHIA", "name": "Koninklijke Philips N.V.", "lei": "H1FJE8H61JGM1JSGM897", "fiscal_year": 2025, "country": "NL"},
    {"id": "ADYEN", "name": "Adyen N.V.", "lei": "724500973ODKK3IFQ447", "fiscal_year": 2025, "country": "NL"},
    {"id": "HEIO", "name": "Heineken Holding N.V.", "lei": "724500M1WJLFM9TYBS04", "fiscal_year": 2025, "country": "NL"},
    {"id": "LVMH", "name": "LVMH", "lei": "IOG4E947OATN0KJYSD45", "fiscal_year": 2024, "country": "FR", "language": "fr"},
]


@dataclass
class EuFilingDocument:
    lei: str
    company_name: str
    fiscal_year: int
    local_path: Path
    xbrl_instance_path: Optional[Path] = None
    taxonomy: str = "ifrs-full"
    language: str = "en"
    filing_date: Optional[date] = None
    source_url: str = ""
    period_end: str = ""


class EsmaFilingsClient:
    """Fetch ESEF annual report packages from filings.xbrl.org (ESMA mirror)."""

    API_URL = f"{SITE_BASE}/api/filings"

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = cache_dir or Path(settings.filing_cache_dir) / "eu"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def list_filings(self, lei: str, fiscal_year: Optional[int] = None) -> List[dict]:
        params = {
            "filter[entity.identifier]": lei.strip().upper(),
            "include": "entity",
            "sort": "-period_end",
            "page[size]": 50,
        }
        url = f"{self.API_URL}?{urlencode(params)}"
        req = Request(url, headers={"Accept": "application/vnd.api+json", "User-Agent": "pdf-intelligence/1.0"})
        with urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        filings = payload.get("data", [])
        if fiscal_year is None:
            return filings
        year_prefix = f"{fiscal_year}-"
        matched = [
            item
            for item in filings
            if str(item.get("attributes", {}).get("period_end", "")).startswith(year_prefix)
        ]
        return matched or filings

    def pick_filing(self, lei: str, fiscal_year: int) -> Optional[dict]:
        filings = self.list_filings(lei, fiscal_year)
        if not filings:
            return None

        def _score(item: dict) -> tuple:
            attrs = item.get("attributes", {})
            period_end = str(attrs.get("period_end", ""))
            package = str(attrs.get("package_url", ""))
            report = str(attrs.get("report_url", ""))
            year_match = period_end.startswith(f"{fiscal_year}-")
            english = "-en" in package.lower() or "-en" in report.lower()
            french = "-fr" in package.lower() and not english
            december = period_end.endswith("-12-31")
            return (year_match, english, december, not french, period_end)

        return max(filings, key=_score)

    def resolve_package_url(self, lei: str, fiscal_year: int) -> Optional[str]:
        filing = self.pick_filing(lei, fiscal_year)
        if not filing:
            return None
        package_url = filing.get("attributes", {}).get("package_url")
        if not package_url:
            return None
        return self._absolute_url(package_url)

    def download_package(self, lei: str, fiscal_year: int, company_name: str = "") -> EuFilingDocument:
        lei = lei.strip().upper()
        cached = self._cached_document(lei, fiscal_year, company_name)
        if cached:
            return cached

        filing = self.pick_filing(lei, fiscal_year)
        if not filing:
            raise FileNotFoundError(f"No ESEF filing found for LEI {lei} FY{fiscal_year}")

        attrs = filing.get("attributes", {})
        package_url = attrs.get("package_url")
        if not package_url:
            raise FileNotFoundError(f"No package_url for LEI {lei} FY{fiscal_year}")

        download_url = self._absolute_url(package_url)
        suffix = Path(package_url).suffix or ".zip"
        zip_path = self.cache_dir / f"{lei}_{fiscal_year}{suffix}"
        req = Request(download_url, headers={"User-Agent": "pdf-intelligence/1.0"})
        with urlopen(req, timeout=300) as resp:
            zip_path.write_bytes(resp.read())

        extract_dir = self.cache_dir / f"{lei}_{fiscal_year}"
        if extract_dir.exists():
            import shutil

            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        xhtml = self._find_primary_xhtml(extract_dir)
        if not xhtml:
            raise FileNotFoundError(f"No inline XHTML found in ESEF package {zip_path}")

        period_end = str(attrs.get("period_end", ""))
        return EuFilingDocument(
            lei=lei,
            company_name=company_name or lei,
            fiscal_year=fiscal_year,
            local_path=xhtml,
            xbrl_instance_path=xhtml,
            source_url=download_url,
            period_end=period_end,
        )

    def _cached_document(
        self,
        lei: str,
        fiscal_year: int,
        company_name: str,
    ) -> Optional[EuFilingDocument]:
        extract_dir = self.cache_dir / f"{lei}_{fiscal_year}"
        if not extract_dir.exists():
            return None
        xhtml = self._find_primary_xhtml(extract_dir)
        if not xhtml:
            return None
        return EuFilingDocument(
            lei=lei,
            company_name=company_name or lei,
            fiscal_year=fiscal_year,
            local_path=xhtml,
            xbrl_instance_path=xhtml,
        )

    @staticmethod
    def _absolute_url(path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return f"{SITE_BASE}{path_or_url}"

    @staticmethod
    def _find_primary_xhtml(directory: Path) -> Optional[Path]:
        candidates = sorted(directory.rglob("*.xhtml")) + sorted(directory.rglob("*.html"))
        if not candidates:
            return None

        def _score(path: Path) -> tuple:
            name = path.name.lower()
            text = path.read_text(encoding="utf-8", errors="ignore")[:120_000].lower()
            english = 1 if re.search(r"-en\.xhtml$|annualreport.*en", name) else 0
            ifrs = 1 if (
                "ifrs-full:assets" in text
                or "total assets" in text
                or "bilan consolid" in text
                or "compte de résultat" in text
            ) else 0
            reports_dir = 1 if "/reports/" in str(path).lower() else 0
            page_count = EsmaFilingsClient._estimate_page_count(path)
            stmt_pages = 1 if page_count >= 80 else 0
            return (ifrs, stmt_pages, reports_dir, page_count, english, -len(str(path)))

        return max(candidates, key=_score)

    @staticmethod
    def _estimate_page_count(path: Path) -> int:
        try:
            import fitz

            doc = fitz.open(str(path))
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0

    @staticmethod
    def xhtml_has_financial_statements(path: Path, *, min_pages: int = 80) -> bool:
        """Heuristic: ESEF annual reports with statements are usually 80+ rendered pages."""
        if not path.exists():
            return False
        page_count = EsmaFilingsClient._estimate_page_count(path)
        if page_count >= min_pages:
            return True
        sample = path.read_text(encoding="utf-8", errors="ignore")[:200_000].lower()
        return bool(
            re.search(
                r"consolidated statement of (?:financial position|comprehensive income|cash flows)|"
                r"compte de r[eé]sultat consolid|bilan consolid|tableau des flux de tr[eé]sorerie",
                sample,
                re.I,
            )
        )


class EuFilingResolver:
    def __init__(self) -> None:
        self.client = EsmaFilingsClient()

    def resolve(
        self,
        lei: str,
        fiscal_year: int,
        *,
        explicit_path: Optional[str] = None,
        company_name: str = "",
    ) -> EuFilingDocument:
        lei = lei.strip().upper()
        if explicit_path:
            path = Path(explicit_path)
            if not path.exists():
                raise FileNotFoundError(explicit_path)
            return EuFilingDocument(
                lei=lei,
                company_name=company_name or lei,
                fiscal_year=fiscal_year,
                local_path=path,
                xbrl_instance_path=path,
            )
        return self.client.download_package(lei, fiscal_year, company_name=company_name)

    @staticmethod
    def benchmark_issuer(lei_or_id: str) -> Optional[dict]:
        key = lei_or_id.strip().upper()
        for item in ESEF_BENCHMARK_ISSUERS:
            if item["lei"].upper() == key or item["id"].upper() == key or item["name"].upper() == key:
                return item
        return None
