"""表格后处理：修复合计行、数值校验、常见 OCR 错误。"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

TOTAL_LABELS = ("合计", "总计", "Total", "Sum", "小计")
GARBLED_TOTAL_PATTERN = re.compile(r"^[\.\·\…\-\—\_\s]+$")
TOTAL_KEYWORDS = ("合计", "总计", "total", "sum", "小计")


def refine_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    df = df.copy()
    df = df.fillna("")
    df = df.map(lambda x: str(x).strip())

    df = _drop_empty_rows(df)
    df = _merge_fragmented_columns(df)
    df = _fix_column_headers(df)
    df = _fix_total_row(df)
    df = _normalize_numeric_columns(df)
    df = _drop_empty_rows(df)
    return df


def _merge_fragmented_columns(df: pd.DataFrame, max_cols: int = 8) -> pd.DataFrame:
    """合并因文本策略过度拆分导致的碎片列。

    当列数超过 max_cols 时，检查相邻两列是否：
    - 都没有数字
    - 合并后第一行是连续短语（没有大量空列插入）
    满足则合并为一列。
    """
    if df is None or df.empty or len(df.columns) <= max_cols:
        return df

    ncols = len(df.columns)
    cols_to_merge: dict[int, int] = {}  # col_idx → merge_with (left index)
    i = 0
    while i < ncols - 1:
        # Check if columns i and i+1 are both text-only (no numbers in any row)
        has_num_i = any(_parse_number(str(df.iloc[r, i])) is not None for r in range(len(df)))
        has_num_j = any(_parse_number(str(df.iloc[r, i + 1])) is not None for r in range(len(df)))
        if has_num_i or has_num_j:
            i += 1
            continue
        # Merge: mark column i+1 to merge into i
        cols_to_merge[i + 1] = i
        i += 2  # skip the merged column

    if not cols_to_merge:
        return df

    # Build new column list
    new_cols = []
    skip_indices = set(cols_to_merge.keys())
    for ci in range(ncols):
        if ci in skip_indices:
            continue  # skip, will be merged into target
        new_cols.append(df.columns[ci])

    # Build new rows
    new_rows = []
    for _, row in df.iterrows():
        new_row: list[str] = []
        ci = 0
        while ci < ncols:
            if ci in skip_indices:
                ci += 1
                continue
            if ci in cols_to_merge.values():
                # This is a merge target — collect this column + all merged-right columns
                merged = str(row.iloc[ci]).strip()
                right = ci + 1
                while right in cols_to_merge and cols_to_merge[right] == ci:
                    right_val = str(row.iloc[right]).strip()
                    if right_val:
                        merged = f"{merged} {right_val}".strip() if merged else right_val
                    right += 1
                new_row.append(merged)
                ci = right
            else:
                new_row.append(str(row.iloc[ci]).strip())
                ci += 1
        new_rows.append(new_row)

    return pd.DataFrame(new_rows, columns=new_cols[:len(new_rows[0])] if new_rows else new_cols)


def _fix_column_headers(df: pd.DataFrame) -> pd.DataFrame:
    """修复/规范化表头。

    对于通用表格：修复 Unit Price+Amount 合并等 OCR 错误。
    对于财务报表：检测年份/货币/财务关键词，做轻量规范化而不破坏原有语义。
    """
    if df.empty:
        return df

    new_cols = []
    for col in df.columns:
        c = str(col).strip()
        c_lower = re.sub(r"\s+", "", c.lower())

        # 财务报表检测：包含四位数年份、货币符号、或财务关键词
        if _is_financial_header(c):
            new_cols.append(_normalize_financial_header(c))
            continue

        # 通用表格表头修复
        if re.search(r"unit.*pri.*ce", c_lower) or c_lower in ("unitprice", "unitpri"):
            new_cols.append("Unit Price")
        elif re.search(r"caemount|amount", c_lower):
            new_cols.append("Amount")
        elif c_lower in ("item", "name", "region", "department"):
            new_cols.append(c.title())
        elif c_lower in ("qty", "quantity"):
            new_cols.append("Qty")
        elif c_lower in ("budget", "actual", "variance", "score"):
            new_cols.append(c.title())
        elif re.match(r"^q[1-4]$", c_lower):
            new_cols.append(c.upper())
        else:
            new_cols.append(c)

    df.columns = new_cols
    return df


_FINANCIAL_KEYWORDS = (
    "revenue", "cost", "profit", "income", "earnings", "earn",
    "asset", "liabilit", "equity", "cash", "flow", "debt",
    "share", "dividend", "eps", "margin", "tax", "ebit",
    "operating", "gross", "net", "balance", "statement",
    "consolidated", "financial", "expense", "depreciation",
    "amortization", "goodwill", "inventory", "receivable",
    "payable", "accrued", "intangib", "capital", "invest",
    "return", "ratio", "percent", "growth", "year",
    "million", "billion", "thousand",
    # 中文
    "收入", "利润", "资产", "负债", "权益", "现金", "税",
    "营业", "净", "毛", "股息", "每股", "财务", "合计",
)


def _is_financial_header(header: str) -> bool:
    """检测表头是否属于财务报表。"""
    h = header.lower()
    # 包含四位数年份
    if re.search(r"(20|19)\d{2}", h):
        return True
    # 包含货币符号
    if re.search(r"[\$€£¥]|CHF|USD|EUR|GBP|CNY|HKD|RMB", h):
        return True
    # 包含财务报表关键词
    if any(kw in h for kw in _FINANCIAL_KEYWORDS):
        return True
    return False


def _normalize_financial_header(header: str) -> str:
    """财务报表表头轻量规范化。

    - 提取简洁年份标签：\"For the year ended December 31, 2024\" → \"2024\"
    - 保留原始关键词但清理多余空格
    """
    h = header.strip()
    # 如果整个表头就是一段日期描述，简化为年份
    years = re.findall(r"(20\d{2})", h)
    if len(years) == 1 and len(h) > 10:
        # 长日期描述 → 仅年份
        return years[0]
    # 保留原始表头，仅清理空格
    return re.sub(r"\s+", " ", h)


def _drop_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    mask = df.apply(lambda row: any(str(v).strip() for v in row), axis=1)
    return df[mask].reset_index(drop=True)


def _is_garbled_total_label(value: str) -> bool:
    v = str(value).strip()
    if not v:
        return True
    if any(kw in v for kw in TOTAL_KEYWORDS):
        return False
    if GARBLED_TOTAL_PATTERN.match(v):
        return True
    if len(v) <= 3 and not re.search(r"[a-zA-Z\u4e00-\u9fff]{2,}", v):
        return True
    return False


def _parse_number(val: str) -> Optional[float]:
    """将财报金额字符串转为浮点数，支持括号负数表示法。

    美股（US-GAAP）常用 (364,980) 表示 -364,980。
    """
    text = str(val).strip()
    if not text or text in ("-", "—", "–"):
        return None

    # 检测括号负数: "(364,980)" 或 "$ (364,980)" → -364980
    is_negative = False
    stripped = text.replace("¥", "").replace("$", "").replace("€", "").replace("CHF", "").replace("£", "").strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        is_negative = True
        stripped = stripped[1:-1]

    # 移除千分位逗号和空格
    stripped = stripped.replace(",", "").replace(" ", "")
    if not stripped or stripped in ("-", "—", "–"):
        return None

    try:
        val = float(stripped)
        return -val if is_negative else val
    except ValueError:
        return None


def _row_matches_column_sums(df: pd.DataFrame, row_idx: int) -> bool:
    if row_idx <= 0:
        return False
    matches = 0
    checked = 0
    for col_idx in range(len(df.columns)):
        last_val = _parse_number(df.iloc[row_idx, col_idx])
        if last_val is None:
            continue
        col_vals = [
            _parse_number(df.iloc[r, col_idx])
            for r in range(row_idx)
        ]
        col_vals = [v for v in col_vals if v is not None]
        if not col_vals:
            continue
        checked += 1
        if abs(sum(col_vals) - last_val) <= 0.02:
            matches += 1
    return checked > 0 and matches / checked >= 0.5


def _fix_total_row(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) < 2:
        return df

    last_idx = len(df) - 1
    first_cell = str(df.iloc[last_idx, 0]).strip()

    should_fix = _is_garbled_total_label(first_cell) or any(
        kw in first_cell for kw in ("total", "sum")
    )
    if should_fix and _row_matches_column_sums(df, last_idx):
        df.iloc[last_idx, 0] = "合计"
    elif _is_garbled_total_label(first_cell):
        # 末行首列乱码但数字列像合计行
        numeric_in_row = sum(
            1 for c in range(1, len(df.columns))
            if _parse_number(df.iloc[last_idx, c]) is not None
        )
        if numeric_in_row >= 1:
            df.iloc[last_idx, 0] = "合计"

    return df


def _normalize_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col_idx in range(len(df.columns)):
        for row_idx in range(len(df)):
            val = str(df.iloc[row_idx, col_idx]).strip()
            num = _parse_number(val)
            if num is not None and "." in val:
                if num == int(num):
                    df.iloc[row_idx, col_idx] = str(int(num)) if num == int(num) else f"{num:.2f}".rstrip("0").rstrip(".")
    return df
