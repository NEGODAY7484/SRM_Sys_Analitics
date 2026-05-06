"""Deployment diagnostics (offline-friendly).

Used by:
- API `/ready`
- CLI `check-deploy`
"""

from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ReadyCheckResult:
    ok: bool
    details: dict[str, object]


def can_write_dir(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)  # type: ignore[arg-type]
        return True, "ok"
    except Exception as e:
        return False, str(e)


def check_db(conn: sqlite3.Connection) -> tuple[bool, str]:
    try:
        conn.execute("SELECT 1").fetchone()
        return True, "ok"
    except Exception as e:
        return False, str(e)


def check_ruleset(conn: sqlite3.Connection) -> tuple[bool, str]:
    try:
        row = conn.execute(
            "SELECT id, name, version FROM rulesets WHERE is_active = 1 LIMIT 1"
        ).fetchone()
        if row is None:
            return False, "Нет активного набора правил (ruleset)."
        return True, f"{row['name']} ({row['version']})"
    except Exception as e:
        return False, str(e)


def ready_check(
    *,
    conn: sqlite3.Connection,
    uploads_dir: Path,
    artifacts_dir: Path,
) -> ReadyCheckResult:
    ok_db, msg_db = check_db(conn)
    ok_up, msg_up = can_write_dir(uploads_dir)
    ok_art, msg_art = can_write_dir(artifacts_dir)
    ok_rules, msg_rules = check_ruleset(conn)
    ok = all([ok_db, ok_up, ok_art, ok_rules])
    return ReadyCheckResult(
        ok=ok,
        details={
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "db": {"ok": ok_db, "message": msg_db},
            "uploads": {"ok": ok_up, "path": str(uploads_dir), "message": msg_up},
            "artifacts": {"ok": ok_art, "path": str(artifacts_dir), "message": msg_art},
            "ruleset": {"ok": ok_rules, "message": msg_rules},
            "env": {"APP_ENV": os.getenv("APP_ENV", ""), "DEBUG": os.getenv("DEBUG", "")},
        },
    )
