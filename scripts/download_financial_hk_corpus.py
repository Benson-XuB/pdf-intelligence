#!/usr/bin/env python3
"""下载港股 benchmark 年报 PDF（HKEX 直链 → SEC 20-F / ARS 回退）。"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.markets.us.sec_client import SecEdgarClient
from scripts.download_financial_10k_pdf_corpus import download_pdf, resolve_sec_ars_pdf
from tests.benchmark.financial_hk.corpus import (
    BENCHMARK_DIR,
    CORPUS_HK,
    available_entries,
    corpus_path,
    missing_entries,
)


def resolve_sec_20f_pdf(
    ticker: str,
    client: Optional[SecEdgarClient] = None,
    prefer_fiscal_year: int = 2024,
) -> Tuple[str, str]:
    """返回 (filing_date, pdf_url) — 交叉上市港股常用 Form 20-F。"""
    client = client or SecEdgarClient()
    headers = client._headers()
    cik = client.resolve_cik(ticker)
    cik_int = int(cik)
    payload = client._get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    recent = payload["filings"]["recent"]

    candidates: List[Tuple[int, str, str, str]] = []
    for idx, form in enumerate(recent["form"]):
        if form not in ("20-F", "20-F/A"):
            continue
        date = recent["filingDate"][idx]
        primary = recent["primaryDocument"][idx]
        acc = recent["accessionNumber"][idx]
        acc_compact = acc.replace("-", "")
        year_hint = 0
        for token in (primary, date):
            for y in (str(prefer_fiscal_year + 1), str(prefer_fiscal_year), str(prefer_fiscal_year - 1)):
                if y in token:
                    year_hint = max(year_hint, int(y))
        if not primary.lower().endswith(".pdf"):
            index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_compact}/index.json"
            client._throttle()
            req = urllib.request.Request(index_url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                index = json.load(resp)
            pdfs = [
                it["name"]
                for it in index.get("directory", {}).get("item", [])
                if it.get("name", "").lower().endswith(".pdf")
            ]
            if not pdfs:
                continue
            pdfs.sort(key=lambda n: ("annual" in n.lower(), "report" in n.lower(), len(n)), reverse=True)
            primary = pdfs[0]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_compact}/{primary}"
        candidates.append((year_hint, date, url, primary))

    if not candidates:
        raise FileNotFoundError(f"{ticker} 无 SEC 20-F PDF")

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, date, url, _ = candidates[0]
    return date, url


MIN_PDF_BYTES = 200_000  # 拒绝占位/公告类极小 PDF


def _try_urls(urls: List[str], dest: Path) -> str:
    last_err: Optional[Exception] = None
    for url in urls:
        try:
            download_pdf(url, dest)
            size = dest.stat().st_size
            if size < MIN_PDF_BYTES:
                raise ValueError(f"PDF 过小 ({size} bytes)，可能非完整年报")
            return url
        except Exception as exc:
            last_err = exc
            if dest.exists():
                dest.unlink(missing_ok=True)
            print(f"  HKEX ✗ {url[:80]}... ({exc})")
    if last_err:
        raise last_err
    raise ValueError("无下载 URL")


def main() -> int:
    have = available_entries()
    need = missing_entries()
    print(f"港股语料: 已有 {len(have)}/{len(CORPUS_HK)} | 待下载 {len(need)}")

    client = SecEdgarClient()
    results = []
    errors = []

    for entry in need:
        dest = corpus_path(entry)
        code = entry["id"]
        print(f"\n[{code}] {entry['name']} → {dest.name}")

        source = "hkex"
        url = ""
        try:
            urls = list(entry.get("urls") or [])
            if urls:
                url = _try_urls(urls, dest)
                print(f"  ✓ HKEX: {url}")
        except Exception as hk_exc:
            sec_ticker = entry.get("sec_ticker") or ""
            if not sec_ticker:
                errors.append({"id": code, "error": str(hk_exc)})
                print(f"  ✗ {hk_exc}")
                continue
            for resolver, label in (
                (resolve_sec_20f_pdf, "SEC 20-F"),
                (resolve_sec_ars_pdf, "SEC ARS"),
            ):
                try:
                    date, sec_url = resolver(sec_ticker, client)
                    print(f"  {label} ({date}): {sec_url}")
                    download_pdf(sec_url, dest, sec=True)
                    url = sec_url
                    source = label.lower().replace(" ", "_")
                    break
                except Exception as sec_exc:
                    print(f"  {label} ✗ {sec_exc}")
            else:
                errors.append({"id": code, "hkex_error": str(hk_exc)})
                continue

        size_mb = dest.stat().st_size / (1024 * 1024)
        results.append(
            {
                "id": code,
                "dest": str(dest),
                "url": url,
                "source": source,
                "size_mb": round(size_mb, 2),
                "sec_ticker": entry.get("sec_ticker", ""),
            }
        )
        print(f"  ✓ {dest.name} ({size_mb:.1f} MB) [{source}]")

    manifest = BENCHMARK_DIR / "corpus_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "available": len(available_entries()),
                "total": len(CORPUS_HK),
                "downloaded": results,
                "errors": errors,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n完成: 成功 {len(results)} | 失败 {len(errors)} | 可用 {len(available_entries())}/{len(CORPUS_HK)}")
    print(f"manifest: {manifest}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
