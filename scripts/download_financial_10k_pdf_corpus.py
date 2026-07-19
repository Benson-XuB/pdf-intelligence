#!/usr/bin/env python3
"""下载 PDF-only / SEC 10-K HTML 语料（IR PDF → SEC ARS PDF → SEC 10-K HTML）。"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.markets.us.sec_client import SecEdgarClient
from tests.benchmark.financial_10k.corpus_pdf import (
    BENCHMARK_DIR,
    CORPUS_PDF,
    available_pdf_entries,
    dest_path,
    missing_pdf_entries,
)


def download_file(url: str, dest: Path, timeout: int = 180, sec: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": "pdf-intelligence-benchmark/1.0 (research; contact@example.com)",
        "Accept": "*/*",
    }
    if sec:
        headers = SecEdgarClient()._headers()
        headers["Accept"] = "*/*"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < 1000:
        raise ValueError(f"响应过小 ({len(data)} bytes)")
    dest.write_bytes(data)


def download_pdf(url: str, dest: Path, timeout: int = 180, sec: bool = False) -> None:
    download_file(url, dest, timeout=timeout, sec=sec)
    data = dest.read_bytes()
    if not data[:5].startswith(b"%PDF"):
        dest.unlink(missing_ok=True)
        raise ValueError("响应不是 PDF 文件")


def resolve_sec_ars_pdf(ticker: str, client: Optional[SecEdgarClient] = None) -> Tuple[str, str]:
    """返回 (filing_date, pdf_url) — 优先 FY2024 对应 ARS。"""
    client = client or SecEdgarClient()
    headers = client._headers()
    cik = client.resolve_cik(ticker)
    cik_int = int(cik)
    payload = client._get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    recent = payload["filings"]["recent"]

    candidates = []
    for idx, form in enumerate(recent["form"]):
        if form != "ARS":
            continue
        date = recent["filingDate"][idx]
        acc = recent["accessionNumber"][idx]
        acc_compact = acc.replace("-", "")
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_compact}/index.json"
        client._throttle()
        req = urllib.request.Request(index_url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            index = json.load(resp)
        pdfs = [it for it in index.get("directory", {}).get("item", []) if it.get("name", "").lower().endswith(".pdf")]
        if not pdfs:
            continue
        pdfs.sort(key=lambda x: -int(x.get("size") or 0))
        name = pdfs[0]["name"]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_compact}/{name}"
        year_hint = 0
        for token in (name, date):
            for y in ("2024", "2025", "2023"):
                if y in token:
                    year_hint = max(year_hint, int(y))
        candidates.append((year_hint, date, url, name))

    if not candidates:
        raise FileNotFoundError(f"{ticker} 无 SEC ARS PDF 附表")

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, date, url, _name = candidates[0]
    return date, url


def resolve_sec_10k_html(
    ticker: str,
    client: Optional[SecEdgarClient] = None,
    prefer_fiscal_year: int = 2024,
) -> Tuple[str, str, str]:
    """返回 (filing_date, document_name, url) — SEC 正式 10-K primary HTML。"""
    client = client or SecEdgarClient()
    cik = client.resolve_cik(ticker)
    cik_int = int(cik)
    payload = client._get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    recent = payload["filings"]["recent"]

    candidates = []
    for idx, form in enumerate(recent["form"]):
        if form not in ("10-K", "10-K/A"):
            continue
        date = recent["filingDate"][idx]
        primary = recent["primaryDocument"][idx]
        acc = recent["accessionNumber"][idx]
        if not primary.lower().endswith((".htm", ".html")):
            continue
        year_hint = 0
        for token in (primary, date):
            for y in (str(prefer_fiscal_year), str(prefer_fiscal_year + 1), str(prefer_fiscal_year - 1)):
                if y in token:
                    year_hint = max(year_hint, int(y))
        if year_hint == 0 and date[:4] >= str(prefer_fiscal_year + 1):
            year_hint = prefer_fiscal_year
        acc_compact = acc.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_compact}/{primary}"
        candidates.append((year_hint, date, primary, url, form))

    if not candidates:
        raise FileNotFoundError(f"{ticker} 无 SEC 10-K HTML")

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, date, primary, url, _form = candidates[0]
    return date, primary, url


def main() -> int:
    have = available_pdf_entries()
    need = missing_pdf_entries()
    print(f"语料: 已有 {len(have)}/{len(CORPUS_PDF)} | 待下载 {len(need)}")

    client = SecEdgarClient()
    results = []
    errors = []

    for entry in need:
        dest = dest_path(entry)
        url = entry.get("url")
        source = "ir"
        suffix = dest.suffix.lower()
        print(f"\n[{entry['id']}] tier={entry.get('tier','?')} → {dest.name}")

        if entry.get("sec_fallback") and suffix in {".htm", ".html"}:
            try:
                date, primary, sec_url = resolve_sec_10k_html(entry["id"], client)
                print(f"  SEC 10-K HTML ({date}, {primary}): {sec_url}")
                download_file(sec_url, dest, sec=True)
                url = sec_url
                source = "sec_10k_html"
            except Exception as sec_exc:
                errors.append({"id": entry["id"], "sec_10k_error": str(sec_exc)})
                print(f"  SEC 10-K ✗ {sec_exc}")
                continue
        elif url:
            print(f"  IR: {url}")
            try:
                if suffix == ".pdf":
                    download_pdf(url, dest)
                else:
                    download_file(url, dest)
            except Exception as ir_exc:
                print(f"  IR ✗ {ir_exc}")
                if suffix != ".pdf" or not entry.get("sec_fallback"):
                    if suffix == ".pdf":
                        try:
                            date, sec_url = resolve_sec_ars_pdf(entry["id"], client)
                            print(f"  SEC ARS ({date}): {sec_url}")
                            download_pdf(sec_url, dest, sec=True)
                            url = sec_url
                            source = "sec_ars"
                        except Exception as sec_exc:
                            if entry.get("sec_fallback"):
                                try:
                                    date, primary, sec_url = resolve_sec_10k_html(entry["id"], client)
                                    htm_dest = dest.with_suffix(".htm")
                                    print(f"  SEC 10-K HTML fallback ({date}): {sec_url}")
                                    download_file(sec_url, htm_dest, sec=True)
                                    url = sec_url
                                    source = "sec_10k_html"
                                    dest = htm_dest
                                except Exception as html_exc:
                                    errors.append(
                                        {
                                            "id": entry["id"],
                                            "ir_error": str(ir_exc),
                                            "sec_ars_error": str(sec_exc),
                                            "sec_10k_error": str(html_exc),
                                        }
                                    )
                                    print(f"  SEC 10-K ✗ {html_exc}")
                                    continue
                            else:
                                errors.append({"id": entry["id"], "ir_error": str(ir_exc), "sec_error": str(sec_exc)})
                                print(f"  SEC ✗ {sec_exc}")
                                continue
                    else:
                        errors.append({"id": entry["id"], "ir_error": str(ir_exc)})
                        continue
                else:
                    errors.append({"id": entry["id"], "ir_error": str(ir_exc)})
                    continue
        else:
            print("  跳过（无 URL 且非 sec_fallback）")
            continue

        size_mb = dest.stat().st_size / (1024 * 1024)
        results.append({"id": entry["id"], "dest": str(dest), "url": url, "source": source, "size_mb": round(size_mb, 2)})
        print(f"  ✓ {dest.name} ({size_mb:.1f} MB) [{source}]")

    manifest = BENCHMARK_DIR / "corpus_pdf_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "available": len(available_pdf_entries()),
                "total": len(CORPUS_PDF),
                "downloaded": results,
                "errors": errors,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n完成: 成功 {len(results)} | 失败 {len(errors)} | 可用 {len(available_pdf_entries())}/{len(CORPUS_PDF)}")
    print(f"manifest: {manifest}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
