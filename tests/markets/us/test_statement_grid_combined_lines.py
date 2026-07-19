"""Tests for combined equity+liabilities row handling."""

from __future__ import annotations

from backend.global_schema.registry import GLOBAL_FIELDS_V1
from backend.markets.us.statement_grid_extractor import (
    StatementGrid,
    _derive_total_liabilities,
    _row_label_score,
    find_row_values,
)


def _balance_grid() -> StatementGrid:
    return StatementGrid(
        statement_type="balance",
        period_ends=["2024-12-31", "2023-12-31"],
        rows=[
            ("Total assets", ["52566.5", "55576.8"]),
            ("Total equity", ["22021.9", "24185.0"]),
            ("Total equity and liabilities", ["52566.5", "55576.8"]),
        ],
    )


def test_combined_equity_liabilities_line_rejected_for_total_liabilities() -> None:
    field = next(f for f in GLOBAL_FIELDS_V1 if f.field_id == "total_liabilities")
    score = _row_label_score("Total equity and liabilities", field)
    assert score == 0.0


def test_find_row_values_skips_combined_line_for_total_liabilities() -> None:
    field = next(f for f in GLOBAL_FIELDS_V1 if f.field_id == "total_liabilities")
    label, values = find_row_values(_balance_grid(), field)
    assert label == ""
    assert values == {}


def test_french_combined_passif_capitaux_propres_rejected() -> None:
    field = next(f for f in GLOBAL_FIELDS_V1 if f.field_id == "total_liabilities")
    score = _row_label_score("Total du passif et des capitaux propres", field)
    assert score == 0.0


def test_derive_total_liabilities_from_assets_minus_equity() -> None:
    label, values = _derive_total_liabilities({"balance": _balance_grid()}, ["2024-12-31", "2023-12-31"])
    assert label == "derived: total assets − total equity"
    assert values["2024-12-31"] == 30544.6
    assert values["2023-12-31"] == 31391.8
