from __future__ import annotations

import json
from importlib import reload
from pathlib import Path

import pytest


def test_api_analyze_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    payload = {
        "procurements": json.loads(Path("examples/procurements.json").read_text(encoding="utf-8"))[
            "procurements"
        ],
        "ontology": json.loads(Path("examples/rules_ontology.json").read_text(encoding="utf-8")),
        "analysis_date": "2026-04-18",
    }

    with TestClient(appmod.app) as c:
        r = c.post("/analyze", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert "summary" in body
        assert body["summary"]["records_total"] == 3
        assert body["summary"]["violations_total"] >= 1


@pytest.mark.parametrize(
    "payload",
    [
        {"procurements": "oops", "ontology": {}},
        {"procurements": [], "ontology": "oops"},
        {"procurements": [], "ontology": {}, "analysis_date": "18.04.2026"},
    ],
)
def test_api_analyze_bad_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict
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

    with TestClient(appmod.app) as c:
        r = c.post("/analyze", json=payload)
        # Pydantic validation errors are returned as 422.
        assert r.status_code in {400, 422}
