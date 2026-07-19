from backend.markets.us.period_parser import (
    align_periods_to_xbrl,
    is_opening_balance_period,
    parse_statement_periods,
    resolve_balance_periods,
    StatementPeriod,
)

SAMPLE_INCOME_HEAD = """
Apple Inc.
CONSOLIDATED STATEMENTS OF OPERATIONS
(In millions)
Years ended September 28, 2024 September 30, 2023 September 24, 2022
Total net sales 391,035 383,285 394,328
"""


def test_parse_statement_periods_from_headers():
    periods = parse_statement_periods(SAMPLE_INCOME_HEAD)
    assert [p.period_end for p in periods] == [
        "2024-09-28",
        "2023-09-30",
        "2022-09-24",
    ]


SAMPLE_AMZN_HEAD = """
AMAZON.COM, INC.
CONSOLIDATED STATEMENTS OF OPERATIONS
Year Ended December 31,
2022
2023
2024
Total net sales 513,983 574,785 637,959
"""


def test_parse_statement_periods_prefers_year_column_over_stale_footnote_dates():
    head = """
    CONSOLIDATED STATEMENTS OF INCOME
    Year Ended December 31,
    2022
    2023
    2024
    Revenues $ 282,836 $ 307,394 $ 350,018
    See Note — December 31, 2021 comparison
    """
    periods = parse_statement_periods(head, max_periods=3)
    assert [p.period_end for p in periods] == [
        "2022-12-31",
        "2023-12-31",
        "2024-12-31",
    ]


def test_parse_amazon_year_column_block():
    periods = parse_statement_periods(SAMPLE_AMZN_HEAD)
    assert [p.year for p in periods] == [2022, 2023, 2024]
    assert periods[-1].period_end == "2024-12-31"


def test_align_periods_to_xbrl_by_exact_end_date():
    pdf_periods = parse_statement_periods(SAMPLE_INCOME_HEAD)
    mapping = align_periods_to_xbrl(pdf_periods, ["2024-09-28", "2023-09-30"])
    assert mapping["2024-09-28"] == 0
    assert mapping["2023-09-30"] == 1


def test_is_opening_balance_period():
    assert is_opening_balance_period("2023-01-01") is True
    assert is_opening_balance_period("2024-12-31") is False


def test_resolve_balance_periods_uses_income_when_opening_column():
    balance = [
        StatementPeriod(period_end="2025-12-31", label="2025", year=2025),
        StatementPeriod(period_end="2023-01-01", label="2023", year=2023),
    ]
    income = [
        StatementPeriod(period_end="2025-12-31", label="2025", year=2025),
        StatementPeriod(period_end="2024-12-31", label="2024", year=2024),
        StatementPeriod(period_end="2023-12-31", label="2023", year=2023),
    ]
    resolved = resolve_balance_periods(balance, income, max_periods=2)
    assert [p.period_end for p in resolved] == ["2025-12-31", "2024-12-31"]


LI_INCOME_HEAD = """
CONSOLIDATED STATEMENTS OF COMPREHENSIVE INCOME
For the Year Ended December 31,
2023
2024
Total revenues
123,851,332
144,459,946
"""


def test_parse_statement_periods_ignores_opening_balance_in_mixed_header():
    periods = parse_statement_periods(
        "December 31, 2023\nJanuary 1, 2023\n" + LI_INCOME_HEAD
    )
    assert [p.period_end for p in periods] == ["2023-12-31", "2024-12-31"]
