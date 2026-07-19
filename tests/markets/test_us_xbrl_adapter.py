from __future__ import annotations

from backend.global_schema.models import ValueScale
from backend.markets.us.xbrl_adapter import (
    UsSecXbrlAdapter,
    _dedupe_by_period,
    _filter_annual,
    _normalize_value,
    _pick_tag_entries,
)


def _sample_apple_facts() -> dict:
    return {
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "start": "2022-09-25",
                                "end": "2023-09-30",
                                "val": 383285000000,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-03",
                            },
                            {
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "val": 391035000000,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-11-01",
                            },
                        ]
                    },
                },
                "GrossProfit": {
                    "label": "Gross Profit",
                    "units": {
                        "USD": [
                            {
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "val": 180683000000,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-11-01",
                            }
                        ]
                    },
                },
                "Assets": {
                    "label": "Assets",
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 364980000000,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-11-01",
                            }
                        ]
                    },
                },
                "EarningsPerShareBasic": {
                    "label": "Basic EPS",
                    "units": {
                        "USD/shares": [
                            {
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "val": 6.11,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-11-01",
                            }
                        ]
                    },
                },
            }
        },
    }


class _FakeSecClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.cik = "0000320193"

    def resolve_cik(self, ticker: str) -> str:
        return self.cik

    def fetch_company_facts(self, ticker: str) -> dict:
        return self.payload


def test_normalize_value_to_millions():
    assert _normalize_value(391035000000, ValueScale.MILLIONS) == 391035.0
    assert _normalize_value(401000000, ValueScale.MILLIONS) == 401.0
    assert _normalize_value(694000000, ValueScale.MILLIONS) == 694.0
    assert _normalize_value(6.11, ValueScale.PER_SHARE) == 6.11


def test_filter_annual_duration_and_instant():
    revenue_entries = _sample_apple_facts()["facts"]["us-gaap"][
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    ]["units"]["USD"]
    annual = _filter_annual(revenue_entries, "revenue")
    assert len(annual) == 2

    assets = _sample_apple_facts()["facts"]["us-gaap"]["Assets"]["units"]["USD"]
    annual_assets = _filter_annual(assets, "total_assets")
    assert len(annual_assets) == 1
    assert "start" not in annual_assets[0]


def test_us_xbrl_adapter_maps_core_fields():
    adapter = UsSecXbrlAdapter(client=_FakeSecClient(_sample_apple_facts()))
    result = adapter.fetch("AAPL", periods=2)

    assert result.company_name == "Apple Inc."
    assert result.market == "US"
    assert "2024-09-28" in result.periods

    by_period = {}
    for v in result.values:
        by_period.setdefault(v.field_id, {})[v.period_end] = v

    assert by_period["revenue"]["2024-09-28"].value == 391035.0
    assert by_period["gross_profit"]["2024-09-28"].value == 180683.0
    assert by_period["total_assets"]["2024-09-28"].value == 364980.0
    assert by_period["eps_basic"]["2024-09-28"].value == 6.11
    assert (
        by_period["revenue"]["2024-09-28"].source_tag
        == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    )


def test_dedupe_by_period_keeps_latest_filing():
    entries = [
        {"end": "2024-09-28", "filed": "2024-11-01", "val": 1},
        {"end": "2024-09-28", "filed": "2025-10-31", "val": 2},
    ]
    deduped = _dedupe_by_period(entries)
    assert len(deduped) == 1
    assert deduped[0]["val"] == 2


def test_pick_tag_entries_prefers_narrow_cash_tag():
    gaap = {
        "CashAndCashEquivalentsAtCarryingValue": {
            "units": {
                "USD": [
                    {
                        "end": "2024-12-31",
                        "val": 23466000000,
                        "fy": 2024,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2025-02-05",
                    }
                ]
            }
        },
        "CashCashEquivalentsAndShortTermInvestments": {
            "units": {
                "USD": [
                    {
                        "end": "2024-12-31",
                        "val": 95657000000,
                        "fy": 2024,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2025-02-05",
                    }
                ]
            }
        },
    }
    picked = _pick_tag_entries(
        gaap,
        [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsAndShortTermInvestments",
        ],
        "cash",
        ValueScale.MILLIONS,
        1,
    )
    assert picked[0][0] == "CashAndCashEquivalentsAtCarryingValue"
    assert picked[0][1]["val"] == 23466000000


def test_pick_tag_entries_prefers_recent_capex_tag():
    gaap = {
        "PaymentsToAcquirePropertyPlantAndEquipment": {
            "units": {
                "USD": [
                    {
                        "start": "2016-01-01",
                        "end": "2016-12-31",
                        "val": 6737000000,
                        "fy": 2016,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2017-02-09",
                    }
                ]
            }
        },
        "PaymentsToAcquireProductiveAssets": {
            "units": {
                "USD": [
                    {
                        "start": "2024-01-01",
                        "end": "2024-12-31",
                        "val": 82999000000,
                        "fy": 2024,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2025-02-06",
                    }
                ]
            }
        },
    }
    picked = _pick_tag_entries(
        gaap,
        [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ],
        "capex",
        ValueScale.MILLIONS,
        1,
    )
    assert picked[0][0] == "PaymentsToAcquireProductiveAssets"
    assert picked[0][1]["val"] == 82999000000


def test_pick_tag_entries_prefers_profit_loss_when_net_income_stale():
    gaap = {
        "NetIncomeLoss": {
            "units": {
                "USD": [
                    {
                        "start": "2013-01-01",
                        "end": "2013-12-31",
                        "val": 3116000000,
                        "fy": 2013,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2014-02-14",
                    }
                ]
            }
        },
        "ProfitLoss": {
            "units": {
                "USD": [
                    {
                        "start": "2024-01-01",
                        "end": "2024-12-31",
                        "val": 12874000000,
                        "fy": 2024,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2025-02-12",
                    }
                ]
            }
        },
    }
    picked = _pick_tag_entries(
        gaap,
        ["NetIncomeLoss", "ProfitLoss"],
        "net_income",
        ValueScale.MILLIONS,
        1,
    )
    assert picked[0][0] == "ProfitLoss"
    assert picked[0][1]["val"] == 12874000000
