from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)


def test_v1_us_verify_aapl():
    res = client.get("/api/v1/markets/us/AAPL/verify?periods=3&export_excel=false")
    assert res.status_code == 200
    data = res.json()
    assert data["ticker"] == "AAPL"
    assert data["market"] == "US"
    assert data["verification_rate"] >= 0
    assert len(data["reconciliation"]) > 0


def test_v1_batch_verify_us():
    res = client.post(
        "/api/v1/batch/verify",
        json={
            "jobs": [
                {"market": "US", "ticker": "AAPL"},
                {"market": "US", "ticker": "MSFT"},
            ],
            "periods": 3,
            "export_excel": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success_count"] == 2
    assert len(data["items"]) == 2
    assert data["portfolio_excel_path"]


def test_v1_usage_endpoint():
    client.get("/api/v1/markets/us/AAPL/verify?export_excel=false")
    res = client.get("/api/v1/usage")
    assert res.status_code == 200
    assert res.json()["total_requests"] >= 1


def test_v1_eu_verify_upload_xhtml(tmp_path):
    xhtml = tmp_path / "demo.xhtml"
    xhtml.write_text(
        "<html><body><table><tr><td>Total assets</td><td>1000</td><td>900</td></tr></table></body></html>",
        encoding="utf-8",
    )
    with xhtml.open("rb") as fh:
        res = client.post(
            "/api/v1/markets/eu/724500Y6DUVHQD6OXN27/verify?fiscal_year=2025&export_excel=false&export_formula_excel=false",
            files={"file": ("demo.xhtml", fh, "application/xhtml+xml")},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["market"] == "EU"
    assert data["cik"] == "724500Y6DUVHQD6OXN27"
    assert "reconciliation" in data
