"""Ruleset persistence helpers (SQLite).

Rulesets allow:
- storing multiple versions of ontology JSON
- switching the active ruleset via UI

For offline-first demo we support both `json_path` (file on disk) and `json_content` (stored in DB).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from srm.ontology.loader import OntologyLoadError, ontology_from_dict


def ensure_default_ruleset(conn: sqlite3.Connection, *, rules_path: Path) -> None:
    """Ensure there is an active ruleset record for the configured rules file."""

    # Make rules path robust for server runs where CWD may differ.
    # If `rules_path` is relative and not found, try resolving from project root (repo root).
    if not rules_path.exists() and not rules_path.is_absolute():
        project_root = Path(__file__).resolve().parents[2]
        candidate = (project_root / rules_path).resolve()
        if candidate.exists():
            rules_path = candidate

    if rules_path.exists():
        rules_path = rules_path.resolve()

    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT id FROM rulesets WHERE is_active = 1 LIMIT 1").fetchone()
    if row is not None:
        return

    # Create active ruleset from file.
    version = "unknown"
    content: str | None = None
    if rules_path.exists():
        content = rules_path.read_text(encoding="utf-8")
        try:
            raw = json.loads(content)
            version = str(raw.get("version", "unknown"))
        except Exception:
            version = "invalid-json"

    conn.execute(
        """
        INSERT INTO rulesets(name, version, is_active, json_path, json_content, created_at, created_by)
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            "Default ruleset",
            version,
            1,
            str(rules_path),
            content,
            now,
            "system",
        ),
    )
    conn.commit()


def get_active_ruleset(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, name, version, json_path, json_content, created_at, created_by FROM rulesets WHERE is_active = 1 LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def resolve_rules_path(conn: sqlite3.Connection, *, fallback_path: Path) -> Path:
    """Return a filesystem path to active rules JSON.

    If active ruleset is stored as `json_content`, we materialize it into `outputs/web_artifacts/rulesets/<id>.json`
    near the database (same parent dir as DB), so it works offline and is debuggable.
    """

    rs = get_active_ruleset(conn)
    if not rs:
        return fallback_path

    if rs.get("json_path"):
        p = Path(str(rs["json_path"]))
        if p.exists():
            return p

    content = rs.get("json_content")
    if not content:
        return fallback_path

    # Materialize next to DB for simplicity.
    db_path_row = conn.execute("PRAGMA database_list").fetchone()
    db_file = Path(str(db_path_row["file"])) if db_path_row and db_path_row["file"] else Path(".")
    out_dir = db_file.parent / "web_artifacts" / "rulesets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ruleset_{rs['id']}.json"
    out_path.write_text(str(content), encoding="utf-8")
    return out_path


def validate_rules_json(raw_text: str) -> tuple[bool, str]:
    """Validate JSON rules text using ontology parser, return (ok, message)."""

    try:
        raw = json.loads(raw_text)
    except Exception as e:
        return False, f"Неверный JSON: {e}"

    if not isinstance(raw, dict):
        return False, "Корень онтологии должен быть объектом (JSON object)."

    try:
        ontology_from_dict(raw)
    except OntologyLoadError as e:
        return False, f"Ошибка валидации правил: {e}"

    return True, "OK"
