#!/usr/bin/env python3
"""运行 PDF 基准测试并输出准确率报告。"""

import json
import os
import sys
from pathlib import Path

# 必须在 import backend 之前设置，避免 Docling 模型加载拖慢基准测试
os.environ.setdefault("ENABLE_DOCLING", "false")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.evaluation.accuracy import BenchmarkCase, evaluate_corpus
from backend.pipeline.orchestrator import PipelineOrchestrator
from tests.benchmark.generate_corpus import BENCHMARK_DIR, ensure_benchmark_corpus

TARGET = 0.97


def main() -> int:
    gt = ensure_benchmark_corpus()
    cases = [
        BenchmarkCase(
            name=c["name"],
            pdf_path=str(BENCHMARK_DIR / c["pdf"]),
            page=c["page"],
            expected_rows=c["expected_rows"],
            min_accuracy=c.get("min_accuracy", 0.9),
        )
        for c in gt["cases"]
    ]

    orchestrator = PipelineOrchestrator()
    results = {}
    for pdf in sorted({c.pdf_path for c in cases}):
        r = orchestrator.process(pdf)
        results[pdf] = r.tables

    overall, details = evaluate_corpus(cases, results)

    print(f"\n{'Case':<30} {'Accuracy':>10} {'Source':>12} {'Pass':>6}")
    print("-" * 62)
    for d in details:
        mark = "PASS" if d.passed else "FAIL"
        print(f"{d.case_name:<30} {d.accuracy:>9.2%} {d.source:>12} {mark:>6}")
    print("-" * 62)
    print(f"{'OVERALL':<30} {overall:>9.2%}")
    print(f"\nTarget: {TARGET:.0%}  |  Result: {'PASS' if overall >= TARGET else 'FAIL'}")

    report_path = BENCHMARK_DIR / "last_report.json"
    report_path.write_text(
        json.dumps(
            {"overall": overall, "target": TARGET, "cases": [d.__dict__ for d in details]},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"Report saved: {report_path}")
    return 0 if overall >= TARGET else 1


if __name__ == "__main__":
    sys.exit(main())
