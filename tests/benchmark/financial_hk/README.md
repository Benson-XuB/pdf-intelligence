# 港股 Benchmark 语料

10 家龙头（交叉上市 + 纯港股），PDF 由脚本自动下载。

## 下载语料

```bash
.venv/bin/python scripts/download_financial_hk_corpus.py
```

来源优先级：**HKEX 披露易直链** → **SEC Form 20-F** → **SEC ARS**（与 US 下载脚本同一套逻辑，无 ticker 特例）。

## 运行 benchmark

```bash
# 查看语料状态
.venv/bin/python scripts/run_hk_verified_benchmark.py --list

# 有 PDF 后跑 HK PDF × US XBRL 交叉校验
.venv/bin/python scripts/run_hk_verified_benchmark.py
```

交叉上市映射见 `backend/markets/hk/constants.py` 中的 `HK_US_CROSS_LIST`。

## 语料列表

| 代码 | 公司 | US 交叉校验 |
|------|------|-------------|
| 0700 | Tencent | TCEHY |
| 9988 | Alibaba | BABA |
| 3690 | Meituan | MPNGY |
| 9618 | JD.com | JD |
| 1810 | Xiaomi | XIACY |
| 9888 | Baidu | BIDU |
| 1024 | Kuaishou | KUASF |
| 1299 | AIA | AIA |
| 0941 | China Mobile | CHL |
| 0005 | HSBC | HSBC |
