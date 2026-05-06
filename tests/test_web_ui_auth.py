from __future__ import annotations

from importlib import reload
from pathlib import Path

import pytest


def _login_with_csrf(client, appmod, *, username: str, password: str):
    # Anonymous CSRF cookie for login form (double submit).
    client.get("/login")
    anon_csrf = client.cookies.get("srm_csrf_anon") or ""
    r = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": anon_csrf},
        follow_redirects=False,
    )
    return r


def _session_csrf(client, appmod) -> str:
    token = client.cookies.get("srm_session") or ""
    row = appmod.app.state.db.execute(
        "SELECT csrf_token FROM sessions WHERE token = ?",
        (token,),
    ).fetchone()
    return str(row["csrf_token"] or "") if row is not None else ""


@pytest.mark.parametrize("password,ok", [("admin123", True), ("wrong", False)])
def test_login_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, password: str, ok: bool
) -> None:
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
        r = client.get("/dashboard", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("/login")

        r = _login_with_csrf(client, appmod, username="admin", password=password)
        if ok:
            assert r.status_code == 302
            assert "srm_session=" in r.headers.get("set-cookie", "")
            r2 = client.get("/dashboard")
            assert r2.status_code == 200
            r3 = client.get("/srm/intelligent")
            assert r3.status_code == 200
        else:
            assert r.status_code == 200


def test_run_analysis_requires_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        # no auth -> redirect
        r = client.post("/runs/new", follow_redirects=False)
        assert r.status_code == 302

        # login as admin
        r = _login_with_csrf(client, appmod, username="admin", password="admin123")
        assert r.status_code == 302
        csrf = _session_csrf(client, appmod)

        # run analysis
        r = client.post("/runs/new", data={"csrf_token": csrf}, follow_redirects=False)
        assert r.status_code == 302

        # verify run persisted
        db = appmod.app.state.db
        row = db.execute("SELECT COUNT(1) AS c FROM analysis_runs").fetchone()
        assert int(row["c"]) >= 1

        # verify at least some violations exist on seeded dataset
        row2 = db.execute("SELECT COUNT(1) AS c FROM run_violations").fetchone()
        assert int(row2["c"]) >= 1

        types = {
            str(r["type"])
            for r in db.execute("SELECT DISTINCT type FROM run_violations").fetchall()
        }
        assert "BUDGET_EXCEEDED" in types
        assert "DISALLOWED_SUPPLIER" in types
        assert "DELIVERY_DELAY" in types
        assert "LOW_RATING_SUPPLIER" in types
        assert "MISSING_WARRANTY" in types
        assert "PRICE_TOO_HIGH" in types
        assert "RECURRING_SUPPLIER_VIOLATIONS" in types


def test_run_analysis_as_analyst_creates_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        # login as analyst
        r = _login_with_csrf(client, appmod, username="analyst", password="analyst123")
        assert r.status_code == 302
        csrf = _session_csrf(client, appmod)

        r = client.post("/runs/new", data={"csrf_token": csrf}, follow_redirects=False)
        assert r.status_code == 302

        db = appmod.app.state.db
        run = db.execute(
            "SELECT run_id, report_path, charts_dir, log_path, status FROM analysis_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        assert run is not None
        assert str(run["status"] or "") in {"success", ""}  # older DBs may lack status

        report_path = Path(str(run["report_path"]))
        charts_dir = Path(str(run["charts_dir"]))
        log_path = Path(str(run["log_path"]))
        assert report_path.exists()
        assert charts_dir.exists()
        assert len(list(charts_dir.glob("*.png"))) >= 1
        assert log_path.exists()

        vio_count = int(db.execute("SELECT COUNT(1) AS c FROM violations").fetchone()["c"])
        assert vio_count >= 1

        risks_count = int(db.execute("SELECT COUNT(1) AS c FROM purchase_risks").fetchone()["c"])
        assert risks_count >= 1


def test_run_analysis_denied_for_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        r = _login_with_csrf(client, appmod, username="master", password="master123")
        assert r.status_code == 302

        before = int(
            appmod.app.state.db.execute("SELECT COUNT(1) AS c FROM analysis_runs").fetchone()["c"]
        )
        r = client.post("/runs/new", follow_redirects=False)
        assert r.status_code == 302
        after = int(
            appmod.app.state.db.execute("SELECT COUNT(1) AS c FROM analysis_runs").fetchone()["c"]
        )
        assert after == before


def test_rules_page_shows_active_ruleset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        r = _login_with_csrf(client, appmod, username="admin", password="admin123")
        assert r.status_code == 302

        r2 = client.get("/rules")
        assert r2.status_code == 200
        body = r2.text
        assert "BUDGET_EXCEEDED" in body
        assert "не удалось прочитать правила" not in body.lower()
