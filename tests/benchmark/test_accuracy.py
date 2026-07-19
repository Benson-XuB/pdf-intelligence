import json
import os
from pathlib import Path

import pytest

from backend.evaluation.accuracy import BenchmarkCase, evaluate_corpus
from backend.pipeline.orchestrator import PipelineOrchestrator
from tests.benchmark.generate_corpus import BENCHMARK_DIR, ensure_benchmark_corpus

TARGET_ACCURACY = 0.97


@pytest.fixture(scope="session")
def benchmark_corpus():
    return ensure_benchmark_corpus()


@pytest.fixture(scope="session")
def benchmark_cases(benchmark_corpus) -> list[BenchmarkCase]:
    cases = []
    for item in benchmark_corpus["cases"]:
        if item["name"].startswith("multi_page_p"):
            continue
        cases.append(
            BenchmarkCase(
                name=item["name"],
                pdf_path=str(BENCHMARK_DIR / item["pdf"]),
                page=item["page"],
                expected_rows=item["expected_rows"],
                min_accuracy=item.get("min_accuracy", 0.9),
            )
        )
    return cases


@pytest.fixture(scope="session")
def pipeline_results(benchmark_cases) -> dict[str, list]:
    from backend.config import settings
    settings.enable_docling = os.environ.get("ENABLE_DOCLING", "false").lower() == "true"

    orchestrator = PipelineOrchestrator()
    results = {}
    processed = set()
    for case in benchmark_cases:
        if case.pdf_path in processed:
            continue
        result = orchestrator.process(case.pdf_path)
        results[case.pdf_path] = result.tables
        processed.add(case.pdf_path)
    return results


def test_benchmark_overall_accuracy_at_least_90(benchmark_cases, pipeline_results):
    overall, details = evaluate_corpus(benchmark_cases, pipeline_results)

    report_lines = [f"\n{'Case':<30} {'Accuracy':>10} {'Source':>12} {'Pass':>6}"]
    report_lines.append("-" * 62)
    for d in details:
        report_lines.append(
            f"{d.case_name:<30} {d.accuracy:>10.2%} {d.source:>12} {'✓' if d.passed else '✗':>6}"
        )
    report_lines.append("-" * 62)
    report_lines.append(f"{'OVERALL':<30} {overall:>10.2%}")
    print("\n".join(report_lines))

    failed = [d for d in details if not d.passed]
    assert overall >= TARGET_ACCURACY, (
        f"整体准确率 {overall:.2%} 未达 {TARGET_ACCURACY:.0%}。"
        f" 失败用例: {[f.case_name for f in failed]}"
    )


def test_each_benchmark_case_individually(benchmark_cases, pipeline_results):
    _, details = evaluate_corpus(benchmark_cases, pipeline_results)
    for d in details:
        assert d.accuracy >= 0.95, f"{d.case_name} 准确率 {d.accuracy:.2%} 过低"
