#!/usr/bin/env python3
"""从 SEC EDGAR 下载 financial_10k 语料（目标 20 家）。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.benchmark.financial_10k.corpus import BENCHMARK_DIR, CORPUS_20, corpus_path, missing_entries

from backend.markets.us.filing_resolver import UsFilingResolver


def download_one(ticker: str, dest: Path) -> dict:
    resolver = UsFilingResolver()
    filing = resolver._download_latest_filing(ticker, prefer_form="10-K")
    src = Path(filing.local_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return {
        "ticker": ticker,
        "dest": str(dest),
        "source": str(src),
        "form": filing.form,
        "filing_date": filing.filing_date,
        "primary_document": filing.primary_document,
    }


def main() -> int:
    missing = missing_entries()
    if not missing:
        print(f"语料已齐全: {len(CORPUS_20)}/{len(CORPUS_20)}")
        return 0

    print(f"待下载 {len(missing)} 家 → {BENCHMARK_DIR}")
    results = []
    errors = []

    for entry in missing:
        ticker = entry["id"]
        dest = corpus_path(entry)
        if dest.exists():
            continue
        print(f"\n[{ticker}] 下载最新 10-K ...")
        try:
            meta = download_one(ticker, dest)
            results.append(meta)
            print(f"  ✓ {dest.name} ({meta['filing_date']})")
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)})
            print(f"  ✗ {exc}")

    manifest = BENCHMARK_DIR / "corpus_manifest.json"
    manifest.write_text(
        json.dumps({"downloaded": results, "errors": errors}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n完成: 成功 {len(results)} | 失败 {len(errors)} | manifest: {manifest}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
