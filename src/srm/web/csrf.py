"""CSRF protection helpers for HTML forms (session-backed).

Implementation notes:
- For authenticated users we store `csrf_token` in `sessions` table (one token per session).
- For non-authenticated pages (login) we use an anonymous cookie `srm_csrf_anon` (double submit).

Templates embed token as hidden field:
    <input type="hidden" name="csrf_token" value="{{ request.state.csrf_token }}">
"""

from __future__ import annotations

import secrets
import sqlite3

from fastapi import Request


class CsrfError(ValueError):
    """Raised when CSRF token is missing or invalid."""


def ensure_csrf_for_request(conn: sqlite3.Connection, request: Request) -> tuple[str, str | None]:
    """Return csrf token for this request and optional anon-cookie value to set.

    If session cookie exists, token is loaded from DB (created if missing).
    Otherwise we use `srm_csrf_anon` cookie, generating a new value if absent.
    """

    session_token = (request.cookies.get("srm_session") or "").strip()
    if session_token:
        csrf = _ensure_session_csrf(conn, session_token=session_token)
        return csrf, None

    anon = (request.cookies.get("srm_csrf_anon") or "").strip()
    if anon:
        return anon, None
    anon = secrets.token_urlsafe(24)
    return anon, anon


def verify_csrf(request: Request, form_token: str | None) -> None:
    expected = getattr(request.state, "csrf_token", None)
    if expected is None or str(expected).strip() == "":
        # Common causes:
        # - cookies disabled in browser
        # - request is cross-site and cookies were not sent due to SameSite
        raise CsrfError("CSRF: отсутствует серверный токен (cookies не переданы).")
    if form_token is None or str(form_token).strip() == "":
        raise CsrfError("CSRF: токен не передан.")
    if str(expected) != str(form_token):
        # Provide more context for debugging local issues (multiple tabs, stale form).
        raise CsrfError("CSRF: неверный токен (возможна устаревшая форма или блокировка cookies).")


def _ensure_session_csrf(conn: sqlite3.Connection, *, session_token: str) -> str:
    try:
        row = conn.execute(
            "SELECT csrf_token FROM sessions WHERE token = ? LIMIT 1", (session_token,)
        ).fetchone()
    except sqlite3.OperationalError:
        # Older DB schema: no csrf_token column.
        return ""

    if row is None:
        return ""
    csrf = str(row["csrf_token"] or "").strip()
    if csrf:
        return csrf
    csrf = secrets.token_urlsafe(24)
    try:
        conn.execute(
            "UPDATE sessions SET csrf_token = ?, created_at = created_at WHERE token = ?",
            (csrf, session_token),
        )
        conn.commit()
    except Exception:
        # Best-effort; still return generated token for current request.
        pass
    return csrf
