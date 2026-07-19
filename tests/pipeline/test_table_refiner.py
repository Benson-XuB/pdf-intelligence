import pandas as pd

from backend.pipeline.table_refiner import refine_dataframe


def test_fix_garbled_total_label():
    df = pd.DataFrame(
        {
            "Region": ["North", "South", "··"],
            "Q1": ["100", "80", "180"],
        }
    )
    refined = refine_dataframe(df)
    assert refined.iloc[-1, 0] == "合计"


def test_fix_total_row_simple_two_column():
    df = pd.DataFrame({"Name": ["Alice", "Bob", "··"], "Score": ["95", "87", "182"]})
    refined = refine_dataframe(df)
    assert refined.iloc[-1, 0] == "合计"
    assert refined.iloc[-1, 1] == "182"
