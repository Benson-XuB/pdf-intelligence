from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Dict, Optional

from backend.config import settings

logger = logging.getLogger(__name__)

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class SecEdgarClient:
    def __init__(self, user_agent: Optional[str] = None) -> None:
        self.user_agent = user_agent or settings.sec_user_agent
        self._ticker_index: Optional[Dict[str, int]] = None
        self._last_request_at = 0.0

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < settings.sec_request_interval_seconds:
            time.sleep(settings.sec_request_interval_seconds - elapsed)

    def _get_json(self, url: str) -> dict:
        self._throttle()
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=settings.sec_request_timeout_seconds) as resp:
                self._last_request_at = time.monotonic()
                return json.load(resp)
        except urllib.error.HTTPError as exc:
                raise RuntimeError(f"SEC request failed {exc.code}: {url}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"SEC network error: {exc.reason}") from exc

    def load_ticker_index(self) -> Dict[str, int]:
        if self._ticker_index is not None:
            return self._ticker_index
        raw = self._get_json(SEC_COMPANY_TICKERS_URL)
        index: Dict[str, int] = {}
        for entry in raw.values():
            ticker = str(entry["ticker"]).upper()
            index[ticker] = int(entry["cik_str"])
        self._ticker_index = index
        return index

    def resolve_cik(self, ticker: str) -> str:
        index = self.load_ticker_index()
        key = ticker.upper().strip()
        if key not in index:
            raise ValueError(f"Ticker not found: {ticker}")
        return f"{index[key]:010d}"

    def fetch_company_facts(self, ticker: str) -> dict:
        cik = self.resolve_cik(ticker)
        return self._get_json(SEC_COMPANY_FACTS_URL.format(cik=cik))
