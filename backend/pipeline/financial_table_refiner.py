"""财务报表专用后处理：拆分合并年份列、规范化金额单元格。"""

from __future__ import annotations

import re
from typing import List, Optional

import pandas as pd

# 宽松年份匹配：抓取四个连续数字（20xx / 19xx），即使被日期文字包裹也能提取
# 匹配 "September 28, 2024 September 30, 2023"、"截至12月31日 2024年 2023年"
YEAR_CAPTURE = re.compile(r"(20\d{2}|19\d{2})")

# 金额对匹配：支持多币种（$ € CHF £ ¥），小数点，括号负数和紧凑格式
# 每组匹配两个金额：有符号版 / 括号版 / 无符号紧凑版
AMOUNT_PAIR = re.compile(
    # 双货币符号: "€ 30.1 € 28.9", "$ 364,980 $ 352,583"
    r"([\$€£¥]|CHF)\s*\(?\s*([\d,]+\.?\d*)\s*\)?\s+([\$€£¥]|CHF)\s*\(?\s*([\d,]+\.?\d*)\s*\)?"
    r"|"
    # 单货币符号管两个数: "CHF 92,998 93,351"
    r"([\$€£¥]|CHF)\s*\(?\s*([\d,]+\.?\d*)\s*\)?\s+\(?\s*([\d,]+\.?\d*)\s*\)?"
    r"|"
    # 括号负数对: "(364,980) (352,583)"
    r"\(\s*([\d,]+\.?\d*)\s*\)\s+\(\s*([\d,]+\.?\d*)\s*\)"
    r"|"
    # 紧凑无符号: "364,980 352,583" 或 "30.1 28.9"
    r"((?:[\d,]{2,}\.\d+)|[\d,]{4,}(?:\.\d+)?)\s+((?:[\d,]{2,}\.\d+)|[\d,]{4,}(?:\.\d+)?)"
)


def refine_financial_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    df = df.copy()
    df = df.fillna("")
    df = df.map(lambda x: str(x).strip())

    df = _split_header_year_columns(df)
    df = _split_merged_amount_cells(df)
    df = _drop_empty_rows(df)
    return df.reset_index(drop=True)


def _split_header_year_columns(df: pd.DataFrame) -> pd.DataFrame:
    """表头中嵌入的年份信息拆分为独立列。

    支持格式：
      - \"2024 2023\"（简单双年份）
      - \"September 28, 2024 September 30, 2023\"（美式日期）
      - \"截至12月31日 2024年 2023年\"（中文日期）
      - \"For the year ended December 31, 2024 and 2023\"（英文长日期）
    从表头文本中抽前两个年份作为独立列。
    """
    new_cols: List[str] = []
    split_plan: List[Optional[tuple[str, str]]] = []

    for col in df.columns:
        text = str(col).strip()
        years = YEAR_CAPTURE.findall(text)
        if len(years) >= 2:
            split_plan.append((years[0], years[1]))
            new_cols.extend([years[0], years[1]])
        else:
            split_plan.append(None)
            new_cols.append(text or "col")

    if not any(s is not None for s in split_plan):
        return df

    rows_out: List[List[str]] = []
    for _, row in df.iterrows():
        expanded: List[str] = []
        for val, plan in zip(row, split_plan):
            sval = str(val).strip()
            if plan is None:
                expanded.append(sval)
                continue
            parts = _split_amount_pair(sval)
            if len(parts) == 2:
                expanded.extend(parts)
            else:
                expanded.extend([sval, ""])
        rows_out.append(expanded)

    return pd.DataFrame(rows_out, columns=new_cols[: len(rows_out[0])] if rows_out else new_cols)


def _split_merged_amount_cells(df: pd.DataFrame) -> pd.DataFrame:
    """数据行 '$ 364,980 $ 352,583' 或 '364,980 352,583' 拆到相邻列。"""
    if df.empty or len(df.columns) < 2:
        return df

    rows_out: List[List[str]] = []
    max_cols = len(df.columns)

    for _, row in df.iterrows():
        cells = list(row)
        expanded: List[str] = []
        for i, val in enumerate(cells):
            sval = str(val).strip()
            if i == 0:
                expanded.append(sval)
                continue
            parts = _split_amount_pair(sval)
            if len(parts) == 2 and i + 1 < len(cells) and not str(cells[i + 1]).strip():
                expanded.extend(parts)
            elif len(parts) == 2 and not expanded[-1].strip() if expanded else False:
                expanded.extend(parts)
            else:
                expanded.append(sval)

        while len(expanded) < max_cols:
            expanded.append("")
        rows_out.append(expanded[:max_cols])

    return pd.DataFrame(rows_out, columns=df.columns)


def _split_amount_pair(text: str) -> List[str]:
    """将一个包含两期金额的单元格拆为两个独立值。

    支持 $ € CHF £ ¥ 符号 + 括号负数和紧凑无符号格式。
    例: \"€ 30.1 € 28.9\" → [\"30.1\", \"28.9\"]
         \"CHF 92,998 93,351\" → [\"92,998\", \"93,351\"]
         \"(1,234) (567)\" → [\"-1,234\", \"-567\"]
         \"364,980 352,583\" → [\"364,980\", \"352,583\"]
    """
    text = text.strip()
    if not text:
        return []

    m = AMOUNT_PAIR.search(text)
    if m:
        g = m.groups()
        # Pattern 1: 双货币符号 (g[0]=sym1, g[1]=num1, g[2]=sym2, g[3]=num2)
        if g[0] is not None or g[1] is not None:
            return [g[1], g[3]]
        # Pattern 2: 单货币符号管两数 (g[4]=sym, g[5]=num1, g[6]=num2)
        if g[4] is not None or g[5] is not None:
            return [g[5], g[6]]
        # Pattern 3: 括号负数 (g[7]=num1, g[8]=num2)
        if g[7] is not None or g[8] is not None:
            return [f"-{g[7]}", f"-{g[8]}"]
        # Pattern 4: 紧凑无符号 (g[9]=num1, g[10]=num2)
        if g[9] is not None or g[10] is not None:
            return [g[9], g[10]]

    return [text] if text else []


def _drop_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    mask = df.apply(lambda row: any(str(v).strip() for v in row), axis=1)
    return df[mask]
