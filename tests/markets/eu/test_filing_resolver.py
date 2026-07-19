from pathlib import Path

from backend.markets.eu.filing_resolver import ESEF_BENCHMARK_ISSUERS, EuFilingResolver


def test_benchmark_issuer_lookup_by_id():
    asml = EuFilingResolver.benchmark_issuer("ASML")
    assert asml is not None
    assert asml["lei"] == "724500Y6DUVHQD6OXN27"


def test_benchmark_issuer_lookup_by_lei():
    lvmh = EuFilingResolver.benchmark_issuer("IOG4E947OATN0KJYSD45")
    assert lvmh is not None
    assert lvmh["id"] == "LVMH"


def test_resolve_explicit_local_xhtml(tmp_path):
    xhtml = tmp_path / "demo.xhtml"
    xhtml.write_text("<html><body>Total assets</body></html>", encoding="utf-8")
    doc = EuFilingResolver().resolve(
        "724500Y6DUVHQD6OXN27",
        2025,
        explicit_path=str(xhtml),
        company_name="ASML Holding N.V.",
    )
    assert doc.local_path == Path(xhtml)
    assert doc.company_name == "ASML Holding N.V."


def test_benchmark_issuer_list_not_empty():
    assert len(ESEF_BENCHMARK_ISSUERS) >= 10


def test_pick_filing_for_asml():
    from backend.markets.eu.filing_resolver import EsmaFilingsClient

    filing = EsmaFilingsClient().pick_filing("724500Y6DUVHQD6OXN27", 2025)
    assert filing is not None
    period_end = filing["attributes"]["period_end"]
    assert str(period_end).startswith("2025-")
