from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from fastapi import Header, HTTPException, Request

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ApiKeyRecord:
    key_id: str
    label: str
    key: str
    rate_limit_per_minute: int = 60


@dataclass
class RequestLogEntry:
    timestamp: float
    method: str
    path: str
    key_id: str
    status_code: int
    duration_ms: float


class ApiKeyManager:
    def __init__(self) -> None:
        self._keys: Dict[str, ApiKeyRecord] = {}
        self._load_from_settings()

    def _load_from_settings(self) -> None:
        if not settings.api_keys:
            return
        for idx, raw in enumerate(settings.api_keys.split(",")):
            token = raw.strip()
            if not token:
                continue
            label = f"client-{idx + 1}"
            if ":" in token:
                label, token = token.split(":", 1)
                label = label.strip()
                token = token.strip()
            self._keys[token] = ApiKeyRecord(key_id=label, label=label, key=token)

    @property
    def auth_enabled(self) -> bool:
        return settings.require_api_key and bool(self._keys)

    def validate(self, api_key: Optional[str]) -> ApiKeyRecord:
        if not self.auth_enabled:
            return ApiKeyRecord(key_id="public", label="public", key="")
        if not api_key:
            raise HTTPException(401, "Missing API Key. Please provide X-API-Key in Header")
        record = self._keys.get(api_key)
        if not record:
            raise HTTPException(403, "Invalid API Key")
        return record


class RateLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, List[float]] = defaultdict(list)

    def check(self, key_id: str, limit_per_minute: int) -> None:
        if limit_per_minute <= 0:
            return
        now = time.monotonic()
        window_start = now - 60.0
        hits = [t for t in self._hits[key_id] if t >= window_start]
        if len(hits) >= limit_per_minute:
            raise HTTPException(429, "Too many requests. Please retry later.")
        hits.append(now)
        self._hits[key_id] = hits


class ApiUsageTracker:
    def __init__(self) -> None:
        self._logs: List[RequestLogEntry] = []
        self._counter: Dict[str, int] = defaultdict(int)

    def record(self, entry: RequestLogEntry) -> None:
        self._logs.append(entry)
        self._counter[entry.key_id] += 1
        if len(self._logs) > settings.api_log_max_entries:
            self._logs = self._logs[-settings.api_log_max_entries :]

    def summary(self) -> dict:
        return {
            "total_requests": len(self._logs),
            "by_key": dict(self._counter),
            "recent": [
                {
                    "path": e.path,
                    "key_id": e.key_id,
                    "status_code": e.status_code,
                    "duration_ms": round(e.duration_ms, 1),
                }
                for e in self._logs[-20:]
            ],
        }


api_key_manager = ApiKeyManager()
rate_limiter = RateLimiter()
usage_tracker = ApiUsageTracker()


def require_api_access(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> ApiKeyRecord:
    record = api_key_manager.validate(x_api_key)
    rate_limiter.check(record.key_id, settings.api_rate_limit_per_minute)
    request.state.api_key_id = record.key_id
    return record
