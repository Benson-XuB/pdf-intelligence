#!/usr/bin/env python3
"""Download ESEF benchmark corpus from filings.xbrl.org into tests/benchmark/financial_esef/."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.markets.eu.filing_resolver import ESEF_BENCHMARK_ISSUERS, EsmaFilingsClient
from tests.benchmark.financial_esef.corpus import CORPUS_10, corpus_path

BENCHMARK_DIR = ROOT / "tests/benchmark/financial_esef"


def download_one(client: EsmaFilingsClient, issuer: dict, *, force: bool = False) -> Path:
    dest = BENCHMARK_DIR / f"{issuer['id'].lower()}_annual.xhtml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        print(f"SKIP {issuer['id']} (exists)")
        return dest

    print(f"DOWNLOAD {issuer['id']} LEI={issuer['lei']} FY{issuer['fiscal_year']} ...")
    doc = client.download_package(
        issuer["lei"],
        issuer["fiscal_year"],
        company_name=issuer["name"],
    )
    shutil.copy2(doc.local_path, dest)
    if not EsmaFilingsClient.xhtml_has_financial_statements(dest):
        print(
            f"  WARN {issuer['id']}: package may lack consolidated financial statements "
            f"({EsmaFilingsClient._estimate_page_count(dest)} pages)"
        )
    print(f"  -> {dest} ({dest.stat().st_size // 1024} KB)")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Download ESEF benchmark XHTML corpus")
    parser.add_argument("--id", help="Download single issuer id (e.g. ASML)")
    parser.add_argument("--force", action="store_true", help="Re-download even if file exists")
    parser.add_argument("--english-only", action="store_true", help="Skip issuers marked language=fr")
    parser.add_argument("--list", action="store_true", help="List benchmark issuers")
    args = parser.parse_args()

    if args.list:
        for item in CORPUS_10:
            path = Path(item["xhtml"])
            status = "OK" if path.exists() else "MISSING"
            print(f"{item['id']:6} {item['lei']} FY{item['fiscal_year']} [{status}] {path.name}")
        return 0

    client = EsmaFilingsClient()
    issuers = ESEF_BENCHMARK_ISSUERS
    if args.english_only:
        issuers = [i for i in issuers if i.get("language") != "fr"]
    if args.id:
        key = args.id.strip().upper()
        issuers = [i for i in issuers if i["id"].upper() == key]
        if not issuers:
            print(f"Unknown issuer id: {args.id}")
            return 1

    failed = 0
    for issuer in issuers:
        try:
            download_one(client, issuer, force=args.force)
        except Exception as exc:
            failed += 1
            print(f"FAIL {issuer['id']}: {exc}")

    print(f"Done. failed={failed}/{len(issuers)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
