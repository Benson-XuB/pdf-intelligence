"""ESEF benchmark corpus — verified LEI list from filings.xbrl.org."""

from __future__ import annotations

from pathlib import Path
from typing import List, TypedDict

from backend.markets.eu.filing_resolver import ESEF_BENCHMARK_ISSUERS

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_DIR = Path(__file__).resolve().parent


class EsefCorpusEntry(TypedDict):
    id: str
    name: str
    lei: str
    fiscal_year: int
    country: str
    xhtml: str


def _p(rel: str) -> str:
    return str(ROOT / rel)


def _entry(issuer: dict) -> EsefCorpusEntry:
    slug = issuer["id"].lower()
    return {
        "id": issuer["id"],
        "name": issuer["name"],
        "lei": issuer["lei"],
        "fiscal_year": issuer["fiscal_year"],
        "country": issuer["country"],
        "xhtml": _p(f"tests/benchmark/financial_esef/{slug}_annual.xhtml"),
    }


CORPUS_10: List[EsefCorpusEntry] = [_entry(item) for item in ESEF_BENCHMARK_ISSUERS]


def corpus_path(entry: EsefCorpusEntry) -> Path:
    return Path(entry["xhtml"])


def available_entries() -> List[EsefCorpusEntry]:
    return [entry for entry in CORPUS_10 if corpus_path(entry).exists()]
