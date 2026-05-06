from __future__ import annotations

from pathlib import Path


def test_cli_experiment_risk_creates_artifacts(tmp_path: Path) -> None:
    from srm.cli import main

    out_dir = tmp_path / "experiments"
    rc = main(["experiment-risk", "--out-dir", str(out_dir), "--seed", "7", "--n-records", "600"])
    assert rc == 0

    assert (out_dir / "risk_comparison.json").exists()
    assert (out_dir / "risk_comparison.csv").exists()
    assert (out_dir / "plots" / "plot_f1_comparison.png").exists()
    assert (out_dir / "plots" / "plot_runtime_comparison.png").exists()
