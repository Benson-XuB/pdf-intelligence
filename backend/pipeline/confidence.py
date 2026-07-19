import re
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from backend.config import settings
from backend.pipeline.classifier import PageProfile
from backend.pipeline.models import ExtractedTable, PlumberTable


@dataclass
class ConfidenceReport:
    score: float
    needs_qwen: bool
    reasons: list[str]
    breakdown: dict[str, float]


def score_page(
    docling_tables: list[ExtractedTable],
    plumber_tables: list[PlumberTable],
    page_profile: PageProfile,
    confidence_threshold: Optional[float] = None,
) -> ConfidenceReport:
    if confidence_threshold is None:
        confidence_threshold = settings.confidence_threshold
    reasons: list[str] = []
    scores: dict[str, float] = {}

    scores["table_structure"] = _table_structure_score(docling_tables)
    scores["cross_engine"] = _cross_engine_agreement(
        docling_tables, plumber_tables, has_tables=page_profile.has_tables
    )
    if scores["cross_engine"] < 0.55:
        reasons.append("Cross-engine agreement too low")

    scores["numeric"] = _numeric_consistency(docling_tables)
    if scores["numeric"] < 0.7:
        reasons.append("Subtotal/numeric consistency check failed")

    scores["ocr"] = 1.0 if page_profile.page_type.value != "scanned" else 0.6
    if page_profile.page_type.value == "scanned":
        reasons.append("Scanned page — OCR quality unverified")

    scores["layout"] = min(0.95, 0.5 + page_profile.char_count / 200.0)
    if page_profile.char_count <= 50:
        reasons.append("Page has very little text")

    weights = {
        "table_structure": 0.25,
        "cross_engine": 0.25,
        "numeric": 0.20,
        "ocr": 0.15,
        "layout": 0.15,
    }
    total = sum(scores[k] * weights[k] for k in weights)

    has_merged_low_structure = any(
        t.has_merged_cells and scores["table_structure"] < 0.7 for t in docling_tables
    )
    if has_merged_low_structure:
        reasons.append("Merged cell structure may be incomplete")

    no_tables_extracted = not docling_tables and not plumber_tables
    if page_profile.page_type.value == "scanned" and no_tables_extracted:
        reasons.append("Scanned page — no tables detected")
        needs_qwen = True
    else:
        needs_qwen = (
            total < confidence_threshold
            or scores["cross_engine"] < 0.55
            or has_merged_low_structure
            or (page_profile.page_type.value == "scanned" and total < 0.9)
        )

    return ConfidenceReport(
        score=round(total, 3),
        needs_qwen=needs_qwen,
        reasons=reasons,
        breakdown=scores,
    )


def _normalize(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return (
        str(val).strip()
        .replace(",", "")
        .replace(" ", "")
        .replace("\u2212", "-")  # Unicode 减号 → ASCII
        .replace("¥", "")
        .replace("$", "")
    )


def _normalize_col(col: str) -> str:
    """列名归一化，用于跨引擎表头匹配。"""
    return re.sub(r"\s+", "", str(col).strip().lower())


def _align_and_compare(d_df: pd.DataFrame, p_df: pd.DataFrame) -> float:
    """基于列头对齐后比较两个表格的数值集合相似度（Jaccard）。

    不再按位置逐行对比（两引擎行数往往不同会丢分），
    而是把每个公共列的数值提取为集合，计算交集/并集比例。
    返回 0.0~1.0，1.0 表示两引擎提取出的数值完全一致。
    """
    if d_df.empty or p_df.empty:
        return 0.0

    # --- 1. 列头匹配 ---
    d_cols = {_normalize_col(c): c for c in d_df.columns}
    p_cols = {_normalize_col(c): c for c in p_df.columns}
    common_keys = set(d_cols.keys()) & set(p_cols.keys())

    if not common_keys:
        # 表头完全无法匹配 → 回退到形状+数值集合相似度
        return _shape_value_similarity(d_df, p_df)

    # --- 2. 对每个公共列，用 Jaccard 相似度比较数值集合 ---
    # 不再按位置逐行对比（双引擎行数往往不一致），
    # 而是把数值提取为集合，计算交集/并集比例
    jaccard_scores: list[float] = []
    for ck in common_keys:
        d_col_name = d_cols[ck]
        p_col_name = p_cols[ck]
        d_vals = d_df[d_col_name].astype(str).apply(_normalize)
        p_vals = p_df[p_col_name].astype(str).apply(_normalize)

        d_set = {v for v in d_vals.tolist() if v and v not in ("-", "—", "")}
        p_set = {v for v in p_vals.tolist() if v and v not in ("-", "—", "")}

        if not d_set and not p_set:
            jaccard_scores.append(1.0)
        else:
            union = d_set | p_set
            intersection = d_set & p_set
            jaccard_scores.append(len(intersection) / len(union) if union else 1.0)

    if not jaccard_scores:
        return 0.3

    return float(np.mean(jaccard_scores))


def _shape_value_similarity(d_df: pd.DataFrame, p_df: pd.DataFrame) -> float:
    """回退方案：形状相似度 + 数值集合重叠度。"""
    # 形状相似度
    dr, dc = d_df.shape
    pr, pc = p_df.shape
    row_sim = min(dr, pr) / max(dr, pr) if max(dr, pr) > 0 else 0
    col_sim = min(dc, pc) / max(dc, pc) if max(dc, pc) > 0 else 0
    shape_score = (row_sim + col_sim) / 2

    # 数值集合重叠（把所有数值提取出来做集合比较）
    d_nums = set()
    for v in d_df.values.flatten():
        n = _normalize(str(v))
        if n and n not in ("-", "—", ""):
            try:
                float(n)
                d_nums.add(n)
            except ValueError:
                pass
    p_nums = set()
    for v in p_df.values.flatten():
        n = _normalize(str(v))
        if n and n not in ("-", "—", ""):
            try:
                float(n)
                p_nums.add(n)
            except ValueError:
                pass

    if d_nums and p_nums:
        overlap = len(d_nums & p_nums) / max(len(d_nums | p_nums), 1)
    else:
        overlap = 0.0

    return shape_score * 0.4 + overlap * 0.6


def _cross_engine_agreement(
    docling_tables: list[ExtractedTable],
    plumber_tables: list[PlumberTable],
    has_tables: Optional[bool] = None,
) -> float:
    if not docling_tables and not plumber_tables:
        return 1.0
    if not docling_tables or not plumber_tables:
        # 单引擎模式：
        # - 若分类器判定本页确有表格 → 0.70（引擎已正确检测，给合理分）
        # - 若无信号 → 0.55（中立，可能是假阳性）
        return 0.70 if has_tables else 0.55

    # 为每个 docling 表找最佳匹配的 plumber 表，基于列头对齐后比较
    pair_scores: list[float] = []
    used_plumber: set[int] = set()

    for dt in docling_tables:
        best_score = 0.0
        best_idx = -1
        for pi, pt in enumerate(plumber_tables):
            if dt.page_num != pt.page_num:
                continue
            if pi in used_plumber:
                continue
            s = _align_and_compare(dt.dataframe, pt.dataframe)
            if s > best_score:
                best_score = s
                best_idx = pi
        if best_idx >= 0:
            used_plumber.add(best_idx)
        pair_scores.append(best_score)

    if not pair_scores:
        return 0.5  # 同页无配对表，中等惩罚

    return float(np.mean(pair_scores))


def _looks_like_financial_report(df: pd.DataFrame) -> bool:
    """检测表格是否有财报特征（含多年列 / 币种符号）。"""
    header_text = " ".join(str(c) for c in df.columns[:20]).lower()
    cols = [str(c) for c in df.columns[:20]]
    # 连续两年出现在列名中
    years = [int(m) for c in cols for m in re.findall(r"\b(20\d{2}|19\d{2})\b", c)]
    year_count = len(set(years))
    has_currency = any(sym in header_text for sym in ("$", "€", "£", "¥", "chf"))
    return year_count >= 2 or has_currency


def _table_structure_score(tables: list[ExtractedTable]) -> float:
    """评估表格结构质量。

    财务表常见的多层表头会导致前 3-5 行有大量空值，这是正常格式而非错误。
    对表头行的空值惩罚权重降低 50%，脚注行降低 30%。
    若检测到财报特征（多列年份 / 币种符号），表头区扩展到 5 行。
    """
    if not tables:
        return 1.0
    scores = []
    for t in tables:
        df = t.dataframe

        # 检测是否为年报表格（列名含连续年份或币种符号）
        _is_report = _looks_like_financial_report(df)

        header_rows = min(5 if _is_report else 3, max(1, df.shape[0] - 1))
        footer_rows = min(2, max(0, df.shape[0] - header_rows))
        data_rows = max(0, df.shape[0] - header_rows - footer_rows)

        # 分别计算各区域的空值率（用各自区域的实际 cell 数）
        header_empty = df.iloc[:header_rows, :].isnull().sum().sum() / max(header_rows * df.shape[1], 1)
        data_empty = 0.0
        if data_rows > 0:
            data_slice = df.iloc[header_rows:header_rows + data_rows, :]
            data_empty = data_slice.isnull().sum().sum() / max(data_slice.size, 1)
        footer_empty = 0.0
        if footer_rows > 0:
            footer_slice = df.iloc[-footer_rows:, :]
            footer_empty = footer_slice.isnull().sum().sum() / max(footer_slice.size, 1)

        # 表头和脚注的空值权重降低（正常格式），数据行空值权重正常
        total_weight = 0.5 + 1.0 + (0.7 if footer_rows > 0 else 0)
        if total_weight == 0:
            weighted_empty = 0.0
        else:
            weighted_empty = (header_empty * 0.5 + data_empty * 1.0 + footer_empty * 0.7) / total_weight

        scores.append(1.0 - min(weighted_empty * 2, 0.5))
    return float(np.mean(scores))


def _numeric_consistency(tables: list[ExtractedTable]) -> float:
    """校验合计/子合计行的数值合理性。

    扫描全表所有行（不仅末3行），在首列含合计关键词的行上：
    若该行某列数值为 0 / 空，但同列上方存在非零数值 → 判定为提取残缺。
    不再检查 sum 精确相等（财报中行间不可简单相加，且有分级合计导致重复计算）。
    """
    if not tables:
        return 1.0

    total_keywords = (
        "合计", "总计", "小计",
        "Total", "Sum", "Subtotal",
        "Total assets", "Total liabilities", "Total equity",
        "Total current assets", "Total current liabilities",
        "Net income", "Net sales", "Total revenue",
        "Total operating", "Gross profit",
        "總計", "合計", "小計",
        "Total", "Summe",
        "Total actif", "Total passif",
    )

    for t in tables:
        df = t.dataframe
        if len(df) < 2:
            continue

        for row_idx in range(len(df)):
            first_cell = str(df.iloc[row_idx, 0])
            if not any(kw.lower() in first_cell.lower() for kw in total_keywords):
                continue

            for col_idx in range(1, len(df.columns)):
                last_val = _parse_numeric_scalar(df.iloc[row_idx, col_idx])
                if last_val is None:
                    continue
                if abs(last_val) < 0.01:
                    # 合计行数值为零 → 检查同列上方是否有数据
                    col_vals = _parse_numeric_column(df.iloc[:row_idx, col_idx])
                    if any(abs(v) >= 0.01 for v in col_vals):
                        return 0.3

    return 1.0


def _parse_numeric_scalar(val) -> Optional[float]:
    """解析单个单元格为浮点数，支持括号负数（US-GAAP 惯例）。"""
    text = str(val).strip()
    if not text or text in ("-", "—", "–", ""):
        return None
    neg = False
    s = text.replace("¥", "").replace("$", "").replace("€", "").replace("CHF", "").replace("£", "").strip()
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace(",", "").replace(" ", "")
    if not s:
        return None
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _parse_numeric_column(col_series) -> list[float]:
    """将 DataFrame 列解析为数值列表，跳过非数值单元格。"""
    vals = []
    for v in col_series:
        n = _parse_numeric_scalar(v)
        if n is not None:
            vals.append(n)
    return vals
