from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api.auth import ApiKeyManager, RateLimiter


def test_api_key_optional_when_disabled(monkeypatch):
    monkeypatch.setattr("backend.api.auth.settings.require_api_key", False)
    mgr = ApiKeyManager()
    record = mgr.validate(None)
    assert record.key_id == "public"


def test_api_key_required_when_enabled(monkeypatch):
    monkeypatch.setattr("backend.api.auth.settings.require_api_key", True)
    monkeypatch.setattr("backend.api.auth.settings.api_keys", "demo:secret123")
    mgr = ApiKeyManager()
    with pytest.raises(HTTPException) as exc:
        mgr.validate(None)
    assert exc.value.status_code == 401


def test_api_key_validates_token(monkeypatch):
    monkeypatch.setattr("backend.api.auth.settings.require_api_key", True)
    monkeypatch.setattr("backend.api.auth.settings.api_keys", "demo:secret123")
    mgr = ApiKeyManager()
    record = mgr.validate("secret123")
    assert record.key_id == "demo"


def test_rate_limiter_blocks_burst():
    limiter = RateLimiter()
    for _ in range(3):
        limiter.check("test-key", 3)
    with pytest.raises(HTTPException) as exc:
        limiter.check("test-key", 3)
    assert exc.value.status_code == 429
