from backend.markets.us.statement_text import (
    cashflow_line_pattern,
    label_prefix_before_amounts,
    parse_eps_basic_amounts,
    parse_statement_amounts,
    score_capex_line,
    score_eps_basic_line,
    score_net_income_line,
    truncate_balance_line_chunk,
    _is_segment_sales_line,
)
import re


def test_parse_negative_operating_loss():
    chunk = "Operating income (loss) (11,678) 93 2,334 Gains on equity investments"
    assert parse_statement_amounts(chunk)[:3] == [-11678.0, 93.0, 2334.0]


def test_parse_parenthesized_cashflow_amounts_under_one_thousand():
    chunk = (
        "Net cash used in investing activities (580) (23,070) (689) "
        "Cash flows from financing activities: Proceeds from long-term borrowings 15,666 39,954"
    )
    assert parse_statement_amounts(chunk)[:3] == [-580.0, -23070.0, -689.0]


def test_score_cashflow_skips_section_header_with_colon():
    from backend.markets.us.statement_text import score_cashflow_line

    assert score_cashflow_line("Net cash provided by (used in) operating activities:", 0, 3) < 0


def test_score_cashflow_skips_continuing_operations_subtotal():
    from backend.markets.us.statement_text import score_cashflow_line

    assert score_cashflow_line(
        "Net cash provided by operating activities of continuing operations", 0, 3
    ) < 0
    assert score_cashflow_line("Net cash provided by operating activities", 0, 3) > 0


def test_score_net_income_prefers_attributable_to_common_shareholders():
    assert score_net_income_line(
        "Net earnings attributable to UnitedHealth Group common shareholders"
    ) > score_net_income_line("Net earnings")
    assert score_net_income_line("Net income (loss) attributable to Intel") > score_net_income_line(
        "Net income (loss)"
    )
    assert score_net_income_line("Net income") > score_net_income_line(
        "Net income attributable to common stock"
    )


def test_parse_sub_thousand_column_amount():
    assert parse_statement_amounts("Operating income 1,900 401 1,264") == [1900.0, 401.0, 1264.0]


def test_parse_dollar_amounts_under_one_thousand():
    assert parse_statement_amounts("Net income $ 1,641 $ 854 $ 1,320") == [1641.0, 854.0, 1320.0]


def test_truncate_balance_line_excludes_footnote_amounts():
    chunk = (
        "Total assets(a)$ 4,002,814 $ 3,875,393 Liabilities "
        "Deposits (included $33,768 and $78,384 at fair value)"
    )
    truncated = truncate_balance_line_chunk(chunk)
    assert parse_statement_amounts(truncated) == [4002814.0, 3875393.0]


def test_statement_unit_divisor_thousands():
    from backend.markets.us.statement_text import statement_unit_divisor

    head = "CONSOLIDATED STATEMENTS OF OPERATIONS (in thousands, except per share data)"
    assert statement_unit_divisor(head) == 1000.0
    assert statement_unit_divisor("CONSOLIDATED BALANCE SHEETS (in millions)") == 1.0
    apple = (
        "(In millions, except number of shares, which are reflected in thousands, "
        "and per-share amounts)"
    )
    assert statement_unit_divisor(apple) == 1.0


def test_parse_thousands_to_millions():
    text = "(in thousands) Revenues $39,000,966 $33,723,297 $31,615,550"
    assert parse_statement_amounts(text, unit_divisor=1000.0)[:3] == [
        39000.966,
        33723.297,
        31615.55,
    ]


def test_label_prefix_stops_at_first_amount_without_dollar():
    chunk = "Total net sales 391,035 383,285 Cost of sales: Products 185,233"
    assert label_prefix_before_amounts(chunk).strip().lower() == "total net sales"


def test_segment_sales_line_detection():
    assert _is_segment_sales_line("sales: products")
    assert not _is_segment_sales_line("total net sales")

    chunk = "Total liabilities $ 46,411 $ 41,566 Total stockholders equity"
    assert "Total liabilities" in truncate_balance_line_chunk(chunk)
    assert parse_statement_amounts(chunk) == [46411.0, 41566.0]


def test_cashflow_pattern_matches_hk_net_lines():
    from backend.markets.us.statement_text import cashflow_line_pattern

    assert re.search(
        cashflow_line_pattern("operating"),
        "Net cash flows generated from operating activities 57,146,784",
        re.I,
    )
    assert re.search(
        cashflow_line_pattern("investing"),
        "Net cash flows generated from/(used in) investing activities",
        re.I,
    )
    assert re.search(
        cashflow_line_pattern("financing"),
        "Net cash inflow/(outflow) from financing activities",
        re.I,
    )


def test_cashflow_pattern_used_by_financing():
    assert re.search(cashflow_line_pattern("financing"), "Net cash used by financing activities", re.I)
    assert re.search(cashflow_line_pattern("investing"), "Net Cash Used for Investing Activities", re.I)


def test_score_net_income_prefers_total_over_continuing():
    assert score_net_income_line("Net earnings") > score_net_income_line(
        "Net earnings from continuing operations"
    )


def test_score_eps_prefers_total_basic():
    assert score_eps_basic_line("Total net earnings per share - basic") > score_eps_basic_line(
        "Continuing operations - basic"
    )


def test_score_capex_prefers_ppe_line_over_investing_total():
    assert score_capex_line("Purchases of property and equipment") > score_capex_line(
        "Net cash used in investing activities"
    )
    assert score_capex_line("Net cash used in investing activities") < 0


def test_parse_eps_basic_hk_multiline_formats():
    from backend.markets.us.statement_text import parse_eps_basic_amounts, eps_basic_label_part

    tencent = (
        "Earnings per share for profit attributable to equity holders of the Company "
        "(in RMB per share) – basic 14(a) 12.186 19.757 – diluted 14(b) 11.887"
    )
    assert parse_eps_basic_amounts(tencent) == [12.186, 19.757]
    assert "basic" in eps_basic_label_part(tencent).lower()

    ccb = "Basic and diluted earnings per share (in RMB Yuan) 14 0.66 0.67"
    assert parse_eps_basic_amounts(ccb) == [0.66, 0.67]

    nio = "shareholders Basic and diluted (8.89) (12.44) (11.03)"
    assert parse_eps_basic_amounts(nio)[:2] == [-8.89, -12.44]
    assert score_eps_basic_line(eps_basic_label_part(nio)) >= 40_000

    assert score_eps_basic_line("net loss per share Basic and diluted 1,636,999,280") < 0


def test_parse_eps_basic_us_colon_and_em_dash_formats():
    nvda = "Net income per share: Basic $ 4.93 $ 2.97 $ 1.21 Diluted $ 4.90"
    assert parse_eps_basic_amounts(nvda) == [4.93, 2.97, 1.21]

    tsla = (
        "Net income per share of common stock attributable to common stockholders "
        "Basic $ 1.18 $ 2.23 $ 4.73 Diluted $ 1.08"
    )
    assert parse_eps_basic_amounts(tsla) == [1.18, 2.23, 4.73]

    unh = (
        "Earnings per share attributable to UnitedHealth Group common shareholders: "
        "Basic $ 13.28 $ 15.64 $ 24.12 Diluted $ 13.23"
    )
    assert parse_eps_basic_amounts(unh) == [13.28, 15.64, 24.12]

    intc = "Earnings (loss) per share attributable to Intel—basic $ (0.06) $ (4.38) $ 0.40"
    assert parse_eps_basic_amounts(intc) == [-0.06, -4.38, 0.4]

    jnj = (
        "Continuing operations - basic $11.13 5.84 5.26 Discontinued operations - basic — — 8.62 "
        "Total net earnings per share - basic $11.13 5.84 13.88"
    )
    assert parse_eps_basic_amounts(jnj) == [11.13, 5.84, 13.88]


def test_grid_revenue_prefers_company_total_over_segment():
    from backend.global_schema.registry import field_by_id
    from backend.markets.us.statement_grid_extractor import (
        StatementGrid,
        _row_label_score,
        find_row_values,
    )

    field = field_by_id()["revenue"]
    assert _row_label_score("Total revenues", field) > _row_label_score(
        "Total automotive revenues", field
    )

    grid = StatementGrid(
        statement_type="income",
        period_ends=["2025-12-31", "2024-12-31", "2023-12-31"],
        rows=[
            ("Total automotive revenues", ["69,526", "77,070", "82,419"]),
            ("Total revenues", ["94,827", "97,690", "96,773"]),
        ],
    )
    label, values = find_row_values(grid, field)
    assert label == "Total revenues"
    assert values["2025-12-31"] == 94827.0

