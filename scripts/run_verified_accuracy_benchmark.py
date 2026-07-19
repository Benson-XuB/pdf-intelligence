#!/usr/bin/env python3
"""用 financial_10k 模版 PDF 评测校验管线准确度（PDF 提取 vs 官方文本标准答案）。"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.evaluation.financial_statement import extract_ground_truth, locate_statements
from backend.markets.us.financials_service import UsFinancialsService
from backend.markets.us.pdf_extractor import UsPdfTextExtractor
from backend.validation.reconciliation import MatchStatus

from tests.benchmark.financial_10k.corpus import CORPUS_20, available_entries, corpus_path
from tests.benchmark.financial_10k.corpus_pdf import (
    as_benchmark_templates,
    available_pdf_entries,
    entries_for_tier,
)

BENCHMARK_DIR = ROOT / "tests/benchmark/financial_10k"
REPORT_PATH = BENCHMARK_DIR / "verified_accuracy_report.json"
REPORT_PDF_PATH = BENCHMARK_DIR / "verified_accuracy_report_pdf_only.json"

TEMPLATES = CORPUS_20

# 官方 ground-truth 行项 -> Global Schema field_id
GT_FIELD_MAP = {
    "total_net_sales": "revenue",
    "gross_margin": "gross_profit",
    "operating_income": "operating_income",
    "net_income": "net_income",
    "eps_basic": "eps_basic",
    "total_assets": "total_assets",
    "total_liabilities": "total_liabilities",
    "total_equity": "total_equity",
    "cash": "cash",
    "operating": "cfo",
    "investing": "cfi",
    "financing": "cff",
    "capex": "capex",
}

STMT_FOR_GT = {
    "revenue": "income",
    "gross_profit": "income",
    "operating_income": "income",
    "net_income": "income",
    "eps_basic": "income",
    "total_assets": "balance",
    "total_liabilities": "balance",
    "total_equity": "balance",
    "cash": "balance",
    "cfo": "cashflow",
    "cfi": "cashflow",
    "cff": "cashflow",
    "capex": "cashflow",
}

THRESHOLD_GO = 0.90
THRESHOLD_STOP = 0.80


@dataclass
class FieldHit:
    field_id: str
    gt_key: str
    period_index: int
    expected: Optional[float]
    actual: Optional[float]
    matched: bool


@dataclass
class CompanyReport:
    id: str
    name: str
    pdf_path: str
    tier: str
    pdf_extraction_accuracy: float
    verification_rate: float
    trust_score: float
    production_ready: bool
    pdf_coverage_rate: float
    matched_recon: int
    mismatch_recon: int
    field_hits: int
    field_total: int
    details: List[FieldHit] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _pdf_value_by_field(pdf_financials, field_id: str, period_end: str) -> Optional[float]:
    for v in pdf_financials.values:
        if v.field_id == field_id and v.period_end == period_end:
            return v.value
    year = period_end[:4]
    for v in pdf_financials.values:
        if v.field_id == field_id and v.period_end.startswith(year):
            return v.value
    return None


def _gt_periods_for_field(pdf_path: str, field_id: str, col_count: int) -> List[str]:
    stype = STMT_FOR_GT.get(field_id, "income")
    pages = locate_statements(pdf_path)
    if stype not in pages:
        return []
    from backend.markets.us.statement_text import load_statement_text

    page_text = load_statement_text(pdf_path, stype, pages[stype])
    from backend.markets.us.period_parser import parse_statement_periods, resolve_balance_periods

    parsed = parse_statement_periods(page_text, max_periods=col_count)
    if stype == "balance":
        income_pages = locate_statements(pdf_path)
        income_parsed = []
        if "income" in income_pages:
            income_text = load_statement_text(pdf_path, "income", income_pages["income"])
            income_parsed = parse_statement_periods(income_text, max_periods=col_count)
        parsed = resolve_balance_periods(parsed, income_parsed, col_count)
    elif not parsed and stype in ("cashflow", "balance"):
        income_pages = locate_statements(pdf_path)
        if "income" in income_pages:
            income_text = load_statement_text(pdf_path, "income", income_pages["income"])
            parsed = parse_statement_periods(income_text, max_periods=col_count)
    return [p.period_end for p in parsed[:col_count]]


def _build_ground_truth(pdf_path: str) -> Dict[str, Dict[str, List[Optional[float]]]]:
    pages = locate_statements(pdf_path)
    out: Dict[str, Dict[str, List[Optional[float]]]] = {}
    for stype, page in pages.items():
        truth = extract_ground_truth(pdf_path, stype, page)
        for item in truth.items:
            field_id = GT_FIELD_MAP.get(item.key)
            if not field_id:
                continue
            out[field_id] = {"gt_key": item.key, "values": item.values}
    return out


def evaluate_company(template: dict, periods: int = 3) -> Optional[CompanyReport]:
    pdf_path = Path(template["pdf"])
    if not pdf_path.exists():
        return None

    service = UsFinancialsService()
    result = service.build_verified_financials(
        ticker=template["id"],
        periods=periods,
        document_path=str(pdf_path),
        export_excel=False,
    )
    pdf_extract = UsPdfTextExtractor().extract(str(pdf_path), max_periods=periods + 2)
    pdf_for_accuracy = pdf_extract.to_company_financials(
        ticker=template["id"],
        company_name=result.company_name,
        cik=result.cik,
    )

    gt = _build_ground_truth(str(pdf_path))
    details: List[FieldHit] = []
    hits = 0
    total = 0

    for field_id, payload in gt.items():
        expected_vals = payload["values"]
        gt_periods = _gt_periods_for_field(str(pdf_path), field_id, len(expected_vals))
        for col_idx, expected in enumerate(expected_vals):
            if expected is None:
                continue
            period_end = gt_periods[col_idx] if col_idx < len(gt_periods) else f"col{col_idx}"
            actual = _pdf_value_by_field(pdf_for_accuracy, field_id, period_end) if gt_periods else None
            total += 1
            matched = actual is not None and abs(expected - actual) < 1.0
            if matched:
                hits += 1
            details.append(
                FieldHit(
                    field_id=field_id,
                    gt_key=payload["gt_key"],
                    period_index=col_idx,
                    expected=expected,
                    actual=actual,
                    matched=matched,
                )
            )

    accuracy = hits / total if total else 0.0
    return CompanyReport(
        id=template["id"],
        name=template["name"],
        pdf_path=str(pdf_path),
        tier=template.get("tier", "A"),
        pdf_extraction_accuracy=round(accuracy, 4),
        verification_rate=result.verification_rate,
        trust_score=result.trust_score,
        pdf_coverage_rate=result.pdf_coverage_rate,
        production_ready=result.is_production_ready,
        matched_recon=result.reconciliation.matched_count,
        mismatch_recon=result.reconciliation.mismatch_count,
        field_hits=hits,
        field_total=total,
        details=details,
        errors=result.errors,
    )


def _verdict(overall: float) -> str:
    if overall >= THRESHOLD_GO:
        return "GO — 模版准确度达标，可继续产品化"
    if overall < THRESHOLD_STOP:
        return "STOP — 模版准确度不足，先优化提取"
    return "HOLD — 80–90%，需补字段/格式"


def run_benchmark(periods: int = 3, templates: Optional[List[dict]] = None, corpus_label: str = "financial_10k") -> dict:
    tpl_list = templates if templates is not None else TEMPLATES
    companies: List[CompanyReport] = []
    missing = []

    for tpl in tpl_list:
        path = Path(tpl["pdf"])
        if not path.exists():
            missing.append(str(path))
            continue
        report = evaluate_company(tpl, periods=periods)
        if report:
            companies.append(report)

    overall_pdf = (
        sum(c.field_hits for c in companies) / sum(c.field_total for c in companies)
        if companies and sum(c.field_total for c in companies)
        else 0.0
    )
    overall_verify = (
        sum(c.verification_rate for c in companies) / len(companies) if companies else 0.0
    )
    overall_trust = (
        sum(c.trust_score for c in companies) / len(companies) if companies else 0.0
    )
    overall_pdf_coverage = (
        sum(c.pdf_coverage_rate for c in companies) / len(companies) if companies else 0.0
    )
    mismatch_total = sum(c.mismatch_recon for c in companies)

    tier_stats: Dict[str, dict] = {}
    for tier in ("A", "B", "C", "X"):
        tier_companies = [c for c in companies if getattr(c, "tier", "A") == tier]
        if not tier_companies:
            continue
        hits = sum(c.field_hits for c in tier_companies)
        total = sum(c.field_total for c in tier_companies)
        tier_stats[tier] = {
            "count": len(tier_companies),
            "pdf_extraction_accuracy": round(hits / total, 4) if total else 0.0,
        }

    return {
        "pipeline": "verified_financials (SEC XBRL × PDF text)",
        "corpus": corpus_label,
        "template_count": len(tpl_list),
        "tested_count": len(companies),
        "missing_templates": missing,
        "hk_templates": "无 — tests/benchmark/financial_hk/ 为空，需先找港股年报 PDF",
        "overall_pdf_extraction_accuracy": round(overall_pdf, 4),
        "overall_verification_rate": round(overall_verify, 4),
        "overall_trust_score": round(overall_trust, 4),
        "overall_pdf_coverage_rate": round(overall_pdf_coverage, 4),
        "total_reconciliation_mismatches": mismatch_total,
        "threshold_go": THRESHOLD_GO,
        "threshold_stop": THRESHOLD_STOP,
        "verdict": _verdict(overall_pdf),
        "tier_stats": tier_stats,
        "companies": [
            {
                "id": c.id,
                "name": c.name,
                "pdf": c.pdf_path,
                "tier": getattr(c, "tier", "A"),
                "pdf_extraction_accuracy": c.pdf_extraction_accuracy,
                "verification_rate": c.verification_rate,
                "trust_score": round(c.trust_score, 4),
                "pdf_coverage_rate": round(c.pdf_coverage_rate, 4),
                "production_ready": c.production_ready,
                "recon_matched": c.matched_recon,
                "recon_mismatch": c.mismatch_recon,
                "field_hits": f"{c.field_hits}/{c.field_total}",
                "errors": c.errors,
                "misses": [
                    asdict(d)
                    for d in c.details
                    if not d.matched
                ],
            }
            for c in companies
        ],
    }


def print_report(report: dict, report_path: Optional[Path] = None) -> None:
    out = report_path or REPORT_PATH
    print("\n" + "=" * 72)
    print("校验管线模版准确度 — financial_10k 标准答案对比")
    if report.get("corpus"):
        print(f"语料: {report['corpus']}")
    print("=" * 72)
    print(f"模版数: {report['tested_count']}/{report['template_count']}")
    print(f"PDF 提取准确度: {report['overall_pdf_extraction_accuracy']:.1%}")
    print(f"XBRL×PDF 校验通过率: {report['overall_verification_rate']:.1%}")
    if report.get("overall_trust_score") is not None:
        print(f"平均信任分: {report['overall_trust_score']:.1%}")
    if report.get("overall_pdf_coverage_rate") is not None:
        print(f"平均 PDF 覆盖率: {report['overall_pdf_coverage_rate']:.1%}")
    print(f"对账不一致项: {report['total_reconciliation_mismatches']}")
    print(f"判定: {report['verdict']}")
    if report.get("tier_stats"):
        print("分 Tier:")
        for tier, stats in sorted(report["tier_stats"].items()):
            print(f"  Tier {tier}: {stats['count']} 家, PDF {stats['pdf_extraction_accuracy']:.1%}")
    if report["missing_templates"]:
        print("缺少模版:", ", ".join(report["missing_templates"]))
    print(f"港股: {report['hk_templates']}")
    print("-" * 72)

    for co in report["companies"]:
        mark = (
            "✅"
            if co["pdf_extraction_accuracy"] >= THRESHOLD_GO
            else ("❌" if co["pdf_extraction_accuracy"] < THRESHOLD_STOP else "⚠️")
        )
        print(
            f"{mark} {co['id']:<6} PDF {co['pdf_extraction_accuracy']:>6.1%}  "
            f"校验 {co['verification_rate']:>6.1%}  "
            f"信任 {co['trust_score']:.1%}  "
            f"覆盖 {co.get('pdf_coverage_rate', 0):.1%}  "
            f"不一致 {co['recon_mismatch']}  "
            f"命中 {co['field_hits']}"
        )
        for miss in co["misses"][:6]:
            print(
                f"      MISS {miss['field_id']:<18} col{miss['period_index']}  "
                f"官方={miss['expected']}  提取={miss['actual']}"
            )
        if len(co["misses"]) > 6:
            print(f"      ... 另有 {len(co['misses']) - 6} 项未命中")

    print("=" * 72)
    print(f"报告: {out}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="financial_10k 模版准确度基准")
    parser.add_argument(
        "--pdf-only",
        action="store_true",
        help="仅评测 PDF-only 语料 (corpus_pdf.py)",
    )
    parser.add_argument("--tier-a", action="store_true", help="语料仅 Tier A")
    parser.add_argument("--tier-b", action="store_true", help="语料仅 Tier B")
    parser.add_argument("--tier-c", action="store_true", help="语料仅 Tier C (SEC 10-K HTML)")
    parser.add_argument("--periods", type=int, default=3)
    args = parser.parse_args()

    if args.pdf_only:
        tier_flags = sum(1 for f in (args.tier_a, args.tier_b, args.tier_c) if f)
        if tier_flags > 1:
            print("不能同时指定多个 --tier-* 过滤")
            return 2
        tier_filter = (
            "A"
            if args.tier_a
            else ("B" if args.tier_b else ("C" if args.tier_c else None))
        )
        templates = as_benchmark_templates(tier=tier_filter)
        label = "financial_10k_corpus"
        if tier_filter:
            label += f"_tier_{tier_filter.lower()}"
        report = run_benchmark(periods=args.periods, templates=templates, corpus_label=label)
        out_path = (
            REPORT_PDF_PATH
            if tier_filter is None
            else BENCHMARK_DIR / f"verified_accuracy_report_tier_{tier_filter.lower()}.json"
        )
        print(f"语料: 测试 {report['tested_count']}/{len(templates)} 家")
    else:
        report = run_benchmark(periods=args.periods)
        out_path = REPORT_PATH

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(report, out_path)
    if report["overall_pdf_extraction_accuracy"] < THRESHOLD_STOP:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
