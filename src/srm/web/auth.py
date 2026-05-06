"""Authentication helpers for the web app (SQLite-backed sessions)."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from srm.web.security import hash_password, verify_password


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str
    role: str  # admin|manager|master|analyst


ALLOWED_ROLES: set[str] = {"admin", "manager", "master", "analyst"}


def ensure_admin_user(conn: sqlite3.Connection, *, app_env: str = "local") -> None:
    """Create demo users for local/dev; on production create them only for an empty DB."""

    env = (app_env or "").strip().lower() or "local"
    if env in {"production", "prod"}:
        row = conn.execute("SELECT COUNT(1) AS c FROM users").fetchone()
        if row is not None and int(row["c"] or 0) > 0:
            # Do not auto-create demo users on a non-empty production DB.
            return

    _ensure_user(conn, username="admin", password="admin123", role="admin")
    _ensure_user(conn, username="manager", password="manager123", role="manager")
    _ensure_user(conn, username="master", password="master123", role="master")
    _ensure_user(conn, username="analyst", password="analyst123", role="analyst")


def _ensure_user(conn: sqlite3.Connection, *, username: str, password: str, role: str) -> None:
    if role not in ALLOWED_ROLES:
        role = "analyst"
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row is not None:
        return
    create_user(conn, username=username, password=password, role=role)


def create_user(conn: sqlite3.Connection, *, username: str, password: str, role: str) -> User:
    now = datetime.now(timezone.utc).isoformat()
    pw = hash_password(password)
    cur = conn.execute(
        "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
        (username, pw, role, now),
    )
    conn.commit()
    return User(id=int(cur.lastrowid), username=username, role=role)


def authenticate(conn: sqlite3.Connection, *, username: str, password: str) -> User | None:
    row = conn.execute(
        "SELECT id, username, password_hash, role, locked_until FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None:
        return None
    locked_until = str(row["locked_until"] or "").strip() if "locked_until" in row.keys() else ""
    if locked_until:
        try:
            if datetime.fromisoformat(locked_until) > datetime.now(timezone.utc):
                return None
        except Exception:
            pass
    if not verify_password(password, str(row["password_hash"])):
        return None
    return User(id=int(row["id"]), username=str(row["username"]), role=str(row["role"]))


def record_failed_login(
    conn: sqlite3.Connection,
    *,
    username: str,
    max_failures: int = 5,
    lock_minutes: int = 15,
) -> None:
    """Increment failed login count and lock user if threshold exceeded."""

    now = datetime.now(timezone.utc).isoformat()
    try:
        row = conn.execute(
            "SELECT failed_login_count FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return
        n = int(row["failed_login_count"] or 0) + 1
        locked_until: str | None = None
        if n >= int(max_failures):
            locked_until = (
                datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)
            ).isoformat()
            n = 0  # reset counter after lock
        conn.execute(
            "UPDATE users SET failed_login_count = ?, locked_until = ?, last_failed_login_at = ? WHERE username = ?",
            (n, locked_until, now, username),
        )
        conn.commit()
    except sqlite3.OperationalError:
        # Older schema without columns.
        return


def reset_failed_login(conn: sqlite3.Connection, *, username: str) -> None:
    """Reset failed login counters for a successful login."""

    try:
        conn.execute(
            "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_failed_login_at = NULL WHERE username = ?",
            (username,),
        )
        conn.commit()
    except sqlite3.OperationalError:
        return


def is_user_locked(conn: sqlite3.Connection, *, username: str) -> tuple[bool, str | None]:
    """Return (locked, locked_until)."""

    try:
        row = conn.execute(
            "SELECT locked_until FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return False, None
        lu = str(row["locked_until"] or "").strip()
        if not lu:
            return False, None
        try:
            locked = datetime.fromisoformat(lu) > datetime.now(timezone.utc)
        except Exception:
            locked = False
        return locked, lu if locked else None
    except sqlite3.OperationalError:
        return False, None


def create_session(conn: sqlite3.Connection, *, user_id: int, session_days: int) -> str:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=session_days)
    try:
        conn.execute(
            "INSERT INTO sessions(token,user_id,created_at,expires_at,csrf_token) VALUES(?,?,?,?,?)",
            (token, user_id, now.isoformat(), expires.isoformat(), csrf_token),
        )
    except sqlite3.OperationalError:
        # Backward-compatible for older DBs without csrf_token column.
        conn.execute(
            "INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
            (token, user_id, now.isoformat(), expires.isoformat()),
        )
    conn.commit()
    return token


def delete_session(conn: sqlite3.Connection, *, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def get_user_by_session(conn: sqlite3.Connection, *, token: str) -> User | None:
    row = conn.execute(
        """
        SELECT u.id, u.username, u.role, s.expires_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ?
        """,
        (token,),
    ).fetchone()
    if row is None:
        return None
    expires = datetime.fromisoformat(str(row["expires_at"]))
    if expires < datetime.now(timezone.utc):
        delete_session(conn, token=token)
        return None
    return User(id=int(row["id"]), username=str(row["username"]), role=str(row["role"]))
