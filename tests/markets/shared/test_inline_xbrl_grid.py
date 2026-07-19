"""Tests for shared inline-XBRL / ESEF table helpers."""

from __future__ import annotations

from backend.markets.shared.inline_xbrl_grid import (
    MarketContext,
    _extract_amount_tokens_from_row,
    score_html_table_text,
)


def test_french_ifrs_income_table_scores_above_threshold() -> None:
    text = (
        "Compte de résultat consolidé Ventes 84 683 79 120 "
        "Résultat net 15 174 12 890 en millions d'euros"
    )
    score = score_html_table_text(text, "income", MarketContext.ESEF)
    assert score >= 1_000.0


def test_french_ifrs_balance_table_scores_above_threshold() -> None:
    text = "Bilan consolidé Total de l'actif 125 000 Capitaux propres 45 000 Total des passifs 80 000"
    score = score_html_table_text(text, "balance", MarketContext.ESEF)
    assert score >= 1_000.0


def test_expand_packed_amount_cells_preserves_eu_thousands() -> None:
    from backend.markets.us.statement_grid_extractor import _expand_packed_amount_cells

    assert _expand_packed_amount_cells(["5\u202f862", "6\u202f602"]) == ["5\u202f862", "6\u202f602"]

