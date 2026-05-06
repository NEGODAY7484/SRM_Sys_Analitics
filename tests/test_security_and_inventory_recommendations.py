from __future__ import annotations

from importlib import reload
from pathlib import Path

import pytest


def _login(client, appmod, *, username: str, password: str) -> None:
    client.get("/login")
    anon_csrf = client.cookies.get("srm_csrf_anon") or ""
    r = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": anon_csrf},
        follow_redirects=False,
    )
    assert r.status_code == 302


def test_security_page_admin_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "web.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    rules_path = Path("examples/repair_rules_ontology.json").resolve()

    monkeypatch.setenv("SRM_DB_PATH", str(db_path))
    monkeypatch.setenv("SRM_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SRM_RULES_PATH", str(rules_path))
    monkeypatch.setenv("SRM_DEFAULT_ANALYSIS_DATE", "2026-04-18")

    import srm.api.app as appmod

    appmod = reload(appmod)

    from fastapi.testclient import TestClient

    with TestClient(appmod.app) as client:
        _login(client, appmod, username="admin", password="admin123")
        r = client.get("/security")
        assert r.status_code == 200

    with TestClient(appmod.app) as client2:
        _login(client2, appmod, username="manager", password="manager123")
        r2 = client2.get("/security", follow_redirects=False)
        assert r2.status_code == 302


def test_inventory_recommendations_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "web.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    rules_path = Path("examples/repair_rules_ontology.json").resolve()

    monkeypatch.setenv("SRM_DB_PATH", str(db_path))
    monkeypatch.setenv("SRM_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SRM_RULES_PATH", str(rules_path))
    monkeypatch.setenv("SRM_DEFAULT_ANALYSIS_DATE", "2026-04-18")

    import srm.api.app as appmod

    appmod = reload(appmod)

    from fastapi.testclient import TestClient

    with TestClient(appmod.app) as client:
        _login(client, appmod, username="analyst", password="analyst123")
        r = client.get("/inventory/recommendations")
        assert r.status_code == 200
