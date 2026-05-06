from __future__ import annotations

from pathlib import Path

import pytest


def test_recalc_supplier_rating_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "web.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir = tmp_path / "uploads"
    rules_path = Path("examples/repair_rules_ontology.json").resolve()

    monkeypatch.setenv("SRM_DB_PATH", str(db_path))
    monkeypatch.setenv("SRM_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SRM_UPLOADS_DIR", str(uploads_dir))
    monkeypatch.setenv("SRM_RULES_PATH", str(rules_path))
    monkeypatch.setenv("SRM_DEFAULT_ANALYSIS_DATE", "2026-04-18")

    from srm.web.auth import ensure_admin_user
    from srm.web.db import connect, init_db
    from srm.web.rulesets import ensure_default_ruleset
    from srm.web.seed import seed_demo_data

    conn = connect(db_path)
    try:
        init_db(conn)
        ensure_admin_user(conn, app_env="local")
        ensure_default_ruleset(conn, rules_path=rules_path)
        seed_demo_data(conn)
    finally:
        conn.close()

    from srm.cli import main

    rc = main(["recalc-supplier-rating", "--analysis-date", "2026-04-18"])
    assert rc == 0

    conn2 = connect(db_path)
    try:
        row = conn2.execute("SELECT COUNT(1) AS c FROM supplier_rating_history").fetchone()
        assert int(row["c"] or 0) >= 1
        row2 = conn2.execute(
            "SELECT COUNT(1) AS c FROM suppliers WHERE rating_config IS NOT NULL"
        ).fetchone()
        assert int(row2["c"] or 0) >= 1
    finally:
        conn2.close()
