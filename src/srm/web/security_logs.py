"""Security logging to SQLite (`security_logs` table)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """Best-effort client IP extraction (supports reverse proxy)."""

    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return str(request.client.host)
    return ""


def log_security_event(
    conn: sqlite3.Connection,
    *,
    request: Request,
    username: str | None,
    action: str,
    risk_level: str,
    details: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    ip = get_client_ip(request)
    details_json = json.dumps(details or {}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO security_logs(ip, username, action, risk_level, details_json, created_at) VALUES(?,?,?,?,?,?)",
        (ip or None, (username or "").strip() or None, action, risk_level, details_json, now),
    )
    conn.commit()
