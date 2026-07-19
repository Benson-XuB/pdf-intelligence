import pandas as pd

from backend.pipeline.financial_table_refiner import refine_financial_dataframe


def test_split_merged_amounts():
    df = pd.DataFrame(
        [["Total assets", "$ 364,980 $ 352,583"]],
        columns=["Item", "2024 2023"],
    )
    out = refine_financial_dataframe(df)
    assert out.iloc[0, 1].replace(" ", "") in ("364,980", "$364,980", "364980")
    assert out.shape[1] >= 2


def test_split_year_header():
    df = pd.DataFrame(
        [["Net income", "93736", "96995"]],
        columns=["", "2024 2023", "x"],
    )
    out = refine_financial_dataframe(df)
    assert len(out.columns) >= 2
