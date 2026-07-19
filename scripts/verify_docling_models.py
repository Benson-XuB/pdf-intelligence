#!/usr/bin/env python3
"""检查 Docling 模型是否下载完整。"""

from pathlib import Path

MODELS_DIR = Path.home() / ".cache/docling/models"

REQUIRED = {
    "版面模型": {
        "dir": MODELS_DIR / "docling-project--docling-layout-heron",
        "files": {
            "model.safetensors": 150_000_000,  # ~164 MB
            "config.json": 100,
            "preprocessor_config.json": 100,
        },
    },
    "表格模型 (accurate)": {
        "dir": MODELS_DIR / "docling-project--docling-models/model_artifacts/tableformer/accurate",
        "files": {
            "tableformer_accurate.safetensors": 200_000_000,  # ~213 MB
            "tm_config.json": 1000,
        },
    },
}


def check() -> bool:
    ok = True
    print(f"模型目录: {MODELS_DIR}\n")
    for name, spec in REQUIRED.items():
        print(f"## {name}")
        base = spec["dir"]
        if not base.exists():
            print(f"  ❌ 目录不存在: {base}")
            ok = False
            continue
        for fname, min_size in spec["files"].items():
            fpath = base / fname
            if not fpath.exists():
                print(f"  ❌ 缺少: {fname}")
                ok = False
            elif fpath.stat().st_size < min_size:
                mb = fpath.stat().st_size / 1024 / 1024
                need = min_size / 1024 / 1024
                print(f"  ⚠️  {fname}: {mb:.1f} MB（不完整，需要 ≥{need:.0f} MB）")
                ok = False
            else:
                mb = fpath.stat().st_size / 1024 / 1024
                print(f"  ✅ {fname}: {mb:.1f} MB")
        print()
    if ok:
        print("全部就绪，可以运行 Docling！")
    else:
        print("还有文件缺失或不完整，请按 README 手动下载。")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if check() else 1)
