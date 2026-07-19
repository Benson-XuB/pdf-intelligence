from backend.markets.shared.protocols import MarketFinancialsService
from backend.markets.us.financials_service import UsFinancialsService


def test_us_service_implements_protocol():
    assert isinstance(UsFinancialsService(), MarketFinancialsService)
