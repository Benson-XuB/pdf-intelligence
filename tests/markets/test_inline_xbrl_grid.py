import pandas as pd
from bs4 import BeautifulSoup

from backend.markets.shared.inline_xbrl_grid import (
    MarketContext,
    compact_html_statement_dataframe,
    html_table_to_dataframe,
    score_html_table_text,
    statement_table_signals,
)


def test_ifrs_market_has_balance_signals():
    signals = statement_table_signals(MarketContext.IFRS)
    assert "balance" in signals
    assert any("total equity" in p for p in signals["balance"])


def test_compact_html_statement_dataframe_period_headers():
    raw = pd.DataFrame(
        [
            ["", "Year Ended Dec 31, 2024", "Year Ended Dec 31, 2023"],
            ["Total assets", "$", "1,000", "", "$", "900"],
        ]
    )
    compact = compact_html_statement_dataframe(raw)
    assert compact is not None
    assert len(compact.columns) >= 3


def test_score_html_table_text_ifrs():
    text = "Consolidated statement of financial position Total assets Total equity"
    score = score_html_table_text(text, "balance", MarketContext.ESEF)
    assert score >= 1000.0


def test_html_table_to_dataframe_min_rows():
    html = """
    <table>
      <tr><td>Revenue</td><td>100</td><td>90</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert html_table_to_dataframe(soup.find("table")) is None
