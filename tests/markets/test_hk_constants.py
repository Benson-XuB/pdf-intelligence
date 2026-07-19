from __future__ import annotations

from backend.markets.hk.constants import normalize_hk_code, us_cross_list_ticker


def test_normalize_hk_code():
    assert normalize_hk_code("700") == "0700"
    assert normalize_hk_code("0700.HK") == "0700"
    assert normalize_hk_code("9988") == "9988"


def test_us_cross_list_ticker():
    assert us_cross_list_ticker("0700") == "TCEHY"
    assert us_cross_list_ticker("9988") == "BABA"
    assert us_cross_list_ticker("9999") is None
