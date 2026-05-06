from __future__ import annotations

from pathlib import Path

import pytest


def test_check_deploy_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "web.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir = tmp_path / "uploads"

    monkeypatch.setenv("SRM_DB_PATH", str(db_path))
    monkeypatch.setenv("SRM_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SRM_UPLOADS_DIR", str(uploads_dir))
    monkeypatch.setenv("SRM_RULES_PATH", str(Path("examples/repair_rules_ontology.json").resolve()))
    monkeypatch.setenv("SRM_DEFAULT_ANALYSIS_DATE", "2026-04-18")

    from srm.cli import main

    rc = main(["check-deploy"])
    assert rc == 0
