"""SQLite database for users, subscriptions, and usage tracking."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path("data/auth.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL DEFAULT '',
            name          TEXT NOT NULL DEFAULT '',
            tier          TEXT NOT NULL DEFAULT 'free',       -- free | pro | enterprise
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            tier        TEXT NOT NULL,                         -- pro | enterprise
            started_at  TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at  TEXT,                                  -- NULL = never
            active      INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS usage_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            action      TEXT NOT NULL,                         -- upload | docling | qwen | download
            file_name   TEXT DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS verification_tokens (
            token       TEXT PRIMARY KEY,
            email       TEXT NOT NULL,
            name        TEXT NOT NULL DEFAULT '',
            used        INTEGER NOT NULL DEFAULT 0,
            expires_at  TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS guest_uploads (
            ip_address  TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_usage_user_date ON usage_logs(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id, active);
        CREATE INDEX IF NOT EXISTS idx_vt_email ON verification_tokens(email, expires_at);
        CREATE INDEX IF NOT EXISTS idx_guest_ip ON guest_uploads(ip_address);
    """)
    conn.commit()


def get_user_by_email(email: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_user(email: str, password_hash: str = "", name: str = "") -> dict:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (email, password_hash, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (email.lower().strip(), password_hash, name.strip(), now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE id = last_insert_rowid()").fetchone()
    return dict(row)


def update_user_tier(user_id: int, tier: str) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE users SET tier = ?, updated_at = ? WHERE id = ?", (tier, now, user_id))
    conn.execute(
        "INSERT INTO subscriptions (user_id, tier, started_at) VALUES (?, ?, ?)",
        (user_id, tier, now),
    )
    conn.commit()


def log_usage(user_id: int, action: str, file_name: str = "") -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO usage_logs (user_id, action, file_name, created_at) VALUES (?, ?, ?, ?)",
        (user_id, action, file_name, now),
    )
    conn.commit()


def get_usage_count(user_id: int, action: str, since_days: int = 1) -> int:
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM usage_logs WHERE user_id = ? AND action = ? AND created_at >= datetime('now', ?)",
        (user_id, action, f"-{since_days} days"),
    ).fetchone()
    return row["cnt"] if row else 0


def get_lifetime_usage_count(user_id: int, action: str) -> int:
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM usage_logs WHERE user_id = ? AND action = ?",
        (user_id, action),
    ).fetchone()
    return row["cnt"] if row else 0


# ── Magic-link verification tokens ──────────────────────────────────

import secrets
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


def create_verification_token(email: str, name: str = "") -> str:
    """Generate a one-time use token valid for 15 minutes."""
    conn = _get_conn()
    token = secrets.token_urlsafe(32)
    expires = (_dt.now(_tz.utc) + _td(minutes=15)).isoformat()
    conn.execute(
        "INSERT INTO verification_tokens (token, email, name, expires_at) VALUES (?, ?, ?, ?)",
        (token, email.lower().strip(), name.strip(), expires),
    )
    conn.commit()
    return token


def consume_verification_token(token: str) -> dict | None:
    """Validate and consume a magic-link token. Returns {email, name} or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT email, name, used, expires_at FROM verification_tokens WHERE token = ?",
        (token,),
    ).fetchone()
    if not row:
        return None
    if row["used"]:
        return None
    if _dt.now(_tz.utc).isoformat() > row["expires_at"]:
        conn.execute("DELETE FROM verification_tokens WHERE token = ?", (token,))
        conn.commit()
        return None
    conn.execute("UPDATE verification_tokens SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    return {"email": row["email"], "name": row["name"]}


# ── Guest upload tracking (IP-based) ─────────────────────────────────


def get_guest_upload_count(ip_address: str) -> int:
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM guest_uploads WHERE ip_address = ?",
        (ip_address,),
    ).fetchone()
    return row["cnt"] if row else 0


def record_guest_upload(ip_address: str) -> None:
    conn = _get_conn()
    conn.execute("INSERT INTO guest_uploads (ip_address) VALUES (?)", (ip_address,))
    conn.commit()


TIER_LIMITS = {
    "free": {
        "max_pdfs_lifetime": 2,
        "max_pdfs_per_day": 9999,
        "allow_docling": False,
        "allow_qwen": False,
        "allow_deepseek": False,
        "allow_download": True,
        "max_file_size_mb": 10,
    },
    "pro": {
        "max_pdfs_per_day": 200,
        "allow_docling": True,
        "allow_qwen": True,
        "allow_deepseek": True,
        "allow_download": True,
        "max_file_size_mb": 50,
    },
    "enterprise": {
        "max_pdfs_per_day": 9999,
        "allow_docling": True,
        "allow_qwen": True,
        "allow_deepseek": True,
        "allow_download": True,
        "max_file_size_mb": 200,
    },
}


def get_tier_limits(tier: str) -> dict:
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])
