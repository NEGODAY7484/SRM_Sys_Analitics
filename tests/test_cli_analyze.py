from __future__ import annotations

from pathlib import Path

import pytest


def test_cli_analyze_creates_artifacts(tmp_path: Path) -> None:
    out_report = tmp_path / "report.json"
    charts_dir = tmp_path / "charts"
    log_dir = tmp_path / "logs"

    from srm.cli import main

    rc = main(
        [
            "analyze",
            "--data",
            str(Path("examples/procurements.json").resolve()),
            "--rules",
            str(Path("examples/rules_ontology.json").resolve()),
            "--out",
            str(out_report),
            "--charts-dir",
            str(charts_dir),
            "--log-dir",
            str(log_dir),
            "--no-ascii-charts",
            "--no-print-violations",
        ]
    )
    assert rc == 0

    assert out_report.exists()
    assert (log_dir / "srm.log").exists()

    pngs = sorted(charts_dir.glob("*.png"))
    assert len(pngs) >= 3


@pytest.mark.parametrize("bad_json", ["{", '{"procurements": {}}'])
def test_cli_analyze_handles_bad_json(tmp_path: Path, bad_json: str) -> None:
    data_path = tmp_path / "bad.json"
    data_path.write_text(bad_json, encoding="utf-8")

    out_report = tmp_path / "report.json"
    charts_dir = tmp_path / "charts"
    log_dir = tmp_path / "logs"

    from srm.cli import main

    rc = main(
        [
            "analyze",
            "--data",
            str(data_path),
            "--rules",
            str(Path("examples/rules_ontology.json").resolve()),
            "--out",
            str(out_report),
            "--charts-dir",
            str(charts_dir),
            "--log-dir",
            str(log_dir),
            "--no-ascii-charts",
            "--no-print-violations",
        ]
    )
    assert rc != 0
