"""从字符坐标重建无边框表格。"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd


def _group_chars_into_words(chars: list, x_gap: float = 20.0) -> list[tuple[float, str]]:
    if not chars:
        return []
    sorted_chars = sorted(chars, key=lambda c: c["x0"])
    words: list[tuple[float, str]] = []
    buf = ""
    word_x0 = sorted_chars[0]["x0"]
    prev_x1 = sorted_chars[0]["x0"]

    for ch in sorted_chars:
        if buf and ch["x0"] - prev_x1 > x_gap:
            words.append((word_x0, buf.strip()))
            buf = ch["text"]
            word_x0 = ch["x0"]
        else:
            if not buf:
                word_x0 = ch["x0"]
            buf += ch["text"]
        prev_x1 = ch["x1"]

    if buf.strip():
        words.append((word_x0, buf.strip()))
    return words


def _cluster_column_positions(all_x0: list[float], tolerance: float = 80.0) -> list[float]:
    if not all_x0:
        return []
    sorted_x = sorted(all_x0)
    clusters: list[list[float]] = [[sorted_x[0]]]
    for x in sorted_x[1:]:
        if x - clusters[-1][-1] <= tolerance:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [sum(c) / len(c) for c in clusters]


def _merge_close_columns(positions: list[float], min_width: float = 80.0) -> list[float]:
    """合并间距小于 min_width 的相邻列，返回合并后的位置列表。"""
    if len(positions) <= 1:
        return positions
    merged = [positions[0]]
    for pos in positions[1:]:
        if pos - merged[-1] < min_width:
            # merge: use midpoint
            merged[-1] = (merged[-1] + pos) / 2
        else:
            merged.append(pos)
    return merged


def _assign_to_columns(words: list[tuple[float, str]], col_positions: list[float]) -> list[str]:
    if not col_positions:
        return [w[1] for w in words]
    cells = [""] * len(col_positions)
    for x0, text in words:
        col_idx = min(range(len(col_positions)), key=lambda i: abs(col_positions[i] - x0))
        cells[col_idx] = f"{cells[col_idx]} {text}".strip() if cells[col_idx] else text
    return cells


def extract_text_grid_from_page(page, min_cols: int = 3, min_rows: int = 3) -> Optional[pd.DataFrame]:
    chars = page.chars
    if len(chars) < min_cols * min_rows:
        return None

    line_tol = 4.0
    lines: dict[float, list] = {}
    for ch in chars:
        key = round(ch["top"] / line_tol) * line_tol
        lines.setdefault(key, []).append(ch)

    row_data: list[tuple[float, list[tuple[float, str]]]] = []
    for top, line_chars in lines.items():
        words = _group_chars_into_words(line_chars)
        if len(words) >= min_cols:
            row_data.append((top, words))

    if len(row_data) < min_rows:
        return None

    row_data.sort(key=lambda x: x[0])
    all_x0 = [w[0] for _, words in row_data for w in words]
    col_positions = _cluster_column_positions(all_x0)

    # Merge columns that are too close together (avoid sentence splitting)
    col_positions = _merge_close_columns(col_positions, min_width=50.0)

    # Cap at a maximum of 15 columns — beyond that it's not a real table
    if len(col_positions) > 15:
        return None

    if len(col_positions) < min_cols:
        return None

    grid_rows = [_assign_to_columns(words, col_positions) for _, words in row_data]

    # Heuristic: reject grids where >60% of cells are empty (not real tables)
    total_cells = sum(len(r) for r in grid_rows)
    filled_cells = sum(sum(1 for c in r if c) for r in grid_rows)
    if total_cells == 0 or filled_cells / total_cells < 0.4:
        return None

    # Filter: rows must have at least min_cols non-empty cells
    col_counts = [sum(1 for c in r if c) for r in grid_rows]
    dominant = max(set(col_counts), key=col_counts.count)
    if dominant < min_cols:
        return None

    filtered = [r for r in grid_rows if sum(1 for c in r if c) >= min_cols - 1]
    if len(filtered) < min_rows:
        return None

    max_cols = max(len(r) for r in filtered)
    normalized = [r + [""] * (max_cols - len(r)) for r in filtered]
    header = normalized[0]
    body = normalized[1:]
    return pd.DataFrame(body, columns=header)
