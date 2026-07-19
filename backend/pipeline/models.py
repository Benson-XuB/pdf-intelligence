from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ExtractedTable:
    page_num: int
    table_index: int
    dataframe: pd.DataFrame
    confidence: float
    has_merged_cells: bool


@dataclass
class PlumberTable:
    page_num: int
    table_index: int
    dataframe: pd.DataFrame


@dataclass
class FinalTable:
    source: str
    page_num: int
    table_index: int
    dataframe: pd.DataFrame
    confidence: float


@dataclass
class DoclingResult:
    tables: list[ExtractedTable] = field(default_factory=list)
    full_text: str = ""
    page_count: int = 0


@dataclass
class PlumberResult:
    tables: list[PlumberTable] = field(default_factory=list)
    chars_by_page: dict[int, list] = field(default_factory=dict)
