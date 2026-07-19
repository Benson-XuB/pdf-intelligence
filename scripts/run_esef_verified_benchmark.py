#!/usr/bin/env python3
"""Run ESEF verified financials benchmark on local corpus."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.global_schema.registry import GLOBAL_FIELDS_V1
from backend.markets.eu.filing_resolver import EsmaFilingsClient
from backend.markets.eu.financials_service import EuFinancialsService
from tests.benchmark.financial_esef.corpus import CORPUS_10, available_entries, corpus_path

REPORT_PATH = ROOT / "tests/benchmark/financial_esef/verified_accuracy_report.json"


@dataclass
class CompanyReport:
    id: str
    name: str
    lei: str
    fiscal_year: int
    xhtml_path: str
    field_coverage: float
    identity_pass_rate: float
    identity_all_passed: bool
    field_hits: str
    errors: list[str] = field(default_factory=list)


def _field_hits(result) -> tuple[int, int]:
    periods = set(result.pdf.periods or [])
    if not periods:
        return 0, 0
    hits = 0
    total = 0
    lookup = {(v.field_id, v.period_end) for v in result.pdf.values if v.value is not None}
    for field_def in GLOBAL_FIELDS_V1:
        for period in periods:
            total += 1
            if (field_def.field_id, period) in lookup:
                hits += 1
    return hits, total


def main() -> int:
    entries = available_entries()
    if not entries:
        print("No local ESEF corpus files. Run scripts/download_esef_benchmark_corpus.py first.")
        return 1

    service = EuFinancialsService()
    reports: list[CompanyReport] = []
    for entry in entries:
        try:
            path = corpus_path(entry)
            if not EsmaFilingsClient.xhtml_has_financial_statements(path):
                print(
                    f"{entry['id']:6} SKIP incomplete ESEF package "
                    "(no full financial statements in XHTML)"
                )
                continue
            result = service.build_verified_financials(
                lei=entry["lei"],
                fiscal_year=entry["fiscal_year"],
                document_path=str(corpus_path(entry)),
                export_excel=False,
                export_formula_excel=False,
            )
            hits, total = _field_hits(result)
            reports.append(
                CompanyReport(
                    id=entry["id"],
                    name=entry["name"],
                    lei=entry["lei"],
                    fiscal_year=entry["fiscal_year"],
                    xhtml_path=entry["xhtml"],
                    field_coverage=hits / total if total else 0.0,
                    identity_pass_rate=result.identity_report.pass_rate,
                    identity_all_passed=result.identity_report.all_passed,
                    field_hits=f"{hits}/{total}",
                    errors=result.errors,
                )
            )
            print(
                f"{entry['id']:6} coverage={hits}/{total} "
                f"identity={result.identity_report.pass_rate:.0%} "
                f"errors={len(result.errors)}"
            )
        except Exception as exc:
            reports.append(
                CompanyReport(
                    id=entry["id"],
                    name=entry["name"],
                    lei=entry["lei"],
                    fiscal_year=entry["fiscal_year"],
                    xhtml_path=entry["xhtml"],
                    field_coverage=0.0,
                    identity_pass_rate=0.0,
                    identity_all_passed=False,
                    field_hits="0/0",
                    errors=[str(exc)],
                )
            )
            print(f"{entry['id']:6} FAIL {exc}")

    overall_cov = sum(r.field_coverage for r in reports) / len(reports)
    overall_identity = sum(r.identity_pass_rate for r in reports) / len(reports)
    payload = {
        "pipeline": "eu_verified_financials (ESEF inline XHTML grid)",
        "corpus": "financial_esef",
        "tested_count": len(reports),
        "available_count": len(entries),
        "template_count": len(CORPUS_10),
        "overall_field_coverage": round(overall_cov, 4),
        "overall_identity_pass_rate": round(overall_identity, 4),
        "companies": [asdict(r) for r in reports],
    }
    REPORT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Report -> {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
