#!/usr/bin/env python3
"""魔王级 PDF 压力测试 - 纯引擎（跳过 Qwen API，专注测量 pipeline 优化效果）"""
import os, sys, time, json, traceback
from pathlib import Path

# 跳过 Qwen API 调用，专注测量 Docling+pdfplumber+分类+合并性能
os.environ["DASHSCOPE_API_KEY"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.orchestrator import PipelineOrchestrator

TEST_DIR = Path(__file__).resolve().parent.parent / "data" / "test_pdfs"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "test_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

pdfs = sorted(TEST_DIR.glob("*.pdf"))

print("=" * 80)
print("  魔王级 PDF 压力测试 (优化后 - 纯引擎，跳过Qwen)")
print("  共 {} 个文件 | 测量 Docling+分类+合并 性能".format(len(pdfs)))
print("=" * 80)
print()

results = []
orch = PipelineOrchestrator()  # 单例复用，避免每次重载 Docling 模型

for i, pdf_path in enumerate(pdfs):
    name = pdf_path.stem
    size_mb = pdf_path.stat().st_size / (1024 * 1024)
    print("[{}/{}] {}  ({:.1f} MB)".format(i + 1, len(pdfs), name, size_mb))
    print("        Docling提取+分类+合并...", flush=True)

    output_path = str(OUTPUT_DIR / "{}.xlsx".format(name))
    start = time.time()
    try:
        result = orch.process(str(pdf_path), output_path=output_path)
        elapsed = time.time() - start

        high = sum(1 for r in result.confidence_reports.values() if not r.needs_qwen)
        low = result.total_pages - high
        avg_conf = (
            sum(r.score for r in result.confidence_reports.values()) / len(result.confidence_reports)
            if result.confidence_reports else 0
        )

        record = {
            "file": name,
            "size_mb": round(size_mb, 1),
            "elapsed_seconds": round(elapsed, 1),
            "total_pages": result.total_pages,
            "table_count": len(result.tables),
            "qwen_calls": result.qwen_calls,
            "high_confidence_pages": high,
            "low_confidence_pages": low,
            "avg_confidence": round(avg_conf, 4),
            "errors": result.errors,
            "output_path": result.output_path,
        }
        sp = elapsed / result.total_pages if result.total_pages else 0
        print("        ✓ {:.0f}s | {}页({:.1f}s/页) | {}表 | 高置信:{} | 置信度:{:.1%}".format(
            elapsed, result.total_pages, sp, len(result.tables), high, avg_conf
        ), flush=True)
        if result.errors:
            for e in result.errors[:3]:
                print("        ⚠ {}".format(e)[:120], flush=True)
    except Exception as e:
        elapsed = time.time() - start
        record = {
            "file": name, "size_mb": round(size_mb, 1),
            "elapsed_seconds": round(elapsed, 1),
            "error": str(e), "traceback": traceback.format_exc()[-500:],
        }
        print("        ✗ {:.0f}s | {}".format(elapsed, e), flush=True)
    results.append(record)
    print()

# 汇总
print("=" * 80)
print("  测 试 汇 总")
print("=" * 80)

success = [r for r in results if "error" not in r]
failed = [r for r in results if "error" in r]

total_time = sum(r["elapsed_seconds"] for r in results)
total_pages = sum(r.get("total_pages", 0) for r in success)
total_tables = sum(r.get("table_count", 0) for r in success)
total_qwen = sum(r.get("qwen_calls", 0) for r in success)

print("  成功: {} | 失败: {} | 总耗时: {:.0f}s ({:.0f}分)".format(
    len(success), len(failed), total_time, total_time/60))
print("  总页: {} | 总表: {} | 低置信度页面(需Qwen): {}".format(
    total_pages, total_tables, sum(r.get("low_confidence_pages", 0) for r in success)))
print()

if success:
    print("  {:<50} {:>4} {:>3} {:>7} {:>6} {:>7}".format(
        "文件", "页", "表", "耗时", "秒/页", "置信度"))
    print("  " + "-" * 82)
    for r in sorted(success, key=lambda x: x["elapsed_seconds"], reverse=True):
        short = r["file"].replace("_202", " ").replace("_Annual_Report", "").replace("_Financial_Statements", "")[:48]
        sp = r["elapsed_seconds"] / r["total_pages"] if r["total_pages"] > 0 else 0
        print("  {:<50} {:>4} {:>3} {:>6.0f}s {:>5.1f}s {:>6.1%}".format(
            short, r["total_pages"], r["table_count"],
            r["elapsed_seconds"], sp, r["avg_confidence"]))

    print()
    print("  📊 对比上次 (优化前):")
    print("     上次 BH 150页/3h34m/85s每页  →  期望大幅提升")
    print("     上次 置信度 90.7% / Qwen调用58次  →  期望提升至93-95%")

for r in failed:
    print("  ✗ {}: {}".format(r["file"], r.get("error", "")[:100]))

report_path = OUTPUT_DIR / "test_report.json"
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print("\n详细报告: {}".format(report_path))
print("Excel结果: {}".format(OUTPUT_DIR))
