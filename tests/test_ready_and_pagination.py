from __future__ import annotations

from importlib import reload
from pathlib import Path

import pytest


def test_ready_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "web.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir = tmp_path / "uploads"
    rules_path = Path("examples/repair_rules_ontology.json").resolve()

    monkeypatch.setenv("SRM_DB_PATH", str(db_path))
    monkeypatch.setenv("SRM_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SRM_UPLOADS_DIR", str(uploads_dir))
    monkeypatch.setenv("SRM_RULES_PATH", str(rules_path))
    monkeypatch.setenv("SRM_DEFAULT_ANALYSIS_DATE", "2026-04-18")

    import srm.api.app as appmod

    appmod = reload(appmod)

    from fastapi.testclient import TestClient

    with TestClient(appmod.app) as client:
        r = client.get("/ready")
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("status") == "ok"
        details = payload.get("details") or {}
        assert (details.get("db") or {}).get("ok") is True


def test_pagination_pages_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "web.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir = tmp_path / "uploads"
    rules_path = Path("examples/repair_rules_ontology.json").resolve()

    monkeypatch.setenv("SRM_DB_PATH", str(db_path))
    monkeypatch.setenv("SRM_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SRM_UPLOADS_DIR", str(uploads_dir))
    monkeypatch.setenv("SRM_RULES_PATH", str(rules_path))
    monkeypatch.setenv("SRM_DEFAULT_ANALYSIS_DATE", "2026-04-18")

    # Seed larger dataset first
    from srm.web.seed_large import seed_large_demo_data_from_cli

    seed_large_demo_data_from_cli(
        reset_db=True, clients=40, orders=60, purchases=120, violations=80, seed=5
    )

    import srm.api.app as appmod

    appmod = reload(appmod)

    from fastapi.testclient import TestClient

    with TestClient(appmod.app) as client:
        client.get("/login")
        anon_csrf = client.cookies.get("srm_csrf_anon") or ""
        r = client.post(
            "/login",
            data={"username": "admin", "password": "admin123", "csrf_token": anon_csrf},
            follow_redirects=False,
        )
        assert r.status_code == 302

        # Carry cookies
        c = client
        for path in [
            "/clients",
            "/devices",
            "/orders",
            "/suppliers",
            "/purchases",
            "/violations",
            "/runs",
        ]:
            rr = c.get(f"{path}?page=1&page_size=10")
            assert rr.status_code == 200
